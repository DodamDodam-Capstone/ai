"""
감정 분류 계층. 아이 발화에 지배 감정 하나를 매긴다.

라벨 정의·경계·종합 예시는 capstone_documents/emotion-labels.md 가 사양이다.
안전 계층과 완전히 분리된 시스템이며, 어떤 경우에도 대화를 게이팅하지 않는다.

규칙 기반으로 먼저 굴리는 이유는 안전 계층과 같다. 라벨링 전에도 신호를 뽑을 수 있고,
이 규칙이 매긴 라벨이 사람이 검토·수정할 가라벨이 되어 그대로 학습 데이터가 된다.
학습된 분류기로 교체한 뒤에도 이 규칙은 앙상블로 남겨둘 것.
"""

from __future__ import annotations

import re
import time

from core.interfaces import EmotionClassifier, EmotionLabel, EmotionResult

# 감정이 발화 시점까지 남아있다는 표지. 과거 시제를 이긴다.
_PERSIST = re.compile(r"(아직|계속|지금도|여전히)")
# 감탄·강조 표지. 지난 사건을 말하면서도 지금의 감정을 담고 있다는 근거로 본다.
_EMPHASIS = re.compile(r"(!|진짜|너무|완전|정말|엄청)")
# 명시적 과거 표지. 축약형(펐/났/했)은 종성 ㅆ 으로 따로 잡는다.
_PAST = re.compile(r"(었|았|였)|어제|아까|저번|지난")
# 과거형으로 축약된 감정 표지. 어간에 ㅆ 받침이 든 표지('재밌')와 구별해야 한다.
_PAST_FORM = re.compile(r"(슬펐|신났|화났|잘\s*봤)")
# 관형형 어미. 감정어가 명사를 수식하는 자리이므로 절의 시제는 다른 용언의 것이다.
# "무서운 꿈 꿨어" 의 과거는 '꿨'에 걸리고 '무서운'은 발화 시점의 감정이다.
_ADNOMINAL = re.compile(r"^(운|은|는)")
# 조건절. "슬프면 어떻게 해?" 는 자기 감정 서술이 아니다.
_CONDITIONAL = re.compile(r"^면")
_CLAUSE_SPLIT = re.compile(r"[,.!?~\n]|는데|지만")

# 라벨별 감정 표지. 사건 서술이 아니라 감정이 실린 표현만 넣는다.
# "공룡 좋아"(선호 서술), "울었어"(사건 서술) 가 걸리면 오탐이다.
MARKERS: tuple[tuple[EmotionLabel, re.Pattern[str]], ...] = (
    (
        EmotionLabel.JOY,
        re.compile(
            r"(재밌|재미있|신나|신났|기뻐|기쁘|기대|행복|뿌듯|최고|우와|드디어|잘\s*봐|잘\s*봤|즐거)"
        ),
    ),
    (
        EmotionLabel.SADNESS,
        re.compile(
            # '서운'은 '무서운'에 통째로 들어있다. 어미를 붙여 끊는다.
            r"(슬퍼|슬프|슬펐|속상|서운[하해했]|실망|우울|외로|울고\s*싶|죽고\s*싶|아무것도\s*하기\s*싫)"
        ),
    ),
    # '분해'는 "로봇 분해했어" 쪽이 아이 발화에서 더 흔하므로 넣지 않는다.
    (EmotionLabel.ANGER, re.compile(r"(짜증|화나|화났|미워|밉|억울|열받)")),
    (
        EmotionLabel.FEAR,
        re.compile(r"(무서|무섭|겁나|걱정|긴장|떨려|떨린|불안)"),
    ),
)


def _has_past_marker(text: str) -> bool:
    """과거 시제 표지가 있는지 본다.

    '-었/았' 은 '꿨어', '혼났어' 처럼 앞 음절의 ㅆ 받침으로 축약되는 경우가 많아
    문자열 매칭만으로는 절반을 놓친다. 종성이 ㅆ 인 음절을 직접 확인한다.

    Args:
        text: 검사할 문장.

    Returns:
        과거 표지가 있으면 True.
    """
    if _PAST.search(text):
        return True
    for ch in text:
        # '있어' 는 과거가 아니라 존재 표현이므로 제외한다.
        if ch == "있" or not ("가" <= ch <= "힣"):
            continue
        if (ord(ch) - 0xAC00) % 28 == 20:  # 종성 ㅆ
            return True
    return False


