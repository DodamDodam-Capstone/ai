"""
Qwen3-ASR STT 구현체 (로컬 추론).

SCRUM-120 비교 실험에서 아동 음성 정확도가 가장 높았던 Qwen3-ASR 1.7B 를 쓴다.
결과는 docs/stt/STT_EXPERIMENTS.md 참고.

들어온 음성을 텍스트로 바꾸기만 한다. 잘못 누름·무음 판단과 재녹음 처리는
백엔드가 맡는다.

모델은 생성 시 한 번만 올리고 계속 재사용한다. 요청마다 올리면 수십 초가 걸린다.
torch, qwen-asr, av 는 requirements.txt 에 없으므로 쓰는 시점에만 import 한다.

모델은 QWEN_ASR_MODEL 환경변수로 바꿀 수 있다. 기본값은 Qwen/Qwen3-ASR-1.7B.
"""

from __future__ import annotations

import asyncio
import io
import os

from core.interfaces import STTEngine, STTResult, UnsupportedAudioError

DEFAULT_MODEL_NAME = "Qwen/Qwen3-ASR-1.7B"
LANGUAGE = "Korean"
# Qwen3-ASR 입력 샘플레이트
TARGET_SR = 16000


class QwenSTT(STTEngine):
    name = "qwen3_asr"

    def __init__(self, model_name: str | None = None):
        import torch
        from qwen_asr import Qwen3ASRModel

        self.model_name = model_name or os.environ.get(
            "QWEN_ASR_MODEL", DEFAULT_MODEL_NAME
        )

        if torch.cuda.is_available():
            device, dtype = "cuda:0", torch.bfloat16
        elif torch.backends.mps.is_available():
            device, dtype = "mps", torch.bfloat16
        else:
            device, dtype = "cpu", torch.float32

        self._model = Qwen3ASRModel.from_pretrained(
            self.model_name,
            dtype=dtype,
            device_map=device,
            max_inference_batch_size=1,
        )
        # 모델 하나를 여러 요청이 동시에 쓰지 않도록 한 번에 하나씩 추론한다.
        self._lock = asyncio.Lock()

    async def transcribe(self, audio: bytes, *, sample_rate: int = 16000) -> STTResult:
        wav, sr = _decode_audio(audio)

        # 추론은 동기 호출이라 이벤트 루프를 막지 않도록 스레드로 넘긴다.
        async with self._lock:
            result = await asyncio.to_thread(
                self._model.transcribe, audio=(wav, sr), language=LANGUAGE
            )

        return STTResult(
            text=(result[0].text or "").strip(),
            raw={
                "language": result[0].language,
                "audio_duration_sec": round(len(wav) / sr, 3) if sr else 0.0,
                "model": self.model_name,
            },
            engine=self.name,
        )


def _decode_audio(audio: bytes):
    """녹음 파일 바이트를 (16kHz 모노 float32 파형, 샘플레이트) 로 바꾼다.

    PyAV(FFmpeg)로 읽으므로 webm, m4a, ogg, wav 를 같은 경로로 처리한다.
    파일이 아닌 헤더 없는 PCM 은 받지 않는다. 엉뚱한 바이트를 PCM 으로 읽으면
    잡음이 되고, 모델이 그 잡음에서 문장을 지어내기 때문이다.

    Raises:
        UnsupportedAudioError: 비어 있거나 읽을 수 없는 파일.
    """
    import av
    import numpy as np

    if not audio:
        raise UnsupportedAudioError("빈 오디오")

    try:
        with av.open(io.BytesIO(audio)) as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_SR)
            chunks = [
                out.to_ndarray().reshape(-1)
                for frame in container.decode(audio=0)
                for out in resampler.resample(frame)
            ]
            # 리샘플러 안에 남은 샘플을 비운다.
            chunks += [out.to_ndarray().reshape(-1) for out in resampler.resample(None)]
    except (av.FFmpegError, IndexError, ValueError) as e:
        raise UnsupportedAudioError(f"오디오를 읽을 수 없음: {e}") from e

    if not chunks:
        raise UnsupportedAudioError("오디오 프레임 없음")

    wav = np.concatenate(chunks).astype(np.float32) / 32768.0
    return wav, TARGET_SR
