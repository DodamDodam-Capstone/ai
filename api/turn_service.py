"""
음성 대화 턴 처리 (AI_Handoff 1. 음성 대화 API).

백엔드가 보낸 metadata(JSON)와 녹음 파일을 받아
STT -> 안전(입력) -> LLM -> 안전(출력) -> 표정 결정 -> TTS 를 돌리고 응답 JSON 을 만든다.
TTS 오디오는 B안(오디오 참조 전달)으로 넘긴다.

[응답]
- SUCCEEDED: 전부 성공. "error": null.
- FAILED: 어느 단계든 실패. "error": {stage, code}. expressionCode 는 null.
  이전 단계에서 만든 stt·reply 가 있으면 함께 싣는다 (부분 결과 유지 정책).

[텍스트 안전성 표기]
- VISIBLE: 원문을 저장·표시해도 된다.
- REDACTED: 가공문만 저장·표시한다. 아직 가공(마스킹) 기능이 없어 쓰지 않는다.
- OMITTED: text=null. 저장·표시 금지.

위험 단계(risk)는 응답에 싣지 않는다. 아이 발화 안전 검사 결과는 별도 테이블(A)로
저장하기로 했다. 그 저장이 생기기 전까지 위험 단계는 응답 어디에도 남지 않는다.

아동 발화 원문은 로그에 남기지 않는다. 실패 로그에는 식별자와 오류 코드만 남긴다.

HTTP 와 무관하게 짜서, 서버 없이 가짜 엔진으로 테스트할 수 있다 (tests/test_turn_service.py).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from core.interfaces import (
    EmotionClassifier,
    EmotionLabel,
    LLMEngine,
    RiskLevel,
    SafetyChecker,
    SafetyResult,
    STTEngine,
    STTResult,
    TTSEngine,
    UnsupportedAudioError,
    Verdict,
)
from core.orchestrator import TurnOrchestrator
from emotion.signals import to_signal
from api.audio_store import InMemoryAudioStore

_log = logging.getLogger(__name__)

SUPPORTED_LOCALES = {"ko-KR"}
# 응답 시각(expiresAt)은 백엔드 명세 예시처럼 KST 오프셋으로 쓴다.
KST = timezone(timedelta(hours=9))
# 입력 음성 최대 크기. 백엔드와 확정 전 임시값.
MAX_AUDIO_BYTES = 10 * 1024 * 1024
# B안은 응답 뒤 백엔드가 오디오를 내려받아 검증해야 deadline 안에 성공이 확정된다.
# 그 시간을 남기려고 AI 는 deadline 보다 이만큼 먼저 끝낸다.
DEADLINE_MARGIN_SEC = 1.0

# 도담이 캐릭터 표정 코드. 아이 감정 자체가 아니라 캐릭터가 지을 표정이다.
# FE 캐릭터 구현 범위와 확정 전 임시안. SURPRISED, SAD 는 아직 쓰지 않는다.
EXPRESSION_BY_EMOTION = {
    EmotionLabel.NEUTRAL: "NEUTRAL",
    EmotionLabel.JOY: "HAPPY",
    EmotionLabel.SADNESS: "CARING",
    EmotionLabel.ANGER: "CARING",
    EmotionLabel.FEAR: "CARING",
}
# 취약 신호(L2) 이상이면 감정과 무관하게 위로하는 표정을 짓는다.
CARING_RISK_LEVEL = RiskLevel.L2


# ---------------------------------------------------------------- 요청


class ChildInfo(BaseModel):
    nickname: str
    interests: list[str] = Field(default_factory=list)


class PreviousTurn(BaseModel):
    role: Literal["child", "assistant"]
    text: str


class TurnRequest(BaseModel):
    requestId: str
    conversationId: str
    turnId: str
    locale: str
    child: ChildInfo
    previousTurns: list[PreviousTurn]
    deadline: datetime


# ---------------------------------------------------------------- 단계별 오류


class StageError(Exception):
    """어느 단계에서 왜 실패했는지 담는 예외. 응답의 error 블록이 된다.

    stage: REQUEST, STT, SAFETY, LLM, TTS
    message 는 응답에 싣지 않고 서버 로그에만 남긴다.
    """

    def __init__(self, stage: str, code: str, message: str):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"stage": self.stage, "code": self.code}


class _Progress:
    """요청 하나의 진행 상황. 실패 시 어디까지 됐는지와 부분 결과를 꺼낸다."""

    def __init__(self):
        self.stage = "REQUEST"
        self.child_text: str | None = None
        # 입력 안전 검사를 마쳤으면 채워진다. 이게 있어야 stt 를 실패 응답에 실을 수 있다.
        self.input_results: list[SafetyResult] | None = None


class _StagedSTT(STTEngine):
    """STT 예외를 StageError 로 바꾼다. 오케스트레이터는 그대로 둔다."""

    def __init__(self, inner: STTEngine, progress: _Progress):
        self.inner = inner
        self.name = inner.name
        self._progress = progress

    async def transcribe(self, audio: bytes, *, sample_rate: int = 16000) -> STTResult:
        self._progress.stage = "STT"
        try:
            result = await self.inner.transcribe(audio, sample_rate=sample_rate)
        except UnsupportedAudioError as e:
            raise StageError("STT", "UNSUPPORTED_AUDIO", str(e)) from e
        except Exception as e:
            raise StageError("STT", "STT_FAILED", repr(e)) from e
        self._progress.child_text = result.text
        # 다음은 입력 안전 검사
        self._progress.stage = "SAFETY"
        return result


class _RecordedInputChecks:
    """입력 체커 결과를 진행 상황에 모은다. LLM 이 실패해도 stt 안전성을 판단하려고."""

    def __init__(self, checkers: list[SafetyChecker], progress: _Progress):
        self._progress = progress
        self._pending = len(checkers)
        self._results: list[SafetyResult] = []
        self.checkers = [_RecordingChecker(c, self) for c in checkers]
        if not checkers:
            progress.input_results = []

    def record(self, result: SafetyResult) -> None:
        self._results.append(result)
        if len(self._results) == self._pending:
            self._progress.input_results = list(self._results)


class _RecordingChecker(SafetyChecker):
    def __init__(self, inner: SafetyChecker, sink: _RecordedInputChecks):
        self.inner = inner
        self.name = inner.name
        self._sink = sink

    async def check(self, text: str, *, context: dict | None = None) -> SafetyResult:
        result = await self.inner.check(text, context=context)
        self._sink.record(result)
        return result


class _StagedLLM(LLMEngine):
    """LLM 예외를 StageError 로 바꾼다."""

    def __init__(self, inner: LLMEngine, progress: _Progress):
        self.inner = inner
        self.name = inner.name
        self._progress = progress

    async def generate(self, **kwargs):
        self._progress.stage = "LLM"
        try:
            result = await self.inner.generate(**kwargs)
        except Exception as e:
            raise StageError("LLM", "GENERATION_FAILED", repr(e)) from e
        # 다음은 출력 안전 검사
        self._progress.stage = "SAFETY"
        return result


class _UnusedTTS(TTSEngine):
    """오케스트레이터는 synthesize=False 로만 부른다. TTS 실패에도 텍스트를 살리려고 밖에서 한다."""

    name = "unused"

    async def synthesize(self, text: str, *, voice: str) -> bytes:
        raise RuntimeError("TurnService 는 오케스트레이터에서 TTS 를 돌리지 않는다")


# ---------------------------------------------------------------- 서비스


class TurnService:
    """백엔드 턴 요청 하나를 응답 JSON 하나로 바꾼다.

    엔진은 서버 시작 시 한 번 만들어 주입한다. 오케스트레이터는 요청마다 새로 만든다
    (demo.py 와 같은 패턴).
    """

    def __init__(
        self,
        *,
        stt: STTEngine,
        llm: LLMEngine,
        tts: TTSEngine | None,
        input_checkers: list[SafetyChecker],
        output_checkers: list[SafetyChecker],
        emotion_classifier: EmotionClassifier | None = None,
        audio_store: InMemoryAudioStore | None = None,
        tts_content_type: str = "audio/wav",
        tts_voice: str = "default",
        now=lambda: datetime.now(timezone.utc),
    ):
        """
        Args:
            tts: None 이면 TTS 미구성. 텍스트까지만 만들고 FAILED(TTS_UNAVAILABLE) 로 응답한다.
            now: 현재 시각. 테스트에서 기한을 다루려고 주입한다.
        """
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.input_checkers = input_checkers
        self.output_checkers = output_checkers
        self.emotion_classifier = emotion_classifier
        self.audio_store = audio_store or InMemoryAudioStore(now=now)
        self.tts_content_type = tts_content_type
        self.tts_voice = tts_voice
        self._now = now

    async def handle(self, audio: bytes, metadata: dict) -> dict:
        """
        Args:
            audio: 녹음 파일 원본 바이트 (WebM/Opus. m4a, wav 도 읽는다).
            metadata: 백엔드가 보낸 metadata JSON 을 파싱한 dict.

        Returns:
            백엔드에 돌려줄 응답 dict. 예외를 밖으로 던지지 않는다.
        """
        ids = _ids(metadata)
        progress = _Progress()
        try:
            return await self._handle(audio, metadata, progress)
        except StageError as e:
            return self._failed(ids, e, progress)
        except asyncio.TimeoutError:
            return self._failed(ids, _deadline_error(progress.stage), progress)
        except Exception as e:
            return self._failed(
                ids, StageError(progress.stage, "INTERNAL_ERROR", repr(e)), progress
            )

    async def _handle(self, audio: bytes, metadata: dict, progress: _Progress) -> dict:
        try:
            req = TurnRequest.model_validate(metadata)
        except ValidationError as e:
            raise StageError("REQUEST", "INVALID_REQUEST", _first_error(e)) from e
        if req.deadline.tzinfo is None:
            raise StageError(
                "REQUEST", "INVALID_REQUEST", "deadline must include timezone"
            )
        if req.locale not in SUPPORTED_LOCALES:
            raise StageError(
                "REQUEST", "UNSUPPORTED_LOCALE", f"locale {req.locale!r}"
            )
        if len(audio) > MAX_AUDIO_BYTES:
            raise StageError("REQUEST", "AUDIO_TOO_LARGE", f"{len(audio)} bytes")

        # 1~4. STT ~ 출력 안전 검사
        timeout = self._remaining(req)
        inputs = _RecordedInputChecks(self.input_checkers, progress)
        orch = TurnOrchestrator(
            stt=_StagedSTT(self.stt, progress),
            llm=_StagedLLM(self.llm, progress),
            tts=_UnusedTTS(),
            input_checkers=inputs.checkers,
            output_checkers=self.output_checkers,
        )
        result = await asyncio.wait_for(
            orch.run(
                audio,
                profile={"name": req.child.nickname, "interests": req.child.interests},
                history=[(t.role, t.text) for t in req.previousTurns],
                synthesize=False,
            ),
            timeout=timeout,
        )

        # 오케스트레이터는 빈 인식 결과를 되묻기 문장으로 조기 반환한다.
        # 백엔드에는 실패로 알리고 재녹음 여부를 맡긴다.
        if not result.child_text:
            raise StageError("STT", "NO_SPEECH", "empty transcription")

        level = _input_level(progress.input_results)
        stt_block = _stt_block(result.child_text, progress.input_results)
        reply_block = _reply_block(result.reply_text, level)
        expression = await self._expression(result.child_text, level)

        # 5. TTS. 실패하면 stt·reply 를 실은 FAILED 로 보낸다.
        progress.stage = "TTS"
        try:
            tts_block = await self._synthesize(result.reply_text, req)
        except StageError as e:
            body = self._failed(_ids(metadata), e, progress)
            body["reply"] = reply_block
            return body

        return {
            **_ids(metadata),
            "status": "SUCCEEDED",
            "stt": stt_block,
            "reply": reply_block,
            "expressionCode": expression,
            "tts": tts_block,
            "error": None,
        }

    async def _synthesize(self, text: str, req: TurnRequest) -> dict:
        if self.tts is None:
            raise StageError("TTS", "TTS_UNAVAILABLE", "TTS is not configured")
        try:
            timeout = self._remaining(req)
            audio = await asyncio.wait_for(
                self.tts.synthesize(text, voice=self.tts_voice), timeout=timeout
            )
        except asyncio.TimeoutError as e:
            raise _deadline_error("TTS") from e
        except Exception as e:
            raise StageError("TTS", "TTS_GENERATION_FAILED", repr(e)) from e
        ref, expires_at = self.audio_store.put(audio, self.tts_content_type)
        return {
            "audioReference": ref,
            "contentType": self.tts_content_type,
            "allowed": True,
            "expiresAt": expires_at.astimezone(KST).isoformat(timespec="seconds"),
        }

    async def _expression(self, child_text: str, level: RiskLevel) -> str | None:
        """도담이 표정 코드. 감정 분류가 실패해도 턴을 깨지 않고 null 을 준다."""
        if level >= CARING_RISK_LEVEL:
            return "CARING"
        if self.emotion_classifier is None:
            return None
        try:
            emo = await self.emotion_classifier.classify(child_text)
        except Exception:
            _log.exception("감정 분류 실패")
            return None
        label = to_signal(emo, turn_id=None, child_id="").label
        return EXPRESSION_BY_EMOTION.get(label)

    def _remaining(self, req: TurnRequest) -> float:
        remaining = (req.deadline - self._now()).total_seconds() - DEADLINE_MARGIN_SEC
        if remaining <= 0:
            raise asyncio.TimeoutError
        return remaining

    def _failed(self, ids: dict, error: StageError, progress: _Progress) -> dict:
        # message 는 예외 설명이라 응답에는 싣지 않고 여기에만 남긴다. 아동 발화는 넣지 않는다.
        _log.warning(
            "turn failed requestId=%s turnId=%s stage=%s code=%s detail=%s",
            ids.get("requestId"),
            ids.get("turnId"),
            error.stage,
            error.code,
            error.message,
        )
        body = failed_response(ids, error)
        # 입력 안전 검사까지 끝났으면 stt 를 함께 싣는다.
        if progress.child_text and progress.input_results is not None:
            body["stt"] = _stt_block(progress.child_text, progress.input_results)
        return body


# ---------------------------------------------------------------- 응답 조립


def _input_level(results: list[SafetyResult] | None) -> RiskLevel:
    return max((r.level for r in results or []), default=RiskLevel.L0)


def _visible(text: str) -> dict:
    return {
        "text": text,
        "visibility": "VISIBLE",
        "saveAllowed": True,
        "displayAllowed": True,
    }


def _omitted() -> dict:
    return {
        "text": None,
        "visibility": "OMITTED",
        "saveAllowed": False,
        "displayAllowed": False,
    }


def _stt_block(text: str, input_results: list[SafetyResult]) -> dict:
    """아이 발화. L4(보호 필요)와 입력 BLOCK 은 원문을 내보내지 않는다.

    telemetry/logger.py 와 같은 규칙: L4 원문은 보호자 기록에 남기지 않는다.
    """
    level = _input_level(input_results)
    blocked = any(r.verdict is Verdict.BLOCK for r in input_results)
    if level >= RiskLevel.L4 or blocked:
        return _omitted()
    return _visible(text)


def _reply_block(text: str, level: RiskLevel) -> dict:
    """도담이 응답. L4 턴은 응답 문장도 저장하지 않는다.

    L4 보호 응답이 보호자 기록에 남으면 아이가 무엇을 털어놨는지 드러난다
    (telemetry/logger.py 와 같은 규칙). 아이는 TTS 음성으로 듣는다.
    """
    if level >= RiskLevel.L4:
        return _omitted()
    return _visible(text)


def failed_response(source: dict, error: StageError) -> dict:
    """실패 응답 뼈대. 부분 결과는 호출부가 채운다."""
    return {
        **_ids(source),
        "status": "FAILED",
        "stt": None,
        "reply": None,
        "expressionCode": None,
        "tts": None,
        "error": error.to_dict(),
    }


def _ids(source) -> dict:
    src = source if isinstance(source, dict) else {}
    return {
        "requestId": src.get("requestId"),
        "conversationId": src.get("conversationId"),
        "turnId": src.get("turnId"),
    }


def _deadline_error(stage: str) -> StageError:
    return StageError(stage, "DEADLINE_EXCEEDED", "deadline exceeded")


def _first_error(e: ValidationError) -> str:
    err = e.errors()[0]
    loc = ".".join(str(p) for p in err["loc"])
    return f"{loc}: {err['msg']}"
