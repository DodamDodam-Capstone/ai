"""
백엔드 통합 형식 검증 (docs/api/AI_HANDOFF.md 1. 음성 대화 API).

평가 세트 음성을 백엔드가 보내는 것과 같은 WebM(Opus)으로 바꿔
POST /internal/ai/turns 에 multipart(metadata JSON Part + audio Part)로 보내고,
  1) 응답이 명세 형식을 지키는지
  2) 응답의 stt.text 가 정답과 얼마나 맞는지 (CER)
  3) B안 오디오 다운로드(GET /internal/ai/audio/{ref})가 되는지
를 확인한다. STT 는 실제 Qwen3-ASR 1.7B 다.

    .venv/bin/python -m stt_eval.be_format_check                 # 나이별 5개씩 20개
    .venv/bin/python -m stt_eval.be_format_check --limit-per-age 25

LLM 은 GEMINI_API_KEY 가 있으면 Gemini, 없으면 고정 답변을 내는 가짜 엔진을 쓴다.
TTS 엔진은 아직 없어서 가짜 엔진(텍스트 바이트)을 쓴다. 이 검증의 대상은 STT 와 형식이다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stt_eval.dataset import load_eval_set
from stt_eval.metrics import cer, normalize

RESULT_TXT = Path(__file__).resolve().parent / "results" / "be_format_check.txt"
KST = timezone(timedelta(hours=9))
RESPONSE_KEYS = {
    "requestId",
    "conversationId",
    "turnId",
    "status",
    "stt",
    "reply",
    "expressionCode",
    "tts",
    "error",
}
TEXT_KEYS = {"text", "visibility", "saveAllowed", "displayAllowed"}
TTS_KEYS = {"audioReference", "contentType", "allowed", "expiresAt"}
EXPRESSIONS = {"HAPPY", "NEUTRAL", "CARING", "SURPRISED", "SAD", None}


def wav_to_webm(wav_bytes: bytes) -> bytes:
    """브라우저 MediaRecorder 와 같은 WebM(Opus, 48kHz 모노)로 바꾼다."""
    import av

    out_buf = io.BytesIO()
    with av.open(io.BytesIO(wav_bytes)) as src, av.open(out_buf, "w", format="webm") as dst:
        stream = dst.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        for frame in src.decode(audio=0):
            for out in resampler.resample(frame):
                for packet in stream.encode(out):
                    dst.mux(packet)
        for packet in stream.encode(None):
            dst.mux(packet)
    return out_buf.getvalue()


def check_text_block(block, name: str) -> list[str]:
    if block is None:
        return []
    errors = []
    if set(block) != TEXT_KEYS:
        errors.append(f"{name} 필드 {sorted(block)}")
    vis = block.get("visibility")
    flags = (block.get("saveAllowed"), block.get("displayAllowed"))
    if vis in ("VISIBLE", "REDACTED"):
        if not isinstance(block.get("text"), str) or flags != (True, True):
            errors.append(f"{name} {vis} 인데 text/허용값이 맞지 않음")
    elif vis == "OMITTED":
        if block.get("text") is not None or flags != (False, False):
            errors.append(f"{name} OMITTED 인데 text/허용값이 맞지 않음")
    else:
        errors.append(f"{name}.visibility={vis!r}")
    return errors


def check_response(body: dict, meta: dict) -> list[str]:
    """명세 형식 위반 목록. 비어 있으면 통과."""
    errors = []
    if set(body) != RESPONSE_KEYS:
        errors.append(f"응답 필드 {sorted(body)}")
    for key in ("requestId", "conversationId", "turnId"):
        if body.get(key) != meta[key]:
            errors.append(f"{key} 불일치")
    errors += check_text_block(body.get("stt"), "stt")
    errors += check_text_block(body.get("reply"), "reply")
    if body.get("expressionCode") not in EXPRESSIONS:
        errors.append(f"expressionCode={body.get('expressionCode')!r}")

    if body.get("status") == "SUCCEEDED":
        if body.get("error") is not None:
            errors.append("SUCCEEDED 인데 error 가 있음")
        tts = body.get("tts") or {}
        if set(tts) != TTS_KEYS:
            errors.append(f"tts 필드 {sorted(tts)}")
        elif datetime.fromisoformat(tts["expiresAt"]).tzinfo is None:
            errors.append("tts.expiresAt 에 시간대 없음")
    elif body.get("status") == "FAILED":
        if set(body.get("error") or {}) != {"stage", "code"}:
            errors.append(f"error 필드 {body.get('error')}")
        if body.get("expressionCode") is not None or body.get("tts") is not None:
            errors.append("FAILED 인데 expressionCode/tts 가 있음")
    else:
        errors.append(f"status={body.get('status')!r}")
    return errors


def build_service():
    from api.turn_service import TurnService
    from core.fakes import FakeLLM, FakeTTS
    from emotion.checkers import RuleEmotionClassifier
    from safety.checkers import ReadabilityChecker, RuleChecker
    from stt.qwen import QwenSTT

    if os.environ.get("GEMINI_API_KEY"):
        from llm.gemini import GeminiEngine

        llm, llm_name = GeminiEngine(), "Gemini"
    else:
        llm, llm_name = FakeLLM(["우와, 그랬구나! 더 이야기해 줄래?"]), "가짜(고정 답변)"
    service = TurnService(
        stt=QwenSTT(),
        llm=llm,
        tts=FakeTTS(),
        input_checkers=[RuleChecker()],
        output_checkers=[RuleChecker(), ReadabilityChecker()],
        emotion_classifier=RuleEmotionClassifier(),
    )
    return service, llm_name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="age_400", choices=["age_400", "hard_100"])
    parser.add_argument("--limit-per-age", type=int, default=5)
    args = parser.parse_args()

    from dotenv import load_dotenv
    from fastapi.testclient import TestClient

    import api.server as server

    load_dotenv()
    samples = load_eval_set(args.set, args.limit_per_age)
    service, llm_name = build_service()
    server.build_service = lambda: service
    server.load_dotenv = lambda: None

    rows, failures = [], 0
    conversation_id = str(uuid.uuid4())
    with TestClient(server.app) as client:
        for i, sample in enumerate(samples, 1):
            meta = {
                "requestId": str(uuid.uuid4()),
                "conversationId": conversation_id,
                "turnId": str(uuid.uuid4()),
                "locale": "ko-KR",
                "child": {"nickname": "도담", "interests": ["공룡", "우주"]},
                "previousTurns": [],
                "deadline": (datetime.now(KST) + timedelta(seconds=30)).isoformat(),
            }
            webm = wav_to_webm(sample.wav_path.read_bytes())
            headers = {}
            if os.environ.get("AI_SERVER_TOKEN"):
                headers["Authorization"] = f"Bearer {os.environ['AI_SERVER_TOKEN']}"

            start = time.perf_counter()
            resp = client.post(
                "/internal/ai/turns",
                files={
                    "metadata": (None, json.dumps(meta, ensure_ascii=False), "application/json"),
                    "audio": ("audio.webm", webm, "audio/webm"),
                },
                headers=headers,
            )
            elapsed = time.perf_counter() - start
            body = resp.json()
            errors = [] if resp.status_code == 200 else [f"HTTP {resp.status_code}"]
            errors += check_response(body, meta)

            if body.get("status") == "SUCCEEDED":
                ref = body["tts"]["audioReference"]
                got = client.get(f"/internal/ai/audio/{ref}", headers=headers)
                if got.status_code != 200:
                    errors.append(f"오디오 다운로드 HTTP {got.status_code}")

            stt_text = (body.get("stt") or {}).get("text")
            sample_cer = (
                cer(normalize(sample.reference), normalize(stt_text))[0]
                if stt_text is not None
                else None
            )
            failures += bool(errors)
            rows.append((sample, body, sample_cer, elapsed, errors))
            print(
                f"[{i}/{len(samples)}] {sample.age}세 {body.get('status')} "
                f"CER {'-' if sample_cer is None else f'{sample_cer * 100:.1f}%'} "
                f"{elapsed:.2f}s {'OK' if not errors else errors}"
            )

    cers = [c for _, _, c, _, _ in rows if c is not None]
    times = [t for _, _, _, t, _ in rows]
    statuses = {}
    for _, body, _, _, _ in rows:
        statuses[body.get("status")] = statuses.get(body.get("status"), 0) + 1
    lines = [
        f"백엔드 통합 형식 검증: {args.set}, 나이별 {args.limit_per_age}개 (총 {len(rows)}개)",
        f"STT: {service.stt.model_name} / LLM: {llm_name} / TTS: 가짜",
        f"입력: WebM(Opus) multipart, POST /internal/ai/turns",
        "",
        f"형식 검증 통과: {len(rows) - failures}/{len(rows)}",
        f"응답 status: {statuses}",
        f"STT Normalized CER 문장 평균: {statistics.mean(cers) * 100:.2f}% "
        f"(정확 일치 {sum(c == 0 for c in cers)}/{len(cers)})",
        f"요청 1건 처리 시간: 중간값 {statistics.median(times):.2f}초 | "
        f"최대 {max(times):.2f}초",
    ]
    for sample, body, _, _, errors in rows:
        if errors:
            lines.append(f"  실패 {sample.wav_name}: {errors}")
    summary = "\n".join(lines) + "\n"
    RESULT_TXT.parent.mkdir(parents=True, exist_ok=True)
    RESULT_TXT.write_text(summary, encoding="utf-8")
    print("\n" + summary)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
