"""세션 종료 후 1건 처리: 조회 → LLM → 검증 → (실패 시 재시도) → 저장.
repo는 백엔드 DB 접근 객체. 실제 테이블명은 백엔드 계약을 따른다."""

import json
import logging
import time

from .llm_client import QuotaExceededError, TopicLLM
from .schema import SessionTopics
from .validator import (
    PersonNameError,
    TopicValidationError,
    mask_person_names,
    validate,
)

log = logging.getLogger("topic_analysis")
MAX_ATTEMPTS = 3  # 최초 1회 + 재시도 2회


def process_session_topic(session_id: str, llm: TopicLLM, repo) -> SessionTopics | None:
    repo.set_job_status(session_id, "running", attempts=0)
    turns = repo.get_full_session(session_id)
    if not turns:
        repo.set_job_status(session_id, "failed", error="empty session")
        return None

    last_error = ""
    last_raw = None
    name_only_failures = 0  # 이름 때문에만 실패한 시도 수
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
            last_raw = raw
            name_only_failures += isinstance(e, PersonNameError)
            feedback = (
                f"이전 출력:\n{json.dumps(raw, ensure_ascii=False)}\n" f"거부 사유: {e}"
            )
        except QuotaExceededError:  # 한도 초과는 재시도하지 않고 호출자에게 넘긴다
            repo.set_job_status(
                session_id, "quota", attempts=attempt, error="quota exceeded"
            )
            raise
        # JSON 파싱 실패·네트워크 등은 재시도 대상
        except Exception as e:  # noqa: BLE001
            last_error = f"{type(e).__name__}: {e}"
        log.warning("session=%s attempt=%d failed: %s", session_id, attempt, last_error)
        repo.set_job_status(session_id, "retrying", attempts=attempt, error=last_error)
        time.sleep(2**attempt)  # 간단한 백오프

    # 모든 시도가 사람 이름 때문에만 실패했으면 이름을 가려서 저장한다 (개인정보 보호 + 세션 유실 방지)
    if name_only_failures == MAX_ATTEMPTS and last_raw is not None:
        try:
            checked = validate(mask_person_names(last_raw, turns), turns)
        except TopicValidationError as e:
            last_error = f"validation after masking: {e}"
        else:
            result = SessionTopics(session_id=session_id, topics=checked.topics)
            repo.save_session_topics(result)
            repo.set_job_status(
                session_id,
                "done",
                attempts=MAX_ATTEMPTS,
                error="person names masked",
            )
            log.warning("session=%s saved after masking person names", session_id)
            return result

    repo.set_job_status(session_id, "failed", attempts=MAX_ATTEMPTS, error=last_error)
    return None  # 실패를 성공으로 저장하지 않음
