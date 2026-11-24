"""
STT 평가 지표. SCRUM-120 실험과 같은 정의를 쓴다.

- CER(Normalized): 띄어쓰기·문장부호를 지우고 한글 소수·단위 표기를 통일한 뒤 글자 편집 거리 / 정답 글자 수
- 정확 일치: 위 정규화 후 정답과 완전히 같음
- Semantic: jhgan/ko-sroberta-multitask 임베딩 코사인 유사도.
  0.85 이상이고 부정어·숫자 차이가 없으면 MATCH, 0.70 미만이면 MISMATCH, 그 사이는 REVIEW.
"""

from __future__ import annotations

import re
import unicodedata

SEMANTIC_MODEL_NAME = "jhgan/ko-sroberta-multitask"
SEMANTIC_MATCH_THRESHOLD = 0.85
SEMANTIC_REVIEW_THRESHOLD = 0.70

KOREAN_DIGITS = {
    "영": "0",
    "공": "0",
    "일": "1",
    "이": "2",
    "삼": "3",
    "사": "4",
    "오": "5",
    "육": "6",
    "칠": "7",
    "팔": "8",
    "구": "9",
}
UNIT_REPLACEMENTS = {
    "킬로미터": "km",
    "센티미터": "cm",
    "센치미터": "cm",
    "밀리미터": "mm",
    "킬로그램": "kg",
    "밀리그램": "mg",
    "퍼센트": "%",
    "센치": "cm",
    "미터": "m",
    "그램": "g",
}
NEGATION_PATTERNS = ("안 ", "못 ", "않", "아니", "없", "싫")
_DIGITS = "영공일이삼사오육칠팔구"


def _strip(text: str) -> str:
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w가-힣]", "", text)
    return text.replace("_", "")


def normalize_basic(text: str | None) -> str:
    """띄어쓰기·문장부호만 지운다 (Raw CER 용)."""
    if text is None:
        return ""
    return _strip(unicodedata.normalize("NFKC", str(text)).lower().strip())


def _korean_decimal(match: re.Match) -> str:
    integer = "".join(KOREAN_DIGITS.get(c, c) for c in re.sub(r"\s+", "", match.group(1)))
    decimal = "".join(KOREAN_DIGITS.get(c, c) for c in re.sub(r"\s+", "", match.group(2)))
    return f"{integer}.{decimal}"


def normalize(text: str | None) -> str:
    """Normalized CER 용 정규화. 한글 소수("삼 점 오")와 단위 표기를 통일한다."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).lower().strip()
    text = re.sub(
        rf"([{_DIGITS}](?:\s*[{_DIGITS}])*)\s*점\s*([{_DIGITS}](?:\s*[{_DIGITS}])*)",
        _korean_decimal,
        text,
    )
    for source, target in sorted(
        UNIT_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        text = text.replace(source, target)
    return _strip(text)


def levenshtein(reference: str, hypothesis: str) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref_char in enumerate(reference, start=1):
        current = [i]
        for j, hyp_char in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[j - 1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (ref_char != hyp_char),
                )
            )
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> tuple[float, int, int]:
    """(CER, 편집 거리, 정답 글자 수). 둘 다 이미 정규화된 문자열을 받는다."""
    if not reference:
        return (0.0, 0, 0) if not hypothesis else (1.0, len(hypothesis), 0)
    distance = levenshtein(reference, hypothesis)
    return distance / len(reference), distance, len(reference)


def semantic_flags(reference: str, hypothesis: str) -> list[str]:
    """임베딩 점수가 높아도 의미가 뒤집힐 수 있는 차이(부정어, 숫자)."""
    flags = []
    if any(p in reference for p in NEGATION_PATTERNS) != any(
        p in hypothesis for p in NEGATION_PATTERNS
    ):
        flags.append("negation_mismatch")
    ref_numbers = set(re.findall(r"\d+(?:\.\d+)?", normalize(reference)))
    hyp_numbers = set(re.findall(r"\d+(?:\.\d+)?", normalize(hypothesis)))
    if ref_numbers != hyp_numbers and (ref_numbers or hyp_numbers):
        flags.append("number_mismatch")
    return flags


class SemanticMatcher:
    def __init__(self):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(SEMANTIC_MODEL_NAME)

    def evaluate(self, reference: str, hypothesis: str) -> tuple[float, str]:
        """(점수, MATCH/REVIEW/MISMATCH)."""
        reference, hypothesis = (reference or "").strip(), (hypothesis or "").strip()
        if not reference and not hypothesis:
            return 1.0, "MATCH"
        if not reference or not hypothesis:
            return 0.0, "MISMATCH"
        # 표기 정규화 후 같으면 임베딩 없이 일치로 본다.
        if normalize(reference) == normalize(hypothesis):
            return 1.0, "MATCH"

        emb = self.model.encode(
            [reference, hypothesis],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        score = float(emb[0] @ emb[1])
        if score >= SEMANTIC_MATCH_THRESHOLD and not semantic_flags(reference, hypothesis):
            label = "MATCH"
        elif score < SEMANTIC_REVIEW_THRESHOLD:
            label = "MISMATCH"
        else:
            label = "REVIEW"
        return round(score, 6), label
