"""감정 분류기 불변식 테스트.

"절대 깨지면 안 되는 것"만 모았다. 감정 신호는 통계용이고 대화를 게이팅하지 않으므로,
이 기능이 어떻게 실패하든 안전 판정과 응답 생성은 영향을 받아서는 안 된다.
구현체가 규칙 기반에서 학습된 분류기로 바뀌어도 이 테스트는 그대로 돌아야 한다.
"""

from __future__ import annotations

import asyncio

import pytest

from core.fakes import FakeEmotionClassifier, FakeLLM, FakeSTT, FakeTTS
from core.interfaces import (
    EmotionClassifier,
    EmotionLabel,
    EmotionResult,
    EmotionSignal,
    RiskLevel,
)
from core.orchestrator import TurnOrchestrator, drain_emotion_tasks
from emotion.signals import CONFIDENCE_THRESHOLD, to_signal
from safety.checkers import ReadabilityChecker, RuleChecker
from telemetry.logger import TurnLogger

PROFILE = {"name": "지우", "age": 8}


class ExplodingEmotionClassifier(EmotionClassifier):
    """항상 터지는 분류기. 실패가 대화에 새지 않는지 보기 위한 것."""

    name = "exploding"

    async def classify(
        self, text: str, *, context: dict | None = None
    ) -> EmotionResult:
        raise RuntimeError("분류기 폭발")


class SlowEmotionClassifier(EmotionClassifier):
    """느린 분류기. 응답 지연에 가산되지 않는지 보기 위한 것."""

    name = "slow"

    async def classify(
        self, text: str, *, context: dict | None = None
    ) -> EmotionResult:
        await asyncio.sleep(0.2)
        return EmotionResult(
            label=EmotionLabel.JOY, confidence=0.9, classifier=self.name
        )


def build(utterance: str, *, classifier=None, on_emotion=None, reply="응 그렇구나"):
    """한 턴을 실행하는 오케스트레이터를 조립한다.

    Args:
        utterance: STT 가 돌려줄 아이 발화.
        classifier: 주입할 감정 분류기. None 이면 감정 분류를 하지 않는다.
        on_emotion: 신호를 받을 콜백.
        reply: LLM 이 돌려줄 응답.

    Returns:
        조립된 TurnOrchestrator.
    """
    return TurnOrchestrator(
        stt=FakeSTT(utterance),
        llm=FakeLLM([reply]),
        tts=FakeTTS(),
        input_checkers=[RuleChecker()],
        output_checkers=[RuleChecker(), ReadabilityChecker()],
        emotion_classifier=classifier,
        on_emotion=on_emotion,
    )


async def run_turn(orch, **kwargs):
    """턴을 실행하고 감정 태스크까지 비운다.

    Args:
        orch: 실행할 오케스트레이터.
        **kwargs: run() 에 넘길 추가 인자.

    Returns:
        TurnResult.
    """
    result = await orch.run(b"<audio>", profile=PROFILE, history=[], **kwargs)
    await drain_emotion_tasks()
    return result


def test_classifier_failure_does_not_touch_safety_or_reply():
    """분류기가 터져도 안전 판정과 응답은 그대로다."""
    signals = []
    orch = build(
        "아빠가 때렸어",
        classifier=ExplodingEmotionClassifier(),
        on_emotion=signals.append,
    )
    result = asyncio.run(run_turn(orch))

    assert result.risk.level is RiskLevel.L4
    assert result.escalate is True
    assert result.reply_text
    assert signals == []  # 신호는 나오지 않지만 턴은 완주한다


def test_latency_is_not_charged_to_the_voice_turn():
    """분류가 느려도 턴 지연에 가산되지 않는다.

    감정 분류를 동기로 붙이면 아이가 기다리는 시간이 늘어난다. 비동기 가지로 두는
    이유가 이것뿐이므로, 지연 예산을 침범하지 않는지 숫자로 고정한다.
    """
    signals = []
    orch = build("오늘 진짜 재밌었어!", classifier=SlowEmotionClassifier(), on_emotion=signals.append)
    result = asyncio.run(run_turn(orch))

    # 분류기는 0.2초를 쓰지만 계측된 구간들에는 들어오지 않는다.
    assert result.total_ms < 200
    assert "emotion" not in result.timings_ms
    assert len(signals) == 1  # 그래도 신호는 도착한다


def test_empty_utterance_skips_classification():
    """STT 가 빈 문자열을 주면 분류기를 아예 부르지 않는다. (근검절약)"""
    fake = FakeEmotionClassifier()
    signals = []
    result = asyncio.run(run_turn(build("", classifier=fake, on_emotion=signals.append)))

    assert result.child_text == ""
    assert fake.calls == []
    assert signals == []


def test_without_injection_nothing_happens():
    """분류기나 콜백이 없으면 기능이 조용히 꺼진다."""
    result = asyncio.run(run_turn(build("나 오늘 좀 슬퍼")))
    assert result.reply_text
    assert result.turn_id


def test_signal_shares_the_turn_id_with_the_turn_log(tmp_path):
    """감정 신호와 턴 로그가 같은 turn_id 를 싣는다.

    둘을 상관짓는 유일한 열쇠다. 로거가 자기 값을 새로 발급하면 백엔드는 어떤 턴의
    감정인지 알 수 없게 된다.
    """
    signals = []
    orch = build("아 짜증나!", classifier=FakeEmotionClassifier(), on_emotion=signals.append)
    result = asyncio.run(run_turn(orch, child_id="anon_x"))

    logger = TurnLogger(
        str(tmp_path / "turns.jsonl"),
        str(tmp_path / "review.jsonl"),
        str(tmp_path / "emotions.jsonl"),
    )
    record = logger.log(child_id="anon_x", session_id="s", result=result)

    assert record["turn_id"] == result.turn_id
    assert signals[0].turn_id == result.turn_id
    assert signals[0].child_id == "anon_x"


def test_emotion_log_survives_the_most_severe_turn(tmp_path):
    """가장 심각한 턴에서도 감정 라벨은 로그에 남는다.

    턴 로그는 L4 에서 원문을 지우지만, 감정 레코드는 애초에 원문을 담지 않으므로
    같이 지울 이유가 없다. 2026-09-10 결정(우선 유지)을 고정한다.
    """
    logger = TurnLogger(
        str(tmp_path / "turns.jsonl"),
        str(tmp_path / "review.jsonl"),
        str(tmp_path / "emotions.jsonl"),
    )
    signal = EmotionSignal(
        label=EmotionLabel.FEAR, confidence=0.8, turn_id="t1", child_id="anon_x", ts="now"
    )
    record = logger.log_emotion(session_id="s", signal=signal)

    assert record["emotion"]["label"] == "fear"
    assert "child_text" not in record  # 원문은 애초에 담지 않는다


@pytest.mark.parametrize(
    "confidence,expected",
    [
        (None, EmotionLabel.JOY),  # 점수가 없는 규칙 기반은 깎지 않는다
        (CONFIDENCE_THRESHOLD, EmotionLabel.JOY),
        (CONFIDENCE_THRESHOLD - 0.01, EmotionLabel.NEUTRAL),
    ],
)
def test_low_confidence_falls_back_to_neutral(confidence, expected):
    """임계값 미만이면 중립으로 내린다. 애매하면 과다 해석하지 않는 쪽이다."""
    result = EmotionResult(label=EmotionLabel.JOY, confidence=confidence)
    signal = to_signal(result, turn_id="t1", child_id="anon_x")

    assert signal.label is expected
    # 깎기 전 원본 점수는 그대로 실어 나중에 임계값을 조정할 수 있게 둔다.
    assert signal.confidence == confidence
