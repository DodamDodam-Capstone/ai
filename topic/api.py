"""백엔드가 세션 종료 시 호출하는 HTTP 엔드포인트 (FastAPI).
pip install fastapi uvicorn / 실행 (저장소 루트에서): uvicorn topic.api:app --port 8001

- POST /topic-analysis/{session_id}   → 202, 백그라운드에서 분석 시작
- GET  /topic-analysis/{session_id}   → 작업 상태 + 결과 (대시보드/백엔드 조회용)

트래픽이 커지면 BackgroundTasks 대신 Celery/RQ + Redis 큐로 교체한다."""

import os

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI

from .llm_client import GeminiTopicLLM
from .pipeline import process_session_topic
from .repo_sqlite import SqliteRepo

load_dotenv()  # 저장소 루트 .env의 GEMINI_API_KEY·GEMINI_MODEL (이미 설정된 환경변수는 유지)
app = FastAPI(title="DodamDodam Topic Analysis")
repo = SqliteRepo(os.getenv("TOPIC_DB", "topic.db"))
llm = None


def get_llm():
    global llm
    if llm is None:
        llm = GeminiTopicLLM()
    return llm


@app.post("/topic-analysis/{session_id}", status_code=202)
def start(session_id: str, bg: BackgroundTasks):
    repo.set_job_status(session_id, "queued")
    bg.add_task(process_session_topic, session_id, get_llm(), repo)
    return {"session_id": session_id, "status": "queued"}


@app.get("/topic-analysis/{session_id}")
def result(session_id: str):
    job = repo.get_job(session_id) or {"status": "not_found"}
    topics = repo.get_topics(session_id) if job.get("status") == "done" else []
    return {"session_id": session_id, **job, "topics": topics}
