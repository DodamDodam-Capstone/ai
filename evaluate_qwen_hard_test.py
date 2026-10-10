"""Qwen3-ASR를 로컬(MPS)에서 실행해 hard_test_100.csv를 평가한다.

- CER / 정규화 / Semantic 평가는 CLOVA 평가(smoke_stt_batch.py)와 같은 함수를 사용해
  hard_test_100.csv의 CLOVA 수치와 바로 비교할 수 있게 한다.
- 결과는 한 샘플씩 append 저장하므로 중단 후 다시 실행하면 이어서 평가한다.
- 기본 모델은 1.7B이며, QWEN_ASR_MODEL 환경변수로 다른 크기를 지정할 수 있다.
  예) QWEN_ASR_MODEL=Qwen/Qwen3-ASR-0.6B .venv/bin/python evaluate_qwen_hard_test.py
- 모델 이름에 "mlx"가 들어 있으면 mlx-audio(Apple GPU)로 실행한다. transformers 버전이 달라
  별도 가상환경(.venv-mlx)을 사용한다.
  예) QWEN_ASR_MODEL=mlx-community/Qwen3-ASR-0.6B-4bit .venv-mlx/bin/python evaluate_qwen_hard_test.py
"""

import csv
import os
import time
from collections import defaultdict
from pathlib import Path

import torch

from smoke_stt_batch import (
    SemanticMatcher,
    calculate_cer,
    normalize_basic,
    normalize_semantic,
)


DEFAULT_MODEL_NAME = "Qwen/Qwen3-ASR-1.7B"
MODEL_NAME = os.environ.get("QWEN_ASR_MODEL", DEFAULT_MODEL_NAME)

USE_MLX = "mlx" in MODEL_NAME.lower()

# 1.7B는 기존 파일명(qwen3_asr_*)을 유지하고, 다른 모델은 qwen3_asr_0.6b_*,
# qwen3_asr_0.6b_4bit_* 처럼 모델 이름의 "Qwen3-ASR-" 뒷부분으로 구분한다.
if MODEL_NAME == DEFAULT_MODEL_NAME:
    RESULT_PREFIX = "qwen3_asr"
else:
    RESULT_PREFIX = "qwen3_asr_" + (
        MODEL_NAME.split("Qwen3-ASR-", 1)[-1].lower().replace("-", "_")
    )
LANGUAGE = "Korean"

BASE_DIR = Path(__file__).resolve().parent

HARD_TEST_CSV = BASE_DIR / "hard_test_100.csv"
LOG_DIR = BASE_DIR / "logs"
RESULT_CSV = LOG_DIR / f"{RESULT_PREFIX}_hard_test_100.csv"
SUMMARY_TXT = LOG_DIR / f"{RESULT_PREFIX}_hard_test_100_summary.txt"

AGES = [7, 8, 9, 10]

FIELDNAMES = [
    "sample_id",
    "age",
    "ground_truth",
    "clova_result",
    "qwen_result",
    "clova_normalized_cer",
    "raw_cer",
    "normalized_cer",
    "raw_edit_distance",
    "raw_ref_chars",
    "normalized_edit_distance",
    "normalized_ref_chars",
    "exact_match",
    "semantic_score",
    "semantic_label",
    "semantic_flags",
    "audio_duration_sec",
    "processing_time_sec",
    "rtf",
    "model",
]


def get_device():
    if USE_MLX:
        return "mlx", None

    if torch.backends.mps.is_available():
        return "mps", torch.bfloat16

    if torch.cuda.is_available():
        return "cuda:0", torch.bfloat16

    return "cpu", torch.float32


class MLXASRModel:
    """mlx-audio 모델을 qwen_asr.Qwen3ASRModel.transcribe()와 같은 형태로 감싼다."""

    def __init__(self, model_name):
        from mlx_audio.stt.utils import load_model

        self.model = load_model(model_name)

    def transcribe(self, audio, language=None):
        return [self.model.generate(audio, language=language)]


def load_asr_model():
    device, dtype = get_device()

    print()
    print(f"Qwen3-ASR 모델 로딩: {MODEL_NAME} ({device})")

    if USE_MLX:
        return MLXASRModel(MODEL_NAME)

    from qwen_asr import Qwen3ASRModel

    return Qwen3ASRModel.from_pretrained(
        MODEL_NAME,
        dtype=dtype,
        device_map=device,
        max_inference_batch_size=1,
    )


