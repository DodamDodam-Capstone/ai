"""음성 대화 턴: 백엔드 요청 -> 응답 JSON (AI_Handoff 1. 음성 대화 API).

가짜 엔진으로 status / error / visibility / 부분 결과 / 표정 규칙을 검증한다.
모델과 API 키 없이 돈다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from api.audio_store import InMemoryAudioStore, Lookup
from api.turn_service import TurnService
from core.fakes import FakeEmotionClassifier, FakeLLM, FakeSTT, FakeTTS
from core.interfaces import (
    EmotionLabel,
    LLMEngine,
    STTEngine,
    STTResult,
    TTSEngine,
    UnsupportedAudioError,
)
from safety.checkers import ReadabilityChecker, RuleChecker

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 31, 22, 0, 0, tzinfo=KST)
IDS = {
    "requestId": "550e8400-e29b-41d4-a716-446655440000",
    "conversationId": "33333333-3333-4333-8333-333333333333",
    "turnId": "44444444-4444-4444-8444-444444444444",
}
OMITTED = {
    "text": None,
    "visibility": "OMITTED",
    "saveAllowed": False,
    "displayAllowed": False,
}


def visible(text: str) -> dict:
    return {
        "text": text,
        "visibility": "VISIBLE",
        "saveAllowed": True,
        "displayAllowed": True,
    }


def metadata(**overrides) -> dict:
    meta = {
        **IDS,
        "locale": "ko-KR",
        "child": {"nickname": "도담", "interests": ["공룡", "우주"]},
        "previousTurns": [
            {"role": "child", "text": "나는 공룡을 좋아해."},
            {"role": "assistant", "text": "어떤 공룡이 가장 좋아?"},
        ],
        "deadline": (NOW + timedelta(seconds=30)).isoformat(),
    }
    meta.update(overrides)
    return meta


class _BrokenSTT(STTEngine):
    name = "broken_stt"

    def __init__(self, exc: Exception):
        self.exc = exc

    async def transcribe(self, audio: bytes, *, sample_rate: int = 16000) -> STTResult:
        raise self.exc


class _BrokenLLM(LLMEngine):
    name = "broken_llm"

    async def generate(self, **kwargs):
        raise RuntimeError("vendor down")


class _BrokenTTS(TTSEngine):
    name = "broken_tts"

    async def synthesize(self, text: str, *, voice: str) -> bytes:
        raise RuntimeError("tts down")


def run(
    *,
    child_text="오늘 친구랑 놀았어!",
    reply="정말 재미있었겠다!",
    stt=None,
    llm=None,
    tts="fake",
    emotion=EmotionLabel.JOY,
    meta=None,
    audio=b"<audio>",
):
    service = TurnService(
        stt=stt or FakeSTT(child_text),
        llm=llm or FakeLLM([reply]),
        tts=FakeTTS() if tts == "fake" else tts,
        input_checkers=[RuleChecker()],
        output_checkers=[RuleChecker(), ReadabilityChecker()],
        emotion_classifier=FakeEmotionClassifier(emotion),
        now=lambda: NOW,
    )
    body = asyncio.run(service.handle(audio, meta or metadata()))
    return body, service


# ---------------------------------------------------------------- 성공


def test_success_shape():
    body, service = run()

    assert {k: body[k] for k in IDS} == IDS
    assert body["status"] == "SUCCEEDED"
    assert body["stt"] == visible("오늘 친구랑 놀았어!")
    assert body["reply"] == visible("정말 재미있었겠다!")
    assert body["expressionCode"] == "HAPPY"
    assert body["error"] is None
    assert set(body) == {*IDS, "status", "stt", "reply", "expressionCode", "tts", "error"}

    tts = body["tts"]
    assert set(tts) == {"audioReference", "contentType", "allowed", "expiresAt"}
    assert tts["contentType"] == "audio/wav"
    assert tts["allowed"] is True
    assert datetime.fromisoformat(tts["expiresAt"]) > NOW
    status, audio, _ = service.audio_store.get(tts["audioReference"])
    assert status is Lookup.FOUND
    assert audio == "정말 재미있었겠다!".encode("utf-8")


def test_sad_child_gets_caring_expression():
    body, _ = run(emotion=EmotionLabel.SADNESS)

    assert body["expressionCode"] == "CARING"


def test_l4_omits_texts_but_keeps_tts():
    # L4 원문과 보호 응답은 보호자 기록에 남기면 안 된다. 아이는 음성으로 듣는다.
    body, _ = run(child_text="아빠가 나 때렸어")

    assert body["status"] == "SUCCEEDED"
    assert body["stt"] == OMITTED
    assert body["reply"] == OMITTED
    assert body["expressionCode"] == "CARING"
    assert body["tts"]["allowed"] is True


# ---------------------------------------------------------------- 실패


def test_no_speech():
    body, _ = run(child_text="")

    assert body == {
        **IDS,
        "status": "FAILED",
        "stt": None,
        "reply": None,
        "expressionCode": None,
        "tts": None,
        "error": {"stage": "STT", "code": "NO_SPEECH"},
    }


def test_llm_failure_keeps_stt():
    body, _ = run(llm=_BrokenLLM())

    assert body["status"] == "FAILED"
    assert body["stt"] == visible("오늘 친구랑 놀았어!")
    assert body["reply"] is None
    assert body["expressionCode"] is None
    assert body["tts"] is None
    assert body["error"] == {"stage": "LLM", "code": "GENERATION_FAILED"}


def test_llm_failure_on_l4_does_not_leak_stt():
    body, _ = run(child_text="아빠가 나 때렸어", llm=_BrokenLLM())

    # L4 는 보호 응답이 고정이라 LLM 을 부르지 않는다. 그래도 원문은 나가면 안 된다.
    assert body["stt"] == OMITTED


def test_tts_failure_keeps_stt_and_reply():
    body, _ = run(tts=_BrokenTTS())

    assert body["status"] == "FAILED"
    assert body["stt"] == visible("오늘 친구랑 놀았어!")
    assert body["reply"] == visible("정말 재미있었겠다!")
    assert body["expressionCode"] is None
    assert body["tts"] is None
    assert body["error"] == {"stage": "TTS", "code": "TTS_GENERATION_FAILED"}


def test_no_tts_engine():
    body, _ = run(tts=None)

    assert body["error"] == {"stage": "TTS", "code": "TTS_UNAVAILABLE"}


def test_unreadable_audio():
    body, _ = run(stt=_BrokenSTT(UnsupportedAudioError("bad file")))

    assert body["stt"] is None
    assert body["error"] == {"stage": "STT", "code": "UNSUPPORTED_AUDIO"}


def test_stt_crash():
    body, _ = run(stt=_BrokenSTT(RuntimeError("gpu oom")))

    assert body["error"] == {"stage": "STT", "code": "STT_FAILED"}


def test_missing_field_is_invalid_request():
    meta = metadata()
    del meta["previousTurns"]
    body, _ = run(meta=meta)

    assert {k: body[k] for k in IDS} == IDS
    assert body["error"] == {"stage": "REQUEST", "code": "INVALID_REQUEST"}


def test_unsupported_locale():
    body, _ = run(meta=metadata(locale="en-US"))

    assert body["error"] == {"stage": "REQUEST", "code": "UNSUPPORTED_LOCALE"}


def test_audio_too_large():
    body, _ = run(audio=b"\0" * (10 * 1024 * 1024 + 1))

    assert body["error"] == {"stage": "REQUEST", "code": "AUDIO_TOO_LARGE"}


def test_past_deadline():
    body, _ = run(meta=metadata(deadline=(NOW - timedelta(seconds=1)).isoformat()))

    assert body["error"] == {"stage": "REQUEST", "code": "DEADLINE_EXCEEDED"}


# ---------------------------------------------------------------- 오디오 참조


def test_audio_store_found_expired_missing():
    clock = [NOW]
    store = InMemoryAudioStore(ttl_sec=60, now=lambda: clock[0])
    ref, expires_at = store.put(b"wav", "audio/wav")

    assert expires_at == NOW + timedelta(seconds=60)
    assert store.get(ref)[0] is Lookup.FOUND

    clock[0] = NOW + timedelta(seconds=61)
    assert store.get(ref)[0] is Lookup.EXPIRED
    assert store.get("audio-unknown")[0] is Lookup.MISSING
