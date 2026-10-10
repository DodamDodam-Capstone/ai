import csv
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import whisper

try:
    from sentence_transformers import SentenceTransformer, util

    SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False


MODEL_NAME = "turbo"

SEMANTIC_MODEL_NAME = "jhgan/ko-sroberta-multitask"

SEMANTIC_MATCH_THRESHOLD = 0.85
SEMANTIC_REVIEW_THRESHOLD = 0.70


BASE_DIR = Path(__file__).resolve().parent

MANIFEST_PATH = BASE_DIR / "stt_age_100_manifest.csv"

LOG_DIR = BASE_DIR / "logs"

RESULT_CSV = LOG_DIR / "whisper_age_100.csv"
SUMMARY_TXT = LOG_DIR / "whisper_age_100_summary.txt"


AUDIO_ROOT = (
    Path.home()
    / "Desktop"
    / "DodamDodam"
    / "011.한국어_아동_음성_데이터_원천"
    / "01.데이터"
    / "2.Validation"
    / "원천데이터"
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


def normalize_text(text):
    text = text.strip().lower()

    text = re.sub(
        r"[^0-9a-zA-Z가-힣]",
        "",
        text,
    )

    return text


def levenshtein_distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))

    for i, ref_char in enumerate(reference, start=1):
        current = [i]

        for j, hyp_char in enumerate(hypothesis, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1

            substitute_cost = previous[j - 1]

            if ref_char != hyp_char:
                substitute_cost += 1

            current.append(
                min(
                    insert_cost,
                    delete_cost,
                    substitute_cost,
                )
            )

        previous = current

    return previous[-1]


def calculate_cer(reference, hypothesis, normalize=False):
    if normalize:
        reference = normalize_text(reference)
        hypothesis = normalize_text(hypothesis)
    else:
        reference = reference.strip()
        hypothesis = hypothesis.strip()

    if len(reference) == 0:
        if len(hypothesis) == 0:
            return 0, 0, 0.0

        return len(hypothesis), 0, 1.0

    errors = levenshtein_distance(
        reference,
        hypothesis,
    )

    cer = errors / len(reference)

    return errors, len(reference), cer


def get_manifest_value(row, candidates):
    lower_row = {
        str(key).strip().lower(): value
        for key, value in row.items()
    }

    for candidate in candidates:
        value = lower_row.get(candidate.lower())

        if value not in (None, ""):
            return str(value).strip()

    return None


def resolve_audio_path(row):
    candidates = [
        "audio_path",
        "wav_path",
        "file_path",
        "filepath",
        "path",
        "audio",
        "wav",
        "filename",
        "file_name",
    ]

    value = get_manifest_value(
        row,
        candidates,
    )

    if value is None:
        for _, item in row.items():
            if (
                isinstance(item, str)
                and item.lower().strip().endswith(".wav")
            ):
                value = item.strip()
                break

    if value is None:
        raise ValueError(
            f"Manifest에서 WAV 경로를 찾을 수 없습니다.\n"
            f"컬럼: {list(row.keys())}"
        )

    path = Path(value).expanduser()

    if path.exists():
        return path.resolve()

    local_path = BASE_DIR / path

    if local_path.exists():
        return local_path.resolve()

    audio_path = AUDIO_ROOT / path

    if audio_path.exists():
        return audio_path.resolve()

    matches = list(
        AUDIO_ROOT.rglob(path.name)
    )

    if len(matches) == 1:
        return matches[0].resolve()

    if len(matches) > 1:
        raise RuntimeError(
            f"같은 WAV 파일명이 여러 개 있습니다: {path.name}"
        )

    raise FileNotFoundError(
        f"WAV 파일을 찾을 수 없습니다.\n{value}"
    )


def resolve_label_path(audio_path):
    try:
        relative_path = audio_path.relative_to(
            AUDIO_ROOT
        )

        label_path = (
            LABEL_ROOT
            / relative_path
        ).with_suffix(".json")

        if label_path.exists():
            return label_path

    except ValueError:
        pass

    matches = list(
        LABEL_ROOT.rglob(
            f"{audio_path.stem}.json"
        )
    )

    if len(matches) == 1:
        return matches[0]

    if not matches:
        raise FileNotFoundError(
            f"라벨링 JSON을 찾지 못했습니다.\n"
            f"{audio_path.stem}.json"
        )

    raise RuntimeError(
        f"동일한 JSON 파일이 여러 개 있습니다.\n"
        f"{audio_path.stem}.json"
    )


def load_label(label_path):
    with open(
        label_path,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def get_reference_text(label_data):
    try:
        return (
            label_data["Transcription"]["LabelText"]
            .strip()
        )

    except KeyError as e:
        raise ValueError(
            "JSON에서 "
            "Transcription -> LabelText를 "
            "찾을 수 없습니다."
        ) from e


def parse_age(value):
    if value in (None, ""):
        return None

    match = re.search(
        r"\d+",
        str(value),
    )

    if not match:
        return None

    age = int(match.group())

    if age in (7, 8, 9, 10):
        return age

    return None


def find_age_in_json(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()

            if "age" in key_lower:
                age = parse_age(value)

                if age is not None:
                    return age

        for value in obj.values():
            age = find_age_in_json(value)

            if age is not None:
                return age

    elif isinstance(obj, list):
        for item in obj:
            age = find_age_in_json(item)

            if age is not None:
                return age

    return None


def get_age(row, label_data):
    value = get_manifest_value(
        row,
        [
            "age",
            "speaker_age",
            "child_age",
            "speakerage",
        ],
    )

    age = parse_age(value)

    if age is not None:
        return age

    for key, value in row.items():
        if "age" in str(key).lower():
            age = parse_age(value)

            if age is not None:
                return age

    age = find_age_in_json(
        label_data
    )

    if age is not None:
        return age

    raise ValueError(
        "나이 정보를 찾을 수 없습니다."
    )


def get_audio_duration(label_data):
    try:
        return float(
            label_data["File"]["FileLength"]
        )
    except (KeyError, TypeError, ValueError):
        return 0.0


def load_manifest():
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Manifest 파일이 없습니다.\n"
            f"{MANIFEST_PATH}"
        )

    with open(
        MANIFEST_PATH,
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f)

        rows = list(reader)

    return rows


def prepare_entries(rows):
    entries = []

    print()
    print("Manifest 및 라벨 확인 중...")

    for index, row in enumerate(
        rows,
        start=1,
    ):
        audio_path = resolve_audio_path(
            row
        )

        label_path = resolve_label_path(
            audio_path
        )

        label_data = load_label(
            label_path
        )

        reference = get_reference_text(
            label_data
        )

        age = get_age(
            row,
            label_data,
        )

        duration = get_audio_duration(
            label_data
        )

        entries.append(
            {
                "index": index,
                "age": age,
                "audio_path": audio_path,
                "label_path": label_path,
                "reference": reference,
                "duration": duration,
            }
        )

    return entries


def validate_distribution(entries):
    if len(entries) != 100:
        raise ValueError(
            f"평가 대상이 100개가 아닙니다: "
            f"{len(entries)}개"
        )

    age_counts = Counter(
        entry["age"]
        for entry in entries
    )

    print()
    print("=" * 70)
    print("평가 대상 확인")
    print("=" * 70)

    for age in [7, 8, 9, 10]:
        print(
            f"{age}세: "
            f"{age_counts.get(age, 0)}개"
        )

    expected = {
        7: 25,
        8: 25,
        9: 25,
        10: 25,
    }

    if dict(age_counts) != expected:
        raise ValueError(
            "연령별 샘플 수가 "
            "각 25개가 아닙니다.\n"
            f"현재 분포: {dict(age_counts)}"
        )


def load_completed_files():
    if not RESULT_CSV.exists():
        return set()

    completed = set()

    with open(
        RESULT_CSV,
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f)

        for row in reader:
            completed.add(
                row["filename"]
            )

    return completed


def semantic_evaluate(
    semantic_model,
    reference,
    hypothesis,
):
    if semantic_model is None:
        return None, "N/A"

    embeddings = semantic_model.encode(
        [
            reference,
            hypothesis,
        ],
        convert_to_tensor=True,
    )

    score = float(
        util.cos_sim(
            embeddings[0],
            embeddings[1],
        ).item()
    )

    if score >= SEMANTIC_MATCH_THRESHOLD:
        label = "MATCH"

    elif score >= SEMANTIC_REVIEW_THRESHOLD:
        label = "REVIEW"

    else:
        label = "MISMATCH"

    return score, label


def append_result(row):
    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "index",
        "filename",
        "age",
        "reference",
        "whisper_text",
        "raw_errors",
        "raw_ref_chars",
        "raw_cer",
        "normalized_errors",
        "normalized_ref_chars",
        "normalized_cer",
        "exact_match",
        "semantic_score",
        "semantic_label",
        "audio_duration_sec",
        "whisper_latency_sec",
        "rtf",
        "model",
    ]

    file_exists = RESULT_CSV.exists()

    with open(
        RESULT_CSV,
        "a",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def read_results():
    if not RESULT_CSV.exists():
        return []

    with open(
        RESULT_CSV,
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return list(
            csv.DictReader(f)
        )


def summarize_group(rows):
    raw_errors = sum(
        int(row["raw_errors"])
        for row in rows
    )

    raw_chars = sum(
        int(row["raw_ref_chars"])
        for row in rows
    )

    norm_errors = sum(
        int(row["normalized_errors"])
        for row in rows
    )

    norm_chars = sum(
        int(row["normalized_ref_chars"])
        for row in rows
    )

    raw_corpus_cer = (
        raw_errors / raw_chars
        if raw_chars
        else 0.0
    )

    norm_corpus_cer = (
        norm_errors / norm_chars
        if norm_chars
        else 0.0
    )

    sentence_cers = [
        float(row["normalized_cer"])
        for row in rows
    ]

    average_sentence_cer = (
        sum(sentence_cers)
        / len(sentence_cers)
        if sentence_cers
        else 0.0
    )

    exact_count = sum(
        row["exact_match"] == "True"
        for row in rows
    )

    latencies = [
        float(row["whisper_latency_sec"])
        for row in rows
    ]

    average_latency = (
        sum(latencies)
        / len(latencies)
        if latencies
        else 0.0
    )

    semantic_scores = [
        float(row["semantic_score"])
        for row in rows
        if row["semantic_score"]
        not in ("", "None", "N/A")
    ]

    average_semantic = (
        sum(semantic_scores)
        / len(semantic_scores)
        if semantic_scores
        else None
    )

    semantic_counts = Counter(
        row["semantic_label"]
        for row in rows
        if row["semantic_label"] != "N/A"
    )

    return {
        "count": len(rows),
        "raw_corpus_cer": raw_corpus_cer,
        "norm_corpus_cer": norm_corpus_cer,
        "average_sentence_cer": average_sentence_cer,
        "exact_count": exact_count,
        "exact_rate": (
            exact_count / len(rows)
            if rows
            else 0.0
        ),
        "average_latency": average_latency,
        "average_semantic": average_semantic,
        "semantic_counts": semantic_counts,
    }


def create_summary():
    rows = read_results()

    grouped = defaultdict(list)

    for row in rows:
        grouped[int(row["age"])].append(
            row
        )

    lines = []

    lines.append(
        "=" * 72
    )
    lines.append(
        "한국어 아동 음성 Whisper STT 연령별 평가"
    )
    lines.append(
        "=" * 72
    )
    lines.append("")

    lines.append(
        f"Whisper 모델: {MODEL_NAME}"
    )
    lines.append(
        f"전체 평가 대상: {len(rows)}개"
    )
    lines.append("")

    overall = summarize_group(
        rows
    )

    lines.append(
        "-" * 72
    )
    lines.append(
        "전체 결과"
    )
    lines.append(
        "-" * 72
    )

    lines.append(
        f"Raw Corpus CER: "
        f"{overall['raw_corpus_cer'] * 100:.2f}%"
    )

    lines.append(
        f"Normalized Corpus CER: "
        f"{overall['norm_corpus_cer'] * 100:.2f}%"
    )

    lines.append(
        f"문장 평균 CER: "
        f"{overall['average_sentence_cer'] * 100:.2f}%"
    )

    lines.append(
        f"정확 일치: "
        f"{overall['exact_count']}/{overall['count']} "
        f"({overall['exact_rate'] * 100:.1f}%)"
    )

    if overall["average_semantic"] is not None:
        lines.append(
            f"평균 Semantic Similarity: "
            f"{overall['average_semantic']:.3f}"
        )

        counts = overall[
            "semantic_counts"
        ]

        lines.append(
            "Semantic 분류: "
            f"MATCH {counts.get('MATCH', 0)} / "
            f"REVIEW {counts.get('REVIEW', 0)} / "
            f"MISMATCH {counts.get('MISMATCH', 0)}"
        )

    lines.append(
        f"평균 Whisper 처리 시간: "
        f"{overall['average_latency']:.2f}초"
    )

    lines.append("")
    lines.append(
        "-" * 72
    )
    lines.append(
        "연령별 결과"
    )
    lines.append(
        "-" * 72
    )

    for age in [7, 8, 9, 10]:
        age_rows = grouped.get(
            age,
            [],
        )

        if not age_rows:
            continue

        summary = summarize_group(
            age_rows
        )

        line = (
            f"{age}세 | "
            f"{summary['count']}개 | "
            f"Raw CER "
            f"{summary['raw_corpus_cer'] * 100:.2f}% | "
            f"Normalized CER "
            f"{summary['norm_corpus_cer'] * 100:.2f}% | "
            f"문장 평균 CER "
            f"{summary['average_sentence_cer'] * 100:.2f}% | "
            f"정확 일치 "
            f"{summary['exact_rate'] * 100:.1f}% | "
            f"평균 처리 "
            f"{summary['average_latency']:.2f}초"
        )

        if summary["average_semantic"] is not None:
            line += (
                f" | Semantic "
                f"{summary['average_semantic']:.3f}"
            )

        lines.append(line)

        if summary["average_semantic"] is not None:
            counts = summary[
                "semantic_counts"
            ]

            lines.append(
                "     Semantic 분류: "
                f"MATCH {counts.get('MATCH', 0)} / "
                f"REVIEW {counts.get('REVIEW', 0)} / "
                f"MISMATCH {counts.get('MISMATCH', 0)}"
            )

    lines.append("")
    lines.append(
        "=" * 72
    )

    summary_text = "\n".join(
        lines
    )

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    SUMMARY_TXT.write_text(
        summary_text,
        encoding="utf-8",
    )

    print()
    print(summary_text)

    print()
    print(
        f"상세 로그: {RESULT_CSV}"
    )

    print(
        f"요약 로그: {SUMMARY_TXT}"
    )


def main():
    print("=" * 72)
    print(
        "Whisper turbo 아동 음성 "
        "100개 성능 평가"
    )
    print("=" * 72)

    rows = load_manifest()

    print(
        f"Manifest 평가 대상: "
        f"{len(rows)}개"
    )

    entries = prepare_entries(
        rows
    )

    validate_distribution(
        entries
    )

    completed_files = (
        load_completed_files()
    )

    pending_entries = [
        entry
        for entry in entries
        if entry["audio_path"].name
        not in completed_files
    ]

    print()
    print(
        f"이미 완료된 파일: "
        f"{len(completed_files)}개"
    )

    print(
        f"이번 실행 대상: "
        f"{len(pending_entries)}개"
    )

    if not pending_entries:
        print()
        print(
            "모든 파일의 평가가 "
            "이미 완료되었습니다."
        )

        create_summary()
        return

    print()
    print(
        f"Whisper 모델 로딩: "
        f"{MODEL_NAME}"
    )

    whisper_model = whisper.load_model(
        MODEL_NAME
    )

    print(
        "Whisper 모델 로딩 완료"
    )

    semantic_model = None

    if SEMANTIC_AVAILABLE:
        print()
        print(
            "Semantic Match 모델 로딩: "
            f"{SEMANTIC_MODEL_NAME}"
        )

        semantic_model = (
            SentenceTransformer(
                SEMANTIC_MODEL_NAME
            )
        )

        print(
            "Semantic Match 모델 로딩 완료"
        )

    else:
        print()
        print(
            "sentence-transformers가 "
            "설치되지 않아 "
            "Semantic 평가는 생략합니다."
        )

    print()

    for current, entry in enumerate(
        pending_entries,
        start=1,
    ):
        audio_path = entry[
            "audio_path"
        ]

        reference = entry[
            "reference"
        ]

        print(
            f"[{current}/{len(pending_entries)}] "
            f"{entry['age']}세 | "
            f"{audio_path.name}"
        )

        start_time = time.time()

        try:
            result = whisper_model.transcribe(
                str(audio_path),
                language="ko",
                task="transcribe",
                fp16=False,
                verbose=False,
            )

            whisper_text = (
                result["text"].strip()
            )

        except Exception as e:
            print(
                f"  Whisper 오류: {e}"
            )
            print()
            continue

        latency = (
            time.time() - start_time
        )

        raw_errors, raw_chars, raw_cer = (
            calculate_cer(
                reference,
                whisper_text,
                normalize=False,
            )
        )

        (
            norm_errors,
            norm_chars,
            norm_cer,
        ) = calculate_cer(
            reference,
            whisper_text,
            normalize=True,
        )

        exact_match = (
            normalize_text(reference)
            == normalize_text(
                whisper_text
            )
        )

        (
            semantic_score,
            semantic_label,
        ) = semantic_evaluate(
            semantic_model,
            reference,
            whisper_text,
        )

        duration = entry[
            "duration"
        ]

        if duration > 0:
            rtf = latency / duration
        else:
            rtf = 0.0

        output_row = {
            "index": entry["index"],
            "filename": audio_path.name,
            "age": entry["age"],
            "reference": reference,
            "whisper_text": whisper_text,
            "raw_errors": raw_errors,
            "raw_ref_chars": raw_chars,
            "raw_cer": f"{raw_cer:.6f}",
            "normalized_errors": norm_errors,
            "normalized_ref_chars": norm_chars,
            "normalized_cer": (
                f"{norm_cer:.6f}"
            ),
            "exact_match": exact_match,
            "semantic_score": (
                f"{semantic_score:.6f}"
                if semantic_score
                is not None
                else ""
            ),
            "semantic_label": (
                semantic_label
            ),
            "audio_duration_sec": (
                f"{duration:.3f}"
            ),
            "whisper_latency_sec": (
                f"{latency:.3f}"
            ),
            "rtf": f"{rtf:.3f}",
            "model": MODEL_NAME,
        }

        append_result(
            output_row
        )

        print(
            f"  정답    : {reference}"
        )

        print(
            f"  Whisper : {whisper_text}"
        )

        print(
            f"  CER     : "
            f"{norm_cer * 100:.2f}%"
        )

        if semantic_score is not None:
            print(
                f"  Semantic: "
                f"{semantic_score:.3f} "
                f"({semantic_label})"
            )

        print(
            f"  처리시간: "
            f"{latency:.2f}초"
        )

        print()

    create_summary()


if __name__ == "__main__":
    main()