def read_csv(path):
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_result(row):
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_exists = RESULT_CSV.exists()

    with open(RESULT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def evaluate_sample(model, semantic_matcher, sample):
    reference = sample["ground_truth"]

    start = time.perf_counter()
    result = model.transcribe(audio=sample["audio_path"], language=LANGUAGE)
    latency = time.perf_counter() - start

    qwen_text = result[0].text.strip()

    raw_cer, raw_distance, raw_chars = calculate_cer(
        normalize_basic(reference),
        normalize_basic(qwen_text),
    )

    normalized_reference = normalize_semantic(reference)
    normalized_qwen = normalize_semantic(qwen_text)

    norm_cer, norm_distance, norm_chars = calculate_cer(
        normalized_reference,
        normalized_qwen,
    )

    semantic = semantic_matcher.evaluate(reference, qwen_text)

    duration = float(sample["audio_duration_sec"] or 0)

    return {
        "sample_id": sample["sample_id"],
        "age": sample["age"],
        "ground_truth": reference,
        "clova_result": sample["clova_result"],
        "qwen_result": qwen_text,
        "clova_normalized_cer": sample["normalized_cer"],
        "raw_cer": f"{raw_cer:.6f}",
        "normalized_cer": f"{norm_cer:.6f}",
        "raw_edit_distance": raw_distance,
        "raw_ref_chars": raw_chars,
        "normalized_edit_distance": norm_distance,
        "normalized_ref_chars": norm_chars,
        "exact_match": normalized_reference == normalized_qwen,
        "semantic_score": semantic["semantic_score"],
        "semantic_label": semantic["semantic_label"],
        "semantic_flags": semantic["semantic_flags"],
        "audio_duration_sec": f"{duration:.3f}",
        "processing_time_sec": f"{latency:.3f}",
        "rtf": f"{latency / duration:.3f}" if duration > 0 else "",
        "model": MODEL_NAME,
    }


def average(values):
    return sum(values) / len(values) if values else 0.0


def summarize_group(rows):
    clova_cers = [float(row["clova_normalized_cer"]) for row in rows]
    qwen_cers = [float(row["normalized_cer"]) for row in rows]

    norm_errors = sum(int(row["normalized_edit_distance"]) for row in rows)
    norm_chars = sum(int(row["normalized_ref_chars"]) for row in rows)

    return {
        "count": len(rows),
        "clova_cer": average(clova_cers),
        "qwen_cer": average(qwen_cers),
        "qwen_corpus_cer": norm_errors / norm_chars if norm_chars else 0.0,
        "exact_count": sum(row["exact_match"] == "True" for row in rows),
        "improved": sum(q < c for q, c in zip(qwen_cers, clova_cers)),
        "worse": sum(q > c for q, c in zip(qwen_cers, clova_cers)),
        "semantic": average([float(row["semantic_score"]) for row in rows]),
        "latency": average([float(row["processing_time_sec"]) for row in rows]),
    }


def create_summary():
    rows = read_csv(RESULT_CSV)

    grouped = defaultdict(list)

    for row in rows:
        grouped[int(row["age"])].append(row)

    overall = summarize_group(rows)

    lines = [
        "=" * 72,
        "Hard Test Set 평가: Qwen3-ASR vs CLOVA",
        "=" * 72,
        f"모델: {MODEL_NAME} (local, {get_device()[0]})",
        f"평가 샘플: {overall['count']}개",
        "",
        f"CLOVA 문장 평균 Normalized CER: {overall['clova_cer'] * 100:.2f}%",
        f"Qwen  문장 평균 Normalized CER: {overall['qwen_cer'] * 100:.2f}%",
        f"Qwen  Normalized Corpus CER: {overall['qwen_corpus_cer'] * 100:.2f}%",
        f"Qwen  정확 일치: {overall['exact_count']}/{overall['count']}",
        f"Qwen  평균 Semantic Similarity: {overall['semantic']:.3f}",
        f"CLOVA 대비 CER 개선 {overall['improved']}개 / 악화 {overall['worse']}개",
        f"Qwen  평균 처리 시간: {overall['latency']:.2f}초",
        "",
        "-" * 72,
        "연령별 결과",
        "-" * 72,
    ]

    for age in AGES:
        age_rows = grouped.get(age, [])

        if not age_rows:
            continue

        summary = summarize_group(age_rows)

        lines.append(
            f"{age}세 | {summary['count']}개 | "
            f"CLOVA CER {summary['clova_cer'] * 100:.2f}% | "
            f"Qwen CER {summary['qwen_cer'] * 100:.2f}% | "
            f"정확 일치 {summary['exact_count']} | "
            f"개선 {summary['improved']} / 악화 {summary['worse']} | "
            f"Semantic {summary['semantic']:.3f}"
        )

    lines.append("=" * 72)

    summary_text = "\n".join(lines)

    SUMMARY_TXT.write_text(summary_text, encoding="utf-8")

    print()
    print(summary_text)
    print()
    print(f"상세 로그: {RESULT_CSV}")
    print(f"요약 로그: {SUMMARY_TXT}")


def main():
    samples = read_csv(HARD_TEST_CSV)

    completed = {row["sample_id"] for row in read_csv(RESULT_CSV)}

    pending = [
        sample
        for sample in samples
        if sample["sample_id"] not in completed
    ]

    print("=" * 72)
    print(f"Qwen3-ASR Hard Test 평가 ({MODEL_NAME})")
    print("=" * 72)
    print(f"전체: {len(samples)}개 | 완료: {len(completed)}개 | 이번 실행: {len(pending)}개")

    if pending:
        model = load_asr_model()

        semantic_matcher = SemanticMatcher()

        print()

        for current, sample in enumerate(pending, start=1):
            print(f"[{current}/{len(pending)}] {sample['age']}세 | {sample['sample_id']}")

            try:
                row = evaluate_sample(model, semantic_matcher, sample)

            except Exception as e:
                print(f"  Qwen 오류: {e}")
                print()
                continue

            append_result(row)

            print(f"  정답 : {row['ground_truth']}")
            print(f"  CLOVA: {row['clova_result']}")
            print(f"  Qwen : {row['qwen_result']}")
            print(
                f"  CER  : CLOVA {float(row['clova_normalized_cer']) * 100:.2f}% "
                f"-> Qwen {float(row['normalized_cer']) * 100:.2f}% "
                f"| {row['processing_time_sec']}초"
            )
            print()

    create_summary()


if __name__ == "__main__":
    main()
