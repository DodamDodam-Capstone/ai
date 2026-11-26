"""세션 종료 후 1건 처리: 조회 → LLM → 검증 → (실패 시 재시도) → 저장.
repo는 백엔드 DB 접근 객체. 실제 테이블명은 백엔드 계약을 따른다."""

import json
import logging
import time

from .llm_client import TopicLLM
from .schema import SessionTopics
from .validator import TopicValidationError, validate

log = logging.getLogger("topic_analysis")
MAX_ATTEMPTS = 3  # 최초 1회 + 재시도 2회


def process_session_topic(session_id: str, llm: TopicLLM, repo) -> SessionTopics | None:
    repo.set_job_status(session_id, "running", attempts=0)
    turns = repo.get_full_session(session_id)
    if not turns:
        repo.set_job_status(session_id, "failed", error="empty session")
        return None

    last_error = ""
    feedback = None  # 검증 실패 내용 → 다음 시도 프롬프트에 포함
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.time()
        raw = None
        try:
            raw = llm.analyze(turns, feedback)  # LLM 1회 호출
            checked = validate(raw, turns)  # 형식·근거·개인정보 검사
            result = SessionTopics(session_id=session_id, topics=checked.topics)
            repo.save_session_topics(result)  # C.1
            repo.set_job_status(session_id, "done", attempts=attempt)
            log.info(
                "session=%s ok attempt=%d %.1fs",
                session_id,
                attempt,
                time.time() - started,
            )
            return result
        except TopicValidationError as e:  # LLM 출력 문제 → 사유를 알려주고 재시도
            last_error = f"validation: {e}"
            feedback = (
                f"이전 출력:\n{json.dumps(raw, ensure_ascii=False)}\n" f"거부 사유: {e}"
            )
        # JSON 파싱 실패·네트워크·쿼터 등 모두 재시도 대상
        except Exception as e:  # noqa: BLE001
            last_error = f"{type(e).__name__}: {e}"
        log.warning("session=%s attempt=%d failed: %s", session_id, attempt, last_error)
        repo.set_job_status(session_id, "retrying", attempts=attempt, error=last_error)
        time.sleep(2**attempt)  # 간단한 백오프

    repo.set_job_status(session_id, "failed", attempts=MAX_ATTEMPTS, error=last_error)
    return None  # 실패를 성공으로 저장하지 않음
