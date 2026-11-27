"""LLM 호출 어댑터. 모델 교체(Gemini / 국내 API / 자체 서버)를 위해
analyze(turns, feedback) -> dict 인터페이스만 맞추면 된다.
feedback은 직전 시도의 검증 실패 내용이며, 재시도 때만 전달된다."""

import json
import os
from typing import Protocol

from .prompt import SYSTEM_PROMPT, build_user_prompt
from .schema import LLMTopicOutput, Turn


class QuotaExceededError(Exception):
    """API 사용 한도 초과 (예: Gemini 429). 재시도하지 않고 실행을 멈추는 신호."""


class TopicLLM(Protocol):
    def analyze(self, turns: list[Turn], feedback: str | None = None) -> dict: ...


class GeminiTopicLLM:
    """pip install google-genai / 환경변수 GEMINI_API_KEY 필요.
    모델명은 공식 문서에서 현재 이름을 확인해 GEMINI_MODEL로 지정한다."""

    def __init__(
        self,
        model: str | None = None,
        thinking_level: str | None = None,
        system_prompt: str | None = None,
    ):
        """Gemini 어댑터를 만든다.

        Args:
            model: 모델명. 없으면 환경변수 GEMINI_MODEL.
            thinking_level: "minimal"·"low"·"medium"·"high". None이면 모델 기본값.
                모델 간 공정 비교·기준 점수 측정에는 "minimal"(사실상 꺼짐)을 쓴다.
            system_prompt: 시스템 프롬프트. None이면 prompt.SYSTEM_PROMPT(현재 프롬프트).

        Raises:
            QuotaExceededError: analyze 호출 시 429(한도 초과)를 받으면.
        """
        from google import genai  # 지연 import: 다른 백엔드 쓸 때 설치 불필요

        # GEMINI_API_KEY 자동 사용. 응답이 멈춰 실행 전체가 걸리지 않도록 2분 제한(ms)
        self.client = genai.Client(http_options={"timeout": 120_000})
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.model = model or os.environ["GEMINI_MODEL"]
        self.thinking_level = thinking_level
        self.last_meta: dict = {}

    def analyze(self, turns: list[Turn], feedback: str | None = None) -> dict:
        from google.genai import errors

        try:
            resp = self._generate(turns, feedback)
        except errors.ClientError as e:
            if getattr(e, "code", None) == 429:
                raise QuotaExceededError(str(e)[:200]) from e
            raise
        u = resp.usage_metadata
        self.last_meta = (
            {  # Gemini는 기본적으로 생각(thinking)을 할 수 있어 토큰 수로 기록
                "thinking_tokens": getattr(u, "thoughts_token_count", None) or 0,
                "prompt_tokens": getattr(u, "prompt_token_count", None),
                "output_tokens": getattr(u, "candidates_token_count", None),
            }
        )
        return json.loads(resp.text)

    def _generate(self, turns: list[Turn], feedback: str | None):
        return self.client.models.generate_content(
            model=self.model,
            contents=build_user_prompt(turns, feedback),
            config={
                "system_instruction": self.system_prompt,
                "response_mime_type": "application/json",
                "response_json_schema": LLMTopicOutput.model_json_schema(),
                "temperature": 0.0,
                **(
                    {"thinking_config": {"thinking_level": self.thinking_level}}
                    if self.thinking_level
                    else {}
                ),
            },
        )


class OpenAICompatTopicLLM:
    """vLLM 등으로 띄운 자체 서버 모델(Qwen 등)이나 OpenAI 호환 국내 API용.
    pip install openai / base_url, model 지정."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "EMPTY",
        system_prompt: str | None = None,
    ):
        from openai import OpenAI

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt or SYSTEM_PROMPT

    def analyze(self, turns: list[Turn], feedback: str | None = None) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": build_user_prompt(turns, feedback)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "topics",
                    "schema": LLMTopicOutput.model_json_schema(),
                },
            },
        )
        return json.loads(resp.choices[0].message.content)


class OllamaTopicLLM:
    """로컬 Ollama 모델. `ollama serve` 실행 + `ollama pull <모델>` 필요.
    Ollama 기본 API(/api/chat)의 format에 JSON Schema를 넣어 출력 형식을 강제한다.
    think=False: Qwen 계열 등 '생각' 모드가 있는 모델이 생각 과정을 길게 출력하지 않게 한다."""

    NUM_CTX = (
        8192  # Ollama 기본 문맥 길이는 짧아서 시스템 프롬프트(규칙·예시)가 잘릴 수 있음
    )

    def __init__(
        self,
        model: str,
        host: str | None = None,
        timeout: int = 600,
        system_prompt: str | None = None,
    ):
        self.model = model
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.url = (
            host or os.getenv("OLLAMA_HOST_URL", "http://localhost:11434")
        ) + "/api/chat"
        self.timeout = timeout
        self.last_meta: dict = {}

    def analyze(self, turns: list[Turn], feedback: str | None = None) -> dict:
        import urllib.request

        body = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": LLMTopicOutput.model_json_schema(),
            "options": {"temperature": 0.0, "num_ctx": self.NUM_CTX},
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": build_user_prompt(turns, feedback)},
            ],
        }
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            resp = json.loads(r.read())
        msg = resp["message"]
        # 생각 모드가 실제로 꺼졌는지 확인용: thinking 필드가 비어 있어야 하고, 출력이 <think>로 시작하면 안 됨
        self.last_meta = {
            "thinking_chars": len(msg.get("thinking") or "")
            + (
                len(msg["content"])
                if msg["content"].lstrip().startswith("<think>")
                else 0
            ),
            "prompt_tokens": resp.get("prompt_eval_count"),
            "output_tokens": resp.get("eval_count"),
        }
        return json.loads(msg["content"])


class MockTopicLLM:
    """API 없이 파이프라인·검증 로직을 테스트할 때 사용.
    출력을 여러 개 주면 호출마다 순서대로 반환하고, 마지막 출력은 반복한다."""

    def __init__(self, *outputs: dict):
        self.outputs = list(outputs)
        self.feedbacks: list[str | None] = []  # 호출마다 받은 feedback 기록

    def analyze(self, turns: list[Turn], feedback: str | None = None) -> dict:
        self.feedbacks.append(feedback)
        return self.outputs[min(len(self.feedbacks), len(self.outputs)) - 1]
