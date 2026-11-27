"""로컬 개발·테스트용 저장소(SQLite). 운영에서는 같은 메서드를
백엔드 DB(MySQL/PostgreSQL 등)로 구현하거나, 백엔드 API를 호출하도록 바꾼다."""

import json
import sqlite3

from .schema import SessionTopics, Turn

DDL = """
CREATE TABLE IF NOT EXISTS conversation_turns (
  session_id TEXT, turn_id INTEGER, child_text TEXT, ai_text TEXT,
  PRIMARY KEY (session_id, turn_id));
CREATE TABLE IF NOT EXISTS session_topics (            -- C.1
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL, schema_version TEXT NOT NULL,
  category TEXT NOT NULL, subtopic TEXT, topic TEXT NOT NULL,
  sentiment TEXT NOT NULL, key_point TEXT NOT NULL, turn_ids TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_st_session ON session_topics(session_id);
CREATE TABLE IF NOT EXISTS topic_analysis_jobs (
  session_id TEXT PRIMARY KEY, status TEXT NOT NULL,
  attempts INTEGER DEFAULT 0, error TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


class SqliteRepo:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(DDL)

    def add_turns(self, session_id, turns: list[dict]):
        self.db.executemany(
            "INSERT OR REPLACE INTO conversation_turns VALUES (?,?,?,?)",
            [
                (
                    session_id,
                    t["turn_id"],
                    t.get("child_text", ""),
                    t.get("ai_text", ""),
                )
                for t in turns
            ],
        )
        self.db.commit()

    def get_full_session(self, session_id) -> list[Turn]:
        rows = self.db.execute(
            "SELECT turn_id, child_text, ai_text FROM conversation_turns "
            "WHERE session_id=? ORDER BY turn_id",
            (session_id,),
        ).fetchall()
        return [
            Turn(turn_id=r[0], child_text=r[1] or "", ai_text=r[2] or "") for r in rows
        ]

    def save_session_topics(self, result: SessionTopics):
        # 재분석 시 중복 저장 방지: 기존 결과 삭제 후 삽입 (멱등)
        with self.db:
            self.db.execute(
                "DELETE FROM session_topics WHERE session_id=?", (result.session_id,)
            )
            self.db.executemany(
                "INSERT INTO session_topics (session_id, schema_version, category, subtopic,"
                " topic, sentiment, key_point, turn_ids) VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        result.session_id,
                        result.schema_version,
                        t.category.value,
                        t.subtopic,
                        t.topic,
                        t.sentiment.value,
                        t.key_point,
                        json.dumps(t.turn_ids),
                    )
                    for t in result.topics
                ],
            )

    def set_job_status(self, session_id, status, attempts=None, error=None):
        self.db.execute(
            "INSERT INTO topic_analysis_jobs (session_id, status, attempts, error) VALUES (?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET status=excluded.status, "
            "attempts=COALESCE(excluded.attempts, attempts), error=excluded.error, "
            "updated_at=CURRENT_TIMESTAMP",
            (session_id, status, attempts or 0, error),
        )
        self.db.commit()

    def get_topics(self, session_id):
        rows = self.db.execute(
            "SELECT category, topic, sentiment, key_point, turn_ids FROM session_topics "
            "WHERE session_id=?",
            (session_id,),
        ).fetchall()
        return [
            dict(zip(["category", "topic", "sentiment", "key_point", "turn_ids"], r))
            for r in rows
        ]

    def get_job(self, session_id):
        r = self.db.execute(
            "SELECT status, attempts, error FROM topic_analysis_jobs "
            "WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return dict(zip(["status", "attempts", "error"], r)) if r else None
