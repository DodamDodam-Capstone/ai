"""
AI 내부 API 서버 (AI_Handoff 1. 음성 대화 API, TTS 는 B안 오디오 참조 전달).

    .venv/bin/uvicorn api.server:app --port 8000

POST /internal/ai/turns   multipart/form-data
    metadata: application/json Part (requestId, conversationId, turnId, locale, child,
              previousTurns, deadline)
    audio:    audio/webm(Opus) Part. 바이너리 그대로.
    -> application/json 응답 (api/turn_service.py 참고).
       성공·실패 모두 HTTP 200 이고 body 의 status 로 구분한다.

GET /internal/ai/audio/{audioReference}
    -> 200 TTS 음성 / 404 참조 없음 / 410 참조 만료

GET /health
    -> 모델 로딩이 끝났는지. 인증 없음.

서버 간 인증: AI_SERVER_TOKEN 환경변수가 있으면 /internal/** 요청에
"Authorization: Bearer <토큰>" 을 요구한다. 방식은 백엔드와 확정 전 임시안.

엔진은 서버 시작 시 한 번 만든다. Qwen3-ASR 로딩에 수십 초가 걸린다.
필요한 환경변수: GEMINI_API_KEY (선택: GEMINI_MODEL, QWEN_ASR_MODEL, AI_SERVER_TOKEN).
TTS 엔진은 아직 없어서 응답은 FAILED(TTS_UNAVAILABLE)로 나간다. stt·reply 는 실린다.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from starlette.datastructures import UploadFile

from api.audio_store import Lookup
from api.turn_service import StageError, TurnService, failed_response

_log = logging.getLogger(__name__)
_service: TurnService | None = None


def build_service() -> TurnService:
    # 무거운 import 는 서버를 띄울 때만 한다.
    from emotion.checkers import RuleEmotionClassifier
    from llm.gemini import GeminiEngine
    from safety.checkers import ReadabilityChecker, RuleChecker
    from stt.qwen import QwenSTT

    return TurnService(
        stt=QwenSTT(),
        llm=GeminiEngine(),
        tts=None,
        input_checkers=[RuleChecker()],
        output_checkers=[RuleChecker(), ReadabilityChecker()],
        emotion_classifier=RuleEmotionClassifier(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _service
    load_dotenv()
    if not os.environ.get("AI_SERVER_TOKEN"):
        _log.warning("AI_SERVER_TOKEN 이 없어 서버 간 인증 없이 동작한다. 개발용으로만 쓸 것.")
    _service = build_service()
    yield


app = FastAPI(title="DodamDodam AI", lifespan=lifespan)


def require_server_token(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("AI_SERVER_TOKEN")
    if not token:
        return
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(status_code=401)


@app.get("/health")
async def health():
    return {"ready": _service is not None}


@app.post("/internal/ai/turns", dependencies=[Depends(require_server_token)])
async def turns(request: Request):
    form = await request.form()
    raw_meta = form.get("metadata")
    audio = form.get("audio")

    # metadata 는 application/json Part 다. 클라이언트에 따라 파일 Part 로 올 수도 있다.
    if isinstance(raw_meta, UploadFile):
        raw_meta = (await raw_meta.read()).decode("utf-8", errors="replace")
    try:
        meta = json.loads(raw_meta) if raw_meta is not None else None
    except json.JSONDecodeError:
        meta = None
    if not isinstance(meta, dict):
        return failed_response(
            {}, StageError("REQUEST", "INVALID_REQUEST", "metadata part")
        )
    if not isinstance(audio, UploadFile):
        return failed_response(
            meta, StageError("REQUEST", "INVALID_REQUEST", "audio part")
        )
    if _service is None:
        return failed_response(
            meta, StageError("REQUEST", "NOT_READY", "models are still loading")
        )
    return await _service.handle(await audio.read(), meta)


@app.get(
    "/internal/ai/audio/{ref}", dependencies=[Depends(require_server_token)]
)
async def tts_audio(ref: str):
    if _service is None:
        raise HTTPException(status_code=503)
    status, audio, content_type = _service.audio_store.get(ref)
    if status is Lookup.EXPIRED:
        raise HTTPException(status_code=410)
    if status is Lookup.MISSING:
        raise HTTPException(status_code=404)
    return Response(content=audio, media_type=content_type)
