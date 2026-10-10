"""Qwen3-ASR를 로컬에서 실행해 연령별 400개(7~10세 각 100개)를 평가하고 CLOVA와 비교한다.

- 평가 대상과 정답은 CLOVA 400개 평가(logs/stt_age_400_validation_fresh.csv)와 동일하다.
- CER / 정규화 / Semantic 평가는 evaluate_qwen_hard_set.py와 같은 함수를 사용한다.
- 결과는 한 샘플씩 append 저장하므로 중단 후 다시 실행하면 이어서 평가한다.
- 모델은 QWEN_ASR_MODEL 환경변수로 지정한다 (evaluate_qwen_hard_set.py 참고).
"""

import csv
from collections import Counter, defaultdict
from pathlib import Path

from evaluate_qwen_hard_set import (
    FIELDNAMES,
    MODEL_NAME,
    RESULT_PREFIX,
    average,
    evaluate_sample,
    get_device,
    load_asr_model,
    read_csv,
    summarize_group,
)
from smoke_stt_batch import SemanticMatcher


BASE_DIR = Path(__file__).resolve().parent

CLOVA_RESULT_CSV = BASE_DIR / "logs" / "stt_age_400_validation_fresh.csv"
MANIFEST_CSV = BASE_DIR / "stt_age_400_manifest.csv"

LOG_DIR = BASE_DIR / "logs"
RESULT_CSV = LOG_DIR / f"{RESULT_PREFIX}_age_400.csv"
SUMMARY_TXT = LOG_DIR / f"{RESULT_PREFIX}_age_400_summary.txt"

AGES = [7, 8, 9, 10]
PER_AGE = 100

OUTPUT_FIELDS = FIELDNAMES + [
    "clova_exact_match",
    "clova_semantic_score",
]


def load_samples():
    audio_paths = {
        row["wav_name"]: row["wav_path"]
        for row in read_csv(MANIFEST_CSV)
    }

    samples = []

    for row in read_csv(CLOVA_RESULT_CSV):
        samples.append(
            {
                "sample_id": Path(row["file_name"]).stem,
                "age": row["age"],
                "audio_path": audio_paths[row["file_name"]],
                "ground_truth": row["reference_text"],
                "clova_result": row["stt_text"],
                "normalized_cer": row["normalized_cer"],
                "audio_duration_sec": row["duration_sec"],
                "clova_exact_match": (
                    row["normalized_reference"] == row["normalized_stt"]
                ),
                "clova_semantic_score": row["semantic_score"],
            }
        )

    age_counts = Counter(int(sample["age"]) for sample in samples)

    if any(age_counts.get(age, 0) != PER_AGE for age in AGES):
        raise ValueError(f"연령별 샘플 수가 {PER_AGE}개가 아닙니다: {dict(age_counts)}")

    return samples


def append_result(row):
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_exists = RESULT_CSV.exists()

    with open(RESULT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def summary_line(label, rows):
    summary = summarize_group(rows)

    clova_exact = sum(row["clova_exact_match"] == "True" for row in rows)
    clova_semantic = average([float(row["clova_semantic_score"]) for row in rows])

    return [
        f"{label} | {summary['count']}개",
        f"  CER(문장 평균)  CLOVA {summary['clova_cer'] * 100:6.2f}% | "
        f"Qwen {summary['qwen_cer'] * 100:6.2f}%",
        f"  정확 일치       CLOVA {clova_exact:3d}개    | "
        f"Qwen {summary['exact_count']:3d}개",
        f"  Semantic 평균   CLOVA {clova_semantic:.3f}   | "
        f"Qwen {summary['semantic']:.3f}",
        f"  Qwen CER 개선 {summary['improved']}개 / 악화 {summary['worse']}개 | "
        f"Qwen Corpus CER {summary['qwen_corpus_cer'] * 100:.2f}% | "
        f"Qwen 평균 처리 {summary['latency']:.2f}초",
    ]


def create_summary():
    rows = read_csv(RESULT_CSV)

    grouped = defaultdict(list)

    for row in rows:
        grouped[int(row["age"])].append(row)

    lines = [
        "=" * 72,
        "연령별 400개 평가: Qwen3-ASR vs CLOVA",
        "=" * 72,
        f"모델: {MODEL_NAME} (local, {get_device()[0]})",
        f"CLOVA 결과: {CLOVA_RESULT_CSV.name}",
        "",
    ]

    lines.extend(summary_line("전체", rows))
    lines.append("")
    lines.append("-" * 72)

    for age in AGES:
        if grouped.get(age):
            lines.extend(summary_line(f"{age}세", grouped[age]))
            lines.append("")

    lines.append("=" * 72)

    summary_text = "\n".join(lines)

    SUMMARY_TXT.write_text(summary_text, encoding="utf-8")

    print()
    print(summary_text)
    print()
    print(f"상세 로그: {RESULT_CSV}")
    print(f"요약 로그: {SUMMARY_TXT}")


def main():
    samples = load_samples()

    completed = {row["sample_id"] for row in read_csv(RESULT_CSV)}

    pending = [
        sample
        for sample in samples
        if sample["sample_id"] not in completed
    ]

    print("=" * 72)
    print(f"Qwen3-ASR 연령별 400개 평가 ({MODEL_NAME})")
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

            row["clova_exact_match"] = sample["clova_exact_match"]
            row["clova_semantic_score"] = sample["clova_semantic_score"]

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
