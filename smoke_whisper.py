import json
import re
import time
from pathlib import Path

import whisper


MODEL_NAME = "turbo"

AUDIO_PATH = Path(
    "/Users/choheeyeon/Desktop/DodamDodam/"
    "011.한국어_아동_음성_데이터_원천/"
    "01.데이터/2.Validation/원천데이터/"
    "kor_free/2022-01-04/4522/"
    "K00014522-BMG23-L1N2D4-E-K0KK-02089153.wav"
)

LABEL_ROOT = (
    Path.home()
    / "Desktop"
    / "DodamDodam"
    / "011.한국어_아동_음성_데이터_라벨링"
    / "01.데이터"
    / "2.Validation"
    / "라벨링데이터"
)


def find_label_json(audio_path):
    json_name = f"{audio_path.stem}.json"

    matches = list(LABEL_ROOT.rglob(json_name))

    if not matches:
        raise FileNotFoundError(
            f"라벨링 JSON을 찾을 수 없습니다.\n"
            f"찾으려던 파일: {json_name}"
        )

    return matches[0]


def extract_reference_text(data):
    try:
        return data["Transcription"]["LabelText"].strip()
    except KeyError:
        raise ValueError(
            "JSON에서 Transcription -> LabelText를 찾을 수 없습니다."
        )


def normalize_text(text):
    text = text.strip().lower()

    text = re.sub(r"\s+", "", text)

    text = re.sub(
        r"[^\w가-힣]",
        "",
        text,
    )

    return text


def levenshtein_distance(reference, hypothesis):
    rows = len(reference) + 1
    cols = len(hypothesis) + 1

    dp = [[0] * cols for _ in range(rows)]

    for i in range(rows):
        dp[i][0] = i

    for j in range(cols):
        dp[0][j] = j

    for i in range(1, rows):
        for j in range(1, cols):

            if reference[i - 1] == hypothesis[j - 1]:
                cost = 0
            else:
                cost = 1

            dp[i][j] = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + cost,
            )

    return dp[-1][-1]


def calculate_cer(reference, hypothesis):
    reference = normalize_text(reference)
    hypothesis = normalize_text(hypothesis)

    if len(reference) == 0:
        return 0.0 if len(hypothesis) == 0 else 1.0

    distance = levenshtein_distance(
        reference,
        hypothesis,
    )

    return distance / len(reference)


def main():
    print("=" * 70)
    print("Whisper STT 단일 파일 성능 평가")
    print("=" * 70)

    if not AUDIO_PATH.exists():
        raise FileNotFoundError(
            f"음성 파일을 찾을 수 없습니다.\n"
            f"{AUDIO_PATH}"
        )

    print(f"음성 파일: {AUDIO_PATH.name}")
    print(f"Whisper 모델: {MODEL_NAME}")

    print()
    print("라벨링 JSON 찾는 중...")

    label_path = find_label_json(AUDIO_PATH)

    print(f"라벨링 파일: {label_path.name}")

    with open(
        label_path,
        "r",
        encoding="utf-8",
    ) as f:
        label_data = json.load(f)

    reference_text = extract_reference_text(
        label_data
    )

    print()
    print(f"정답 문장: {reference_text}")

    print()
    print("Whisper 모델 로딩 중...")

    model = whisper.load_model(
        MODEL_NAME
    )

    print("Whisper 모델 로딩 완료")

    print()
    print("STT 변환 중...")

    start_time = time.time()

    result = model.transcribe(
        str(AUDIO_PATH),
        language="ko",
        task="transcribe",
        fp16=False,
    )

    elapsed_time = (
        time.time() - start_time
    )

    whisper_text = (
        result["text"].strip()
    )

    cer = calculate_cer(
        reference_text,
        whisper_text,
    )

    exact_match = (
        normalize_text(reference_text)
        == normalize_text(whisper_text)
    )

    print()
    print("=" * 70)
    print("Whisper STT 평가 결과")
    print("=" * 70)

    print(f"정답     : {reference_text}")
    print(f"Whisper  : {whisper_text}")

    print()
    print(f"CER      : {cer * 100:.2f}%")

    if exact_match:
        print("정확 일치: YES")
    else:
        print("정확 일치: NO")

    print(f"처리 시간: {elapsed_time:.2f}초")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()