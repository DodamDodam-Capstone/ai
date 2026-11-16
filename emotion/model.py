"""
학습된 감정 분류기. klue/bert-base 를 라벨링 매뉴얼 v0.3 의 6범주로 미세조정한 model1 이다.

가중치(model.safetensors, 약 440MB)는 저장소에 없다. 받는 방법은 models/README.md 참고.
나머지 모델 파일(config, 토크나이저, 메타데이터, 전처리)은 models/model/ 에 들어 있다.

torch 와 transformers 는 load() 안에서만 import 한다. 이 모듈을 import 하는 것만으로는
무거운 의존성이 필요하지 않아야 CI(requirements.txt 만 설치)에서 테스트가 돈다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from core.interfaces import EmotionClassifier, EmotionLabel, EmotionResult

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "model"
SCHEMA_VERSION = "model1-v0.3"
REQUIRED_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "emotion_metadata.json",
    "preprocessing.py",
)

# 모델 출력 순서(C0~C5)와 EmotionLabel 의 대응. 순서가 곧 logits 인덱스다.
CLASS_LABELS: tuple[EmotionLabel, ...] = (
    EmotionLabel.NEUTRAL,  # C0 감정 없음
    EmotionLabel.POSITIVE,  # C1 긍정
    EmotionLabel.FEAR,  # C2 걱정·두려움
    EmotionLabel.UPSET,  # C3 속상함
    EmotionLabel.SHAME,  # C4 부끄러움·미안함
    EmotionLabel.NEGATIVE_OTHER,  # C5 부정 기타
)


class BertEmotionClassifier(EmotionClassifier):
    """학습된 모델로 감정 라벨을 매기는 분류기.

    점수가 낮은 판정을 중립으로 내리는 일은 여기서 하지 않는다. 본 대로 돌려주고,
    깎는 책임은 emotion/signals.py 의 to_signal 이 진다.
    """

    name = "bert_emotion_model1_v0.3"

    def __init__(self, score: Callable[[str], list[float]]):
        """
        Args:
            score: 발화를 받아 C0~C5 순서의 점수 6개를 돌려주는 함수. 모델이 읽을 수 없는
                발화(빈 문자열, 기호뿐인 발화)에는 ValueError 를 낸다. 실제 모델은
                load() 가 만들어 넣고, 테스트는 가짜를 넣는다.
        """
        self._score = score

    @classmethod
    def load(
        cls, model_dir: str | Path | None = None, *, device: str = "cpu"
    ) -> BertEmotionClassifier:
        """모델 폴더를 읽어 분류기를 만든다. 수 초가 걸리므로 서버 시작 때 한 번만 부른다.

        Args:
            model_dir: 모델 폴더. None 이면 EMOTION_MODEL_DIR 환경변수, 그것도 없으면
                models/model/ 을 쓴다.
            device: "cpu" 또는 "cuda".

        Returns:
            추론 준비가 끝난 분류기.

        Raises:
            FileNotFoundError: 모델 파일이 빠져 있을 때. 가중치를 안 받은 경우가 대부분이다.
            ValueError: 폴더의 모델이 이 코드가 아는 model1 v0.3 이 아닐 때.
            ImportError: torch 또는 transformers 가 없을 때.
        """
        path = Path(model_dir or os.environ.get("EMOTION_MODEL_DIR") or DEFAULT_MODEL_DIR)
        path = path.expanduser().resolve()
        missing = [name for name in REQUIRED_FILES if not (path / name).is_file()]
        if missing:
            raise FileNotFoundError(f"감정 모델 파일 없음: {path} ({', '.join(missing)})")

        meta = json.loads((path / "emotion_metadata.json").read_text(encoding="utf-8"))
        classes = [f"C{i}" for i in range(len(CLASS_LABELS))]
        # 클래스 순서가 다른 모델을 그대로 쓰면 예외 없이 라벨만 뒤바뀐다. 여기서 막는다.
        if meta.get("schema_version") != SCHEMA_VERSION or meta.get("classes") != classes:
            raise ValueError(f"{SCHEMA_VERSION} 모델이 아니다: {path}")

        # 허브에 접속하지 않는다. 아이 발화가 지나가는 프로세스다.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        # 전처리는 학습 때 쓴 것을 모델과 함께 저장해 둔 파일을 그대로 쓴다.
        spec = importlib.util.spec_from_file_location(
            "emotion_model_preprocessing", path / "preprocessing.py"
        )
        preprocessing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(preprocessing)

        tokenizer = AutoTokenizer.from_pretrained(
            str(path), local_files_only=True, trust_remote_code=False
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            str(path), local_files_only=True, trust_remote_code=False, use_safetensors=True
        )
        if [model.config.id2label[i] for i in range(len(classes))] != classes:
            raise ValueError(f"모델 출력 순서가 메타데이터와 다르다: {path}")
        model = model.to(torch.device(device)).eval()
        max_length = int(meta["max_length"])

        @torch.inference_mode()
        def score(text: str) -> list[float]:
            cleaned = preprocessing.prepare_inference_text(text)
            inputs = tokenizer(
                cleaned, return_tensors="pt", truncation=True, max_length=max_length
            ).to(model.device)
            return model(**inputs).logits[0].float().softmax(-1).cpu().tolist()

        return cls(score)

    async def classify(
        self, text: str, *, context: dict | None = None
    ) -> EmotionResult:
        """발화에 감정 라벨 하나를 매긴다.

        Args:
            text: 아이 발화(STT 결과).
            context: 인터페이스 통일용 부가 정보. 이 구현체에서는 사용하지 않는다.

        Returns:
            최고 점수 범주와 그 점수를 담은 EmotionResult. 모델이 읽을 수 없는 발화는
            점수 없는 중립.
        """
        t0 = time.perf_counter()
        try:
            # 추론은 CPU 에서 10ms 안팎이지만 동기 호출이라 이벤트 루프 밖에서 돌린다.
            scores = await asyncio.to_thread(self._score, text)
        except ValueError:
            return EmotionResult(
                classifier=self.name, latency_ms=(time.perf_counter() - t0) * 1000
            )
        index = max(range(len(CLASS_LABELS)), key=scores.__getitem__)
        return EmotionResult(
            label=CLASS_LABELS[index],
            confidence=scores[index],
            classifier=self.name,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
