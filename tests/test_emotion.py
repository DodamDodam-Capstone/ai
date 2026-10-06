"""감정 라벨링 회귀 테스트.

capstone_documents/emotion-labels.md 의 종합 예시 표를 그대로 옮긴 것이다. 문서가 사양이고
이 파일이 그 사양의 실행 가능한 사본이다. 둘 중 하나만 고치면 안 된다.

학습된 분류기로 교체할 때 이 표가 기준선이 된다.
"""

from __future__ import annotations

import asyncio

import pytest

from core.interfaces import EmotionLabel
from emotion.checkers import RuleEmotionClassifier

N = EmotionLabel.NEUTRAL
J = EmotionLabel.JOY
S = EmotionLabel.SADNESS
A = EmotionLabel.ANGER
F = EmotionLabel.FEAR


def label(text: str) -> EmotionLabel:
    """아이 발화 하나에 감정 라벨을 매긴다.

    Args:
        text: 아이 발화.

    Returns:
        매겨진 감정 라벨.
    """
    return asyncio.run(RuleEmotionClassifier().classify(text)).label


# (발화, 기대 라벨)
SPEC_CASES = [
    ("공룡 좋아!", N),
    ("오늘 학교 갔다 왔어", N),
    ("이거 뭐야?", N),
    ("오늘 진짜 재밌었어!", J),
    ("나 오늘 시험 잘 봤어!", J),
    ("시험 봤어", N),
    ("우와!", J),
    ("나 오늘 좀 슬퍼", S),
    ("친구가 안 놀아줘서 속상해", S),
    ("어제 슬펐어", N),
    ("어제 슬펐는데 아직 속상해", S),
    ("울었어", N),
    ("울고 싶어", S),
    ("외로워", S),
    ("아무도 없어", N),
    ("아 짜증나!", A),
    ("동생이 내 준비물 망가뜨렸어, 미워!", A),
    ("동생이 준비물 망가뜨렸어", N),
    ("나만 혼났어, 억울해", A),
    ("아 몰라", N),
    ("무서운 꿈 꿨어", F),
    ("내일 시험 생각하니까 떨려", F),
    ("귀신 무서워", F),
    ("동생이 울었어", N),
    ("공룡이 무서워했어", N),
    ("슬프면 어떻게 해?", N),
    ("시험 떨리는데 좀 기대돼", J),
    ("죽고 싶어", S),
]


@pytest.mark.parametrize("text,expected", SPEC_CASES, ids=[c[0] for c in SPEC_CASES])
def test_emotion_table(text, expected):
    """emotion-labels.md 종합 예시 표의 각 행이 그대로 재현되는지 확인."""
    assert label(text) is expected


def test_neutral_is_the_default():
    """표지가 없으면 중립이다. 모든 발화를 감정에 욱여넣으면 통계가 무의미해진다."""
    assert label("") is N
    assert label("음...") is N
    assert label("도담아 안녕") is N


def test_past_report_is_neutral_but_not_by_tense_alone():
    """시점 판정은 문법적 과거형이 아니라 감정의 귀속 시점으로 가른다.

    안전 계층의 ongoing 은 시제 어미로 판정하지만, 감정 라벨은 "그날의 감정 통계에
    넣을 것인가"를 본다. 과거형이어도 감탄 표지가 있으면 지금의 감정으로 본다.
    """
    assert label("어제 슬펐어") is N
    assert label("어제 진짜 슬펐어") is S  # 감탄 표지
    assert label("어제 슬펐는데 아직 속상해") is S  # 잔존 표지


def test_stem_with_sseot_batchim_is_not_past():
    """'재밌'처럼 어간에 ㅆ 받침이 든 표지를 과거형으로 오인하지 않는다.

    받침만으로 가르면 "오늘 재밌어" 가 지난 감정의 보고로 처리돼 중립이 된다.
    """
    assert label("오늘 재밌어") is J
    assert label("오늘 재밌었어") is N  # 이쪽이 진짜 과거형


def test_dominant_emotion_is_the_last_marker():
    """혼합 감정은 주절 기준이고, 한국어 주절은 뒤에 온다."""
    assert label("시험 떨리는데 좀 기대돼") is J
    assert label("기대되는데 떨려") is F


def test_vulnerable_utterances_map_to_sadness():
    """외로움·무기력은 슬픔으로 매긴다.

    emotion-labels.md 가 배제한 것은 '무기력/위축'이라는 별도 라벨이고, 그런 발화를
    라벨링에서 빼라는 뜻이 아니다. 안전 계층이 같은 발화를 L2 로 잡는 것과 충돌하지
    않는다 — 라벨 공간이 서로 다르다.
    """
    assert label("외로워") is S
    assert label("아무것도 하기 싫어") is S


def test_known_gap_fictional_third_party_passes_by_tense():
    """알려진 한계를 현재 동작 그대로 고정한다.

    "공룡이 무서워했어" 는 허구 속 제3자의 감정이라 중립이어야 하는데, 규칙은 3인칭
    귀속('-어했')을 보지 못하고 과거 표지 덕에 우연히 중립에 도달한다. 같은 구조의
    현재형("공룡이 무서워해")은 두려움으로 잘못 매긴다.

    이 테스트가 실패하면 3인칭 귀속을 실제로 보게 된 것이다. emotion-labels.md 와
    함께 갱신할 것.
    """
    assert label("공룡이 무서워했어") is N
    assert label("공룡이 무서워해") is F  # 오탐


def test_known_false_positive_attributive_emotion_word():
    """알려진 오탐을 현재 동작 그대로 고정한다.

    emotion-labels.md 는 "무서운 영화가 뭐야?" 를 중립으로 적어뒀지만, 규칙은 관형형
    '무서운'을 발화 시점의 감정으로 보기 때문에 두려움으로 잡는다. 관형형을 전부
    제외하면 표의 "무서운 꿈 꿨어"(두려움)가 통째로 빠지므로 오탐을 남겨뒀다.

    이 테스트가 실패하면 수식 대상이 자기 감정인지 보게 된 것이다. emotion-labels.md
    와 함께 갱신할 것.
    """
    assert label("무서운 영화가 뭐야?") is F