def _clause_of(text: str, start: int, end: int) -> str:
    """감정 표지가 놓인 절만 잘라낸다.

    시제를 문장 전체로 보면 "나만 혼났어, 억울해" 가 과거로 묶여 중립이 된다.
    감정이 실린 절의 시제만 봐야 한다.

    Args:
        text: 발화 전문.
        start: 감정 표지가 시작된 위치.
        end: 감정 표지가 끝난 위치.

    Returns:
        해당 표지를 포함하는 절.
    """
    lo, hi = 0, len(text)
    for m in _CLAUSE_SPLIT.finditer(text):
        if m.end() <= start:
            lo = m.end()
        elif m.start() >= end:
            hi = m.start()
            break
    return text[lo:hi]


def _is_past_report(text: str, match: re.Match[str]) -> bool:
    """지난 감정을 사실로 보고하는 발화인지 본다.

    emotion-labels.md 의 시점 판정을 그대로 옮긴다. 문법적 과거형만으로 판단하지
    않는다는 점이 안전 계층의 ongoing 과 다르다.

    Args:
        text: 발화 전문.
        match: 걸린 감정 표지.

    Returns:
        지난 감정의 보고로 보이면 True.
    """
    tail = text[match.end() : match.end() + 4]
    if _ADNOMINAL.match(tail):
        return False
    clause = _clause_of(text, match.start(), match.end())
    if _PERSIST.search(clause):
        return False
    # 표지를 뺀 나머지로 절의 시제를 본다. 표지 자신의 ㅆ 받침은 과거형('슬펐')일 수도
    # 어간('재밌')일 수도 있어 받침만으로는 가를 수 없으므로 과거형을 열거한다.
    rest = clause.replace(match.group(0), " ", 1)
    return bool(_has_past_marker(rest) or _PAST_FORM.match(match.group(0)))


class RuleEmotionClassifier(EmotionClassifier):
    """감정 분류기의 부트스트랩 버전.

    정규식 수준이라 비유 표현이나 복잡한 문장은 놓친다. 놓치는 쪽이 틀리게 매기는
    쪽보다 안전하다 — emotion-labels.md 의 "애매하면 중립" 원칙 그대로다.
    """

    name = "rule_emotion_v1"

    async def classify(
        self, text: str, *, context: dict | None = None
    ) -> EmotionResult:
        """발화에서 감정 표지를 찾아 라벨 하나를 매긴다.

        Args:
            text: 아이 발화(STT 결과).
            context: 인터페이스 통일용 부가 정보. 이 구현체에서는 사용하지 않는다.

        Returns:
            판정 결과를 담은 EmotionResult. 표지가 없으면 중립.
        """
        t0 = time.perf_counter()
        label, matched = self._label(text)
        return EmotionResult(
            label=label,
            classifier=self.name,
            matched_text=matched,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    def _label(self, text: str) -> tuple[EmotionLabel, str | None]:
        """감정 표지를 모아 지배 감정 하나를 고른다.

        여러 감정이 함께 실리면 마지막에 나온 표지를 택한다. 한국어는 주절이 뒤에
        오므로 "시험 떨리는데 좀 기대돼" 의 지배 감정은 기쁨이다.

        Args:
            text: 아이 발화.

        Returns:
            (라벨, 근거가 된 표지) 튜플. 표지가 없으면 (중립, None).
        """
        found: list[tuple[int, EmotionLabel, re.Match[str]]] = []
        for label, pattern in MARKERS:
            for m in pattern.finditer(text):
                # 조건절 안의 감정 어휘는 자기 감정이 아니다.
                if _CONDITIONAL.match(text[m.end() : m.end() + 4]):
                    continue
                found.append((m.start(), label, m))

        if not found:
            return EmotionLabel.NEUTRAL, None

        _, label, match = max(found, key=lambda f: f[0])
        if _is_past_report(text, match) and not _EMPHASIS.search(text):
            return EmotionLabel.NEUTRAL, match.group(0)
        return label, match.group(0)
