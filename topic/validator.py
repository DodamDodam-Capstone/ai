"""LLM 결과 검증. 형식(Schema/Enum)은 Pydantic, 근거·개인정보는 규칙 기반.
의미 일치·환각은 이 단계로 완전히 못 잡으므로 평가(eval.py)에서 사람 검토 병행."""

import json
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

# 사람 이름 후보: 아이 발화에서 "민준이가", "지우랑", "지우는 내 친구" 같은 꼴로 쓰인 두 글자 이름.
# 형태소 분석 없이 잡는 규칙이라 완전하지 않다. 출력(topic·key_point)에 그 이름이 나올 때만 거부한다.
_NAME_PATTERNS = [
    re.compile(
        r"(?<![가-힣])([가-힣]{2})이(?:가|랑|는|한테|하고|도|를|의|와|만|에게)"
    ),  # 민준이가, 서준이랑
    re.compile(r"(?<![가-힣])([가-힣]{2})(?:랑|한테|하고)(?![가-힣])"),  # 지우랑
    re.compile(
        r"(?<![가-힣])([가-힣]{2})(?:이)?(?:는|가) (?:내|우리) [^.!?]{0,10}"
        r"(?:친구|짝꿍|동생|형|누나|언니|오빠)"
    ),  # 지우는 내 제일 친한 친구야
]
# 이름이 아닌 호칭·일반 명사 (위 패턴에 걸리지만 사람 이름이 아님)
_NOT_NAMES = {
    "엄마", "아빠", "친구", "짝꿍", "동생", "형이", "누나", "언니", "오빠", "형아",
    "이모", "삼촌", "고모", "사촌", "아기", "애들", "우리", "너희", "가족", "사람",
    "반장", "선생", "할머", "할아", "고양", "원숭", "호랑", "거북", "달팽", "어린",
}  # fmt: skip
# 반려동물 이름은 사람 이름이 아니므로 허용한다: 같은 발화에 동물 단어가 함께 나온 이름
_ANIMAL_WORDS = re.compile(
    r"강아지|고양이|햄스터|금붕어|물고기|토끼|거북이|앵무새|고슴도치|반려|"
    r"(?<![가-힣])개(?![가-힣])|(?<![가-힣])새(?![가-힣])"
)


def person_names(turns: list[Turn]) -> set[str]:
    """아이 발화에서 사람 이름으로 보이는 단어를 찾는다 (반려동물 이름·호칭 제외).

    Args:
        turns: 세션의 전체 턴.

    Returns:
        사람 이름 후보 집합 (예: {"지우", "민준"}).
    """
    candidates = set()
    for t in turns:
        for pattern in _NAME_PATTERNS:
            candidates |= set(pattern.findall(t.child_text))
    candidates -= _NOT_NAMES
    texts = [t.child_text for t in turns] + [t.ai_text for t in turns]
    pets = {
        name
        for name in candidates
        for text in texts
        for sentence in re.split(r"[.!?]", text)
        if _ANIMAL_WORDS.search(sentence)
        and re.search(rf"(?<![가-힣]){name}", sentence)
    }
    return candidates - pets


def mask_person_names(raw: dict, turns: list[Turn], replacement: str = "친구") -> dict:
    """출력의 topic·key_point에 들어간 사람 이름을 관계 표현으로 바꾼다.

    재시도를 모두 이름 때문에만 실패했을 때 쓰는 마지막 수단이다. 이름의 주인이 친구가 아닐 수도
    있지만, 개인정보를 남기는 것보다 낫다고 보고 일괄로 replacement를 쓴다.

    Args:
        raw: LLM 출력 (validate 입력과 같은 형식).
        turns: 세션의 전체 턴.
        replacement: 이름 대신 넣을 말.

    Returns:
        이름을 바꾼 출력 사본.
    """
    names = person_names(turns)
    out = json.loads(json.dumps(raw, ensure_ascii=False))
    for item in out.get("topics", []):
        for field in ("topic", "key_point"):
            text = item.get(field)
            if not isinstance(text, str):
                continue
            for name in names:  # "민준이가" → "친구가", "지우와" → "친구와"
                text = re.sub(
                    rf"(?<![가-힣]){name}(?:이(?=[가는랑를도의와한하에만]))?",
                    replacement,
                    text,
                )
            item[field] = text
    return out


class TopicValidationError(Exception):
    pass


class PersonNameError(TopicValidationError):
    """출력에 사람 이름이 들어간 경우 (이름 가리기 대상)."""


def _norm(text: str) -> str:
    return re.sub(r"[\s.!?~,]", "", text)


def validate(raw: dict, turns: list[Turn]) -> LLMTopicOutput:
    # 1) Schema · 필수 필드 · Category/Sentiment Enum · turn_ids 비어있지 않음
    try:
        out = LLMTopicOutput.model_validate(raw)
    except ValidationError as e:
        raise TopicValidationError(f"schema: {e.errors()[:3]}")

    child = {t.turn_id: t.child_text.strip() for t in turns}
    names = person_names(turns)

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
            for name in names:
                if re.search(rf"(?<![가-힣]){name}", field):
                    raise PersonNameError(
                        f"topic[{i}] contains person name '{name}': "
                        "이름 대신 관계(친구, 동생 등)로 쓴다"
                    )

    return out
