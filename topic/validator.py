"""LLM 결과 검증. 형식(Schema/Enum)은 Pydantic, 근거·개인정보는 규칙 기반.
의미 일치·환각은 이 단계로 완전히 못 잡으므로 평가(eval.py)에서 사람 검토 병행."""

import re

from pydantic import ValidationError

from .schema import LLMTopicOutput, Turn

SHORT_AGREEMENTS = {"응", "어", "네", "예", "맞아", "그래", "웅", "엉", "좋아"}
# 간단한 개인정보 패턴 (필요 시 팀에서 확장)
PII_PATTERNS = [
    re.compile(r"\d{2,3}-\d{3,4}-\d{4}"),  # 전화번호
    re.compile(r"[가-힣]+(초등학교|유치원|어린이집)"),  # 기관명
    re.compile(r"[가-힣]+(동|로|길)\s?\d+"),  # 주소
]


class TopicValidationError(Exception):
    pass


def _norm(text: str) -> str:
    return re.sub(r"[\s.!?~,]", "", text)


def validate(raw: dict, turns: list[Turn]) -> LLMTopicOutput:
    # 1) Schema · 필수 필드 · Category/Sentiment Enum · turn_ids 비어있지 않음
    try:
        out = LLMTopicOutput.model_validate(raw)
    except ValidationError as e:
        raise TopicValidationError(f"schema: {e.errors()[:3]}")

    child = {t.turn_id: t.child_text.strip() for t in turns}

    for i, item in enumerate(out.topics):
        if item.subtopic is not None:
            raise TopicValidationError(f"topic[{i}] subtopic must be null")

        # 2) 존재하는 Turn ID + 아동 발화가 있는 턴만 근거로 인정
        for tid in item.turn_ids:
            if tid not in child:
                raise TopicValidationError(f"topic[{i}] unknown turn_id {tid}")
            if not child[tid]:
                raise TopicValidationError(
                    f"topic[{i}] turn {tid} has no child utterance"
                )

        # 3) 짧은 동의만으로 positive 단정 금지
        if item.sentiment.value == "positive" and all(
            _norm(child[t]) in SHORT_AGREEMENTS for t in item.turn_ids
        ):
            raise TopicValidationError(f"topic[{i}] positive from short agreement only")

        # 4) 개인정보
        for field in (item.topic, item.key_point):
            if any(p.search(field) for p in PII_PATTERNS):
                raise TopicValidationError(f"topic[{i}] possible PII")

    return out
