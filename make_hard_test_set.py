"""CLOVA STT 평가 결과에서 인식 실패 사례를 추출해 고정 Hard Test Set을 만든다.

- 이미 저장된 평가 결과만 사용한다 (STT API 재호출 없음).
- 원본 평가 결과 / audio 파일은 읽기만 하고 수정하지 않는다.
- 나이별(7~10세) exact match가 아닌 샘플을 CER 내림차순으로 25개씩 선택한다.
"""

import csv
from collections import Counter
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

RESULT_CSV = BASE_DIR / "logs" / "stt_age_400_validation_fresh.csv"
MANIFEST_CSV = BASE_DIR / "stt_age_400_manifest.csv"
OUTPUT_CSV = BASE_DIR / "hard_test_100.csv"

STT_MODEL = "clova"
AGES = [7, 8, 9, 10]
PER_AGE = 25

OUTPUT_FIELDS = [
    "sample_id",
    "age",
    "audio_path",
    "label_path",
    "ground_truth",
    "clova_result",
    "raw_cer",
    "normalized_cer",
    "semantic_similarity",
    "semantic_label",
    "exact_match",
    "processing_time_sec",
    "audio_duration_sec",
    "gender",
    "snr_db",
    "recording_environment",
    "noise_environment",
    "stt_model",
    "error_type",
]


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def is_exact_match(row):
    # evaluate_whisper_100.py와 동일하게 정규화 텍스트 일치 여부로 판단
    return row["normalized_reference"] == row["normalized_stt"]


def load_audio_paths():
    paths = {}

    for row in read_csv(MANIFEST_CSV):
        paths[row["wav_name"]] = (row["wav_path"], row["json_path"])

    return paths


def select_hard_samples(results):
    candidates = [
        row
        for row in results
        if row["success"] == "True" and not is_exact_match(row)
    ]

    selected = []

    for age in AGES:
        age_rows = [row for row in candidates if int(row["age"]) == age]

        if len(age_rows) < PER_AGE:
            raise ValueError(
                f"{age}세 후보가 부족합니다: {len(age_rows)}개 (필요 {PER_AGE}개)"
            )

        age_rows.sort(
            key=lambda row: (
                -float(row["normalized_cer"]),
                -float(row["raw_cer"]),
                row["file_name"],
            )
        )

        selected.extend(age_rows[:PER_AGE])

    return selected


def build_output_rows(selected, audio_paths):
    output_rows = []

    for row in selected:
        file_name = row["file_name"]

        if file_name not in audio_paths:
            raise KeyError(f"Manifest에 audio 경로가 없습니다: {file_name}")

        audio_path, label_path = audio_paths[file_name]

        if not Path(audio_path).exists():
            raise FileNotFoundError(f"audio 파일이 없습니다: {audio_path}")

        output_rows.append(
            {
                "sample_id": Path(file_name).stem,
                "age": int(row["age"]),
                "audio_path": audio_path,
                "label_path": label_path,
                "ground_truth": row["reference_text"],
                "clova_result": row["stt_text"],
                "raw_cer": row["raw_cer"],
                "normalized_cer": row["normalized_cer"],
                "semantic_similarity": row["semantic_score"],
                "semantic_label": row["semantic_label"],
                "exact_match": is_exact_match(row),
                "processing_time_sec": row["latency_sec"],
                "audio_duration_sec": row["duration_sec"],
                "gender": row["gender"],
                "snr_db": row["snr_db"],
                "recording_environment": row["recording_environment"],
                "noise_environment": row["noise_environment"],
                "stt_model": STT_MODEL,
                "error_type": "",
            }
        )

    return output_rows


def write_output(rows):
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def average(values):
    return sum(values) / len(values) if values else 0.0


def print_summary(rows):
    age_counts = Counter(row["age"] for row in rows)
    raw_cers = [float(row["raw_cer"]) for row in rows]
    norm_cers = [float(row["normalized_cer"]) for row in rows]
    semantic_scores = [
        float(row["semantic_similarity"])
        for row in rows
        if row["semantic_similarity"] not in ("", "None")
    ]

    print("=" * 72)
    print("CLOVA STT Hard Test Set")
    print("=" * 72)
    print(f"전체 샘플: {len(rows)}개")
    print()

    for age in AGES:
        print(f"{age}세: {age_counts.get(age, 0)}개")

    print()
    print(f"평균 Raw CER: {average(raw_cers) * 100:.2f}%")
    print(f"평균 Normalized CER: {average(norm_cers) * 100:.2f}%")
    print(f"평균 Semantic Similarity: {average(semantic_scores):.3f}")
    print()
    print(f"CER 최소: {min(norm_cers) * 100:.2f}% (Normalized)")
    print(f"CER 최대: {max(norm_cers) * 100:.2f}% (Normalized)")
    print("=" * 72)
    print()
    print(f"원본 평가 결과: {RESULT_CSV}")
    print(f"audio 경로 manifest: {MANIFEST_CSV}")
    print(f"출력 파일: {OUTPUT_CSV}")


def main():
    results = read_csv(RESULT_CSV)
    audio_paths = load_audio_paths()

    selected = select_hard_samples(results)
    output_rows = build_output_rows(selected, audio_paths)

    write_output(output_rows)
    print_summary(output_rows)


if __name__ == "__main__":
    main()
