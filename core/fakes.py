"""
API 키 없이 파이프라인 로직을 검증하기 위한 가짜 구현체.
테스트에서 이 fake 들을 쓰면 안전 필터 회귀 테스트를 비용 0으로 돌릴 수 있음.
"""

from __future__ import annotations

from core.interfaces import (
    EmotionClassifier,
    EmotionLabel,
    EmotionResult,
    LLMEngine,
    LLMResult,
    STTEngine,
    STTResult,
    TTSEngine,
)


class FakeSTT(STTEngine):
    name = "fake_stt"

    def __init__(self, text: str):
        self.text = text

    async def transcribe(self, audio: bytes, *, sample_rate: int = 16000) -> STTResult:
        return STTResult(text=self.text, confidence=0.9, engine=self.name)


class FakeLLM(LLMEngine):
    name = "fake_llm"

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls = 0

    async def generate(self, **kwargs) -> LLMResult:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return LLMResult(
            text=reply, input_tokens=1800, output_tokens=40, model=self.name
        )


class FakeTTS(TTSEngine):
    name = "fake_tts"

    async def synthesize(self, text: str, *, voice: str) -> bytes:
        return text.encode("utf-8")


class FakeEmotionClassifier(EmotionClassifier):
    name = "fake_emotion"

    def __init__(
        self,
        label: EmotionLabel = EmotionLabel.NEUTRAL,
        confidence: float | None = 0.9,
    ):
        self.label = label
        self.confidence = confidence
        # 호출 여부 자체가 검증 대상이다. 빈 발화에서는 불려서는 안 된다.
        self.calls: list[str] = []

    async def classify(
        self, text: str, *, context: dict | None = None
    ) -> EmotionResult:
        self.calls.append(text)
        return EmotionResult(
            label=self.label, confidence=self.confidence, classifier=self.name
        )
