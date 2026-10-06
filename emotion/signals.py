"""
감정 신호 조립. 분류 결과를 집계하는 쪽(백엔드)에 넘길 계약 객체로 바꾼다.

신뢰도 필터링이 여기 있는 이유는 "무엇을 분류했는가"(EmotionResult)와 "무엇을
신호로 내보낼 것인가"(EmotionSignal)가 다른 질문이기 때문이다. 분류기는 자기가 본
대로 돌려주고, 보수적으로 깎는 책임은 조립 단계가 진다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.interfaces import EmotionLabel, EmotionResult, EmotionSignal

# 이 값 미만의 신뢰도는 라벨을 내지 않고 중립으로 내린다.
# 규칙 기반 구현체는 점수가 없어(None) 실제 발동은 학습된 분류기부터다.
# 숫자에 근거는 아직 없다 — capstone_documents/emotion-labels.md 의 "임계값 미확정" 참고.
CONFIDENCE_THRESHOLD = 0.5


def to_signal(
    result: EmotionResult, *, turn_id: str | None, child_id: str
) -> EmotionSignal:
    """분류 결과에 신뢰도 필터를 적용해 신호를 만든다.

    안전 판정은 "애매하면 높은 쪽"이지만 감정 통계는 반대다. 오분류된 감정이 그대로
    보호자에게 노출되는 쪽이 더 큰 손해이므로 애매하면 중립으로 내린다.

    Args:
        result: 분류기가 돌려준 원본 판정.
        turn_id: 이 발화가 속한 턴 식별자.
        child_id: 익명화된 아이 식별자.

    Returns:
        집계 쪽에 넘길 EmotionSignal.
    """
    label = result.label
    if result.confidence is not None and result.confidence < CONFIDENCE_THRESHOLD:
        label = EmotionLabel.NEUTRAL

    return EmotionSignal(
        label=label,
        # 깎기 전의 원본 점수를 싣는다. 임계값을 나중에 조정할 때 재계산할 수 있어야 한다.
        confidence=result.confidence,
        turn_id=turn_id,
        child_id=child_id,
        ts=datetime.now(timezone.utc).isoformat(),
    )
