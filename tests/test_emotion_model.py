"""학습된 감정 분류기(emotion/model.py) 테스트.

앞부분은 가짜 점수 함수로 래퍼의 동작만 본다. torch 도 가중치도 필요 없다.
뒷부분은 실제 모델을 돌리며, 가중치(models/model/model.safetensors)나 torch 가 없으면
건너뛴다. CI 에는 둘 다 없으므로 로컬에서만 돈다.
"""

from __future__ import annotations

import asyncio

import pytest

from core.interfaces import EmotionLabel
from emotion.model import CLASS_LABELS, DEFAULT_MODEL_DIR, BertEmotionClassifier
from emotion.signals import to_signal

N = EmotionLabel.NEUTRAL
P = EmotionLabel.POSITIVE
F = EmotionLabel.FEAR
U = EmotionLabel.UPSET
S = EmotionLabel.SHAME
O = EmotionLabel.NEGATIVE_OTHER


def classify(score, text="아무 말"):
    return asyncio.run(BertEmotionClassifier(score).classify(text))


# ---------------------------------------------------------------- 래퍼 (가짜 점수)


@pytest.mark.parametrize("index,expected", list(enumerate([N, P, F, U, S, O])))
def test_class_order_maps_to_labels(index, expected):
    """C0~C5 순서가 라벨과 어긋나면 예외 없이 라벨만 뒤바뀐다. 순서를 고정한다."""
    scores = [0.0] * 6
    scores[index] = 1.0

    result = classify(lambda text: scores)

    assert result.label is expected
    assert result.confidence == 1.0
    assert result.classifier == BertEmotionClassifier.name


def test_every_label_is_reachable():
    assert set(CLASS_LABELS) == set(EmotionLabel)


def test_unreadable_text_is_neutral_without_score():
    """빈 문자열·기호뿐인 발화에 전처리가 ValueError 를 낸다. 턴을 깨지 않고 중립을 준다."""

    def score(text):
        raise ValueError("empty_text")

    result = classify(score, "!!!")

    assert result.label is N
    assert result.confidence is None


def test_classifier_returns_raw_label_and_signal_applies_threshold():
    """분류기는 본 대로 돌려주고, 임계값 미만을 중립으로 내리는 것은 to_signal 이다."""
    result = classify(lambda text: [0.2, 0.0, 0.0, 0.0, 0.0, 0.8])

    assert result.label is O
    assert to_signal(result, turn_id=None, child_id="").label is N


def test_load_reports_missing_weights(tmp_path):
    with pytest.raises(FileNotFoundError, match="model.safetensors"):
        BertEmotionClassifier.load(tmp_path)


# ---------------------------------------------------------------- 실제 모델

# 라벨링 매뉴얼 v0.3 의 4절(범주별 정의)·5절(경계 규칙) 예시에서 뽑았다.
# 학습 시트에 있던 문장이라 일반화 성능의 근거는 아니다. 모델 파일이 바뀌었거나
# 로딩·전처리·라벨 순서가 틀어졌을 때 알아채기 위한 회귀 표다.
MANUAL_CASES = [
    ("내일 시골 가요 신나요", P),
    ("찾아서 다행이다", P),
    ("엄마 해냈어", P),
    ("영화 재미있었어", P),  # R7 특정 경험에 대한 느낌. 과거형도 라벨을 준다
    ("저는 아이스크림을 제일 좋아해요", N),  # R7 평소의 선호
    ("혼날까봐 걱정돼요", F),
    ("지진이 나면 어떡해", F),  # R1
    ("야 그렇게 멀리 던지면 어떡해", N),  # R1 상대를 탓하는 말
    ("너도 귀신 무서워", N),  # 질문
    ("하나도 안 무서워 겁 안나", N),  # 감정 부정
    ("수민이가 이사가서 서운해요", U),  # E05 슬픔
    ("동생이 과자를 다 먹었어요 엄청 화나요", U),  # E06 화. 슬픔과 같은 범주다
    ("나 빼고 놀아서 싫어", U),  # E07 소외감
    ("누나는 나랑 잘 안 놀아줘", U),  # R3 감정 단어 없는 간접 표현
    ("엄마가 속상해할 것 같아", N),  # 타인의 감정
    ("코가 막혀서 답답해", N),  # 신체 감각
    ("거짓말해서 미안해", S),
    ("죄송합니다", S),  # R2 인사말뿐인 사과
    ("미안하다고 해 빨리", N),  # R2 사과 요구
    ("지금 기분 별로예요", O),
    ("숙제가 너무 많아서 힘들어요", O),  # R9
    ("저는 급식이 싫어요", N),  # R11
    ("천둥소리 때문에 깜짝 놀랐어", N),  # 놀람은 체계 밖
    ("비행기 처음 타보는 거라 엄청 신났는데 금방 도착해서 아쉬웠어", U),  # 복수 감정은 결론
]


@pytest.fixture(scope="module")
def model():
    if not (DEFAULT_MODEL_DIR / "model.safetensors").is_file():
        pytest.skip("감정 모델 가중치가 없다 (models/README.md)")
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    return BertEmotionClassifier.load(DEFAULT_MODEL_DIR)


@pytest.mark.parametrize("text,expected", MANUAL_CASES, ids=[c[0] for c in MANUAL_CASES])
def test_manual_examples(model, text, expected):
    result = asyncio.run(model.classify(text))

    assert to_signal(result, turn_id=None, child_id="").label is expected


def test_real_model_handles_unreadable_text(model):
    assert asyncio.run(model.classify("")).label is N
    assert asyncio.run(model.classify("!!!")).label is N
