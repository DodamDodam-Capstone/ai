import csv
import json
import random
from collections import defaultdict
from pathlib import Path


AUDIO_DIR = (
    Path.home()
    / "Desktop"
    / "DodamDodam"
    / "011.한국어_아동_음성_데이터_원천"
    / "01.데이터"
    / "2.Validation"
    / "원천데이터"
)

LABEL_DIR = (
    Path.home()
    / "Desktop"
    / "DodamDodam"
    / "011.한국어_아동_음성_데이터_라벨링"
    / "01.데이터"
    / "2.Validation"
    / "라벨링데이터"
)

TARGET_SAMPLES = {
    7: 100,
    8: 100,
    9: 100,
    10: 100,
}

RANDOM_SEED = 42

OUTPUT_CSV = Path("stt_age_400_manifest.csv")


def main():
    random.seed(RANDOM_SEED)

    print("WAV 파일 목록 만드는 중...")

    wav_map = {
        wav_path.name: wav_path
        for wav_path in AUDIO_DIR.rglob("*.wav")
    }

    print(f"WAV 파일: {len(wav_map):,}개")

    candidates = defaultdict(list)

    print("JSON 라벨 데이터 확인 중...")

    for json_path in LABEL_DIR.rglob("*.json"):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            age_raw = data.get("Speaker", {}).get("Age")

            if age_raw is None:
                continue

            age_text = str(age_raw).strip()

            if not age_text.isdigit():
                continue

            age = int(age_text)

            if age not in TARGET_SAMPLES:
                continue

            wav_name = data.get("File", {}).get("FileName")

            reference = (
                data.get("Transcription", {})
                .get("LabelText", "")
                .strip()
            )

            if not wav_name:
                continue

            if not reference:
                continue

            wav_path = wav_map.get(wav_name)

            if wav_path is None:
                continue

            candidates[age].append(
                {
                    "age": age,
                    "wav_name": wav_name,
                    "wav_path": str(wav_path),
                    "json_path": str(json_path),
                    "reference": reference,
                }
            )

        except Exception as e:
            print(f"JSON 처리 오류: {json_path}")
            print(e)

    print("\n후보 데이터")
    print("-" * 40)

    for age in TARGET_SAMPLES:
        print(
            f"{age}세: "
            f"{len(candidates[age]):,}개 "
            f"(필요: {TARGET_SAMPLES[age]}개)"
        )

    selected = []

    print("\n연령별 랜덤 샘플 추출 중...")

    for age, sample_count in TARGET_SAMPLES.items():
        available_count = len(candidates[age])

        if available_count < sample_count:
            raise ValueError(
                f"{age}세 데이터가 부족합니다. "
                f"필요: {sample_count}개, "
                f"현재: {available_count}개"
            )

        sampled = random.sample(
            candidates[age],
            sample_count,
        )

        selected.extend(sampled)

    random.shuffle(selected)

    with open(
        OUTPUT_CSV,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "age",
                "wav_name",
                "wav_path",
                "json_path",
                "reference",
            ],
        )

        writer.writeheader()
        writer.writerows(selected)

    print("\n추출 완료")
    print("=" * 40)

    total_count = 0

    for age in TARGET_SAMPLES:
        count = sum(
            1
            for row in selected
            if row["age"] == age
        )

        total_count += count

        print(
            f"{age}세: "
            f"{count}개"
        )

    print("-" * 40)
    print(f"전체: {total_count}개")
    print(f"파일: {OUTPUT_CSV.resolve()}")

    print("\n샘플 구성 확인")

    for index, row in enumerate(selected[:10], start=1):
        print(
            f"{index}. "
            f"{row['age']}세 | "
            f"{row['wav_name']}"
        )


if __name__ == "__main__":
    main()