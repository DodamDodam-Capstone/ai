"""AI 내부 API 의 HTTP 계약: Part 이름, 엔드포인트, 404/410, 서버 간 인증.

fastapi 가 requirements.txt 에 없는 환경(CI)에서는 건너뛴다.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import api.server as server  # noqa: E402
from api.turn_service import TurnService  # noqa: E402
from core.fakes import FakeLLM, FakeSTT, FakeTTS  # noqa: E402
from safety.checkers import RuleChecker  # noqa: E402

META = {
    "requestId": "request-001",
    "conversationId": "conversation-001",
    "turnId": "turn-001",
    "locale": "ko-KR",
    "child": {"nickname": "도담", "interests": []},
    "previousTurns": [],
    "deadline": "2099-01-01T00:00:00+09:00",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("AI_SERVER_TOKEN", raising=False)
    monkeypatch.setattr(server, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        server,
        "build_service",
        lambda: TurnService(
            stt=FakeSTT("오늘 친구랑 놀았어!"),
            llm=FakeLLM(["정말 재미있었겠다!"]),
            tts=FakeTTS(),
            input_checkers=[RuleChecker()],
            output_checkers=[RuleChecker()],
        ),
    )
    with TestClient(server.app) as c:
        yield c


def post_turn(client, headers=None):
    # 백엔드(Spring)처럼 metadata 를 application/json Part 로 보낸다.
    return client.post(
        "/internal/ai/turns",
        files={
            "metadata": (None, json.dumps(META), "application/json"),
            "audio": ("audio.webm", b"<webm>", "audio/webm"),
        },
        headers=headers or {},
    )


def test_turn_and_audio_download(client):
    r = post_turn(client)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "SUCCEEDED"
    assert body["conversationId"] == "conversation-001"

    audio = client.get(f"/internal/ai/audio/{body['tts']['audioReference']}")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"


def test_unknown_audio_is_404(client):
    assert client.get("/internal/ai/audio/audio-unknown").status_code == 404


def test_missing_metadata_part(client):
    r = client.post(
        "/internal/ai/turns", files={"audio": ("a.webm", b"x", "audio/webm")}
    )
    assert r.json()["error"] == {"stage": "REQUEST", "code": "INVALID_REQUEST"}


def test_server_token_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("AI_SERVER_TOKEN", "secret")

    assert post_turn(client).status_code == 401
    assert post_turn(client, {"Authorization": "Bearer wrong"}).status_code == 401
    assert post_turn(client, {"Authorization": "Bearer secret"}).status_code == 200
