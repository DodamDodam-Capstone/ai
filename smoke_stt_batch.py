import asyncio
import csv
import json
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

from stt.clova import ClovaSTT


MANIFEST_FILE = Path("stt_age_400_manifest.csv")
OUTPUT_FILE = Path("logs/stt_age_400_validation_fresh.csv")
LLM_REVIEW_FILE = Path("logs/stt_age_400_llm_review_fresh.jsonl")

TARGET_AGES = [7, 8, 9, 10]

SEMANTIC_MODEL_NAME = "jhgan/ko-sroberta-multitask"
SEMANTIC_MATCH_THRESHOLD = 0.85
SEMANTIC_REVIEW_THRESHOLD = 0.70


KOREAN_DIGITS = {
    "영": "0",
    "공": "0",
    "일": "1",
    "이": "2",
    "삼": "3",
    "사": "4",
    "오": "5",
    "육": "6",
    "칠": "7",
    "팔": "8",
    "구": "9",
}


UNIT_REPLACEMENTS = {
    "킬로미터": "km",
    "센티미터": "cm",
    "센치미터": "cm",
    "밀리미터": "mm",
    "킬로그램": "kg",
    "밀리그램": "mg",
    "퍼센트": "%",
    "센치": "cm",
    "미터": "m",
    "그램": "g",
}


FIELDNAMES = [
    "file_name",
    "age",
    "gender",
    "school_year",
    "dialect",
    "snr_db",
    "duration_sec",
    "recording_environment",
    "noise_environment",
    "recording_device",
    "quality_status",
    "reference_text",
    "stt_text",
    "raw_reference",
    "raw_stt",
    "normalized_reference",
    "normalized_stt",
    "confidence",
    "raw_cer",
    "raw_cer_percent",
    "normalized_cer",
    "normalized_cer_percent",
    "raw_edit_distance",
    "raw_ref_chars",
    "normalized_edit_distance",
    "normalized_ref_chars",
    "semantic_score",
    "semantic_label",
    "semantic_match",
    "semantic_flags",
    "needs_llm_review",
    "latency_sec",
    "success",
    "error",
    "tested_at",
]


def normalize_basic(text: str) -> str:
    if text is None:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        str(text),
    )

    text = text.lower().strip()

    text = re.sub(
        r"\s+",
        "",
        text,
    )

    text = re.sub(
        r"[^\w가-힣]",
        "",
        text,
    )

    text = text.replace(
        "_",
        "",
    )

    return text


def convert_korean_decimal(match) -> str:
    integer_part = match.group(1)
    decimal_part = match.group(2)

    integer_part = re.sub(
        r"\s+",
        "",
        integer_part,
    )

    decimal_part = re.sub(
        r"\s+",
        "",
        decimal_part,
    )

    integer_number = "".join(
        KOREAN_DIGITS.get(
            char,
            char,
        )
        for char in integer_part
    )

    decimal_number = "".join(
        KOREAN_DIGITS.get(
            char,
            char,
        )
        for char in decimal_part
    )

    return (
        f"{integer_number}."
        f"{decimal_number}"
    )


def normalize_semantic(text: str) -> str:
    if text is None:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        str(text),
    )

    text = text.lower().strip()

    digit_pattern = "영공일이삼사오육칠팔구"

    text = re.sub(
        rf"([{digit_pattern}]"
        rf"(?:\s*[{digit_pattern}])*)"
        rf"\s*점\s*"
        rf"([{digit_pattern}]"
        rf"(?:\s*[{digit_pattern}])*)",
        convert_korean_decimal,
        text,
    )

    for source, target in sorted(
        UNIT_REPLACEMENTS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        text = text.replace(
            source,
            target,
        )

    text = re.sub(
        r"\s+",
        "",
        text,
    )

    text = re.sub(
        r"[^\w가-힣]",
        "",
        text,
    )

    text = text.replace(
        "_",
        "",
    )

    return text


def levenshtein_distance(
    reference: str,
    hypothesis: str,
) -> int:
    previous = list(
        range(
            len(hypothesis) + 1
        )
    )

    for i, ref_char in enumerate(
        reference,
        start=1,
    ):
        current = [i]

        for j, hyp_char in enumerate(
            hypothesis,
            start=1,
        ):
            insertion = (
                current[j - 1] + 1
            )

            deletion = (
                previous[j] + 1
            )

            substitution = (
                previous[j - 1]
                + (
                    ref_char
                    != hyp_char
                )
            )

            current.append(
                min(
                    insertion,
                    deletion,
                    substitution,
                )
            )

        previous = current

    return previous[-1]


def calculate_cer(
    reference: str,
    hypothesis: str,
):
    if not reference:
        if not hypothesis:
            return 0.0, 0, 0

        return 1.0, len(hypothesis), 0

    distance = levenshtein_distance(
        reference,
        hypothesis,
    )

    cer = (
        distance
        / len(reference)
    )

    return (
        cer,
        distance,
        len(reference),
    )



NEGATION_PATTERNS = (
    "안 ",
    "못 ",
    "않",
    "아니",
    "없",
    "싫",
)


def detect_semantic_flags(
    reference: str,
    hypothesis: str,
):
    flags = []

    reference_text = str(reference or "")
    hypothesis_text = str(hypothesis or "")

    reference_has_negation = any(
        pattern in reference_text
        for pattern in NEGATION_PATTERNS
    )

    hypothesis_has_negation = any(
        pattern in hypothesis_text
        for pattern in NEGATION_PATTERNS
    )

    if reference_has_negation != hypothesis_has_negation:
        flags.append("negation_mismatch")

    reference_normalized = normalize_semantic(
        reference_text
    )
    hypothesis_normalized = normalize_semantic(
        hypothesis_text
    )

    reference_numbers = set(
        re.findall(
            r"\d+(?:\.\d+)?",
            reference_normalized,
        )
    )

    hypothesis_numbers = set(
        re.findall(
            r"\d+(?:\.\d+)?",
            hypothesis_normalized,
        )
    )

    if reference_numbers != hypothesis_numbers:
        if reference_numbers or hypothesis_numbers:
            flags.append("number_mismatch")

    return flags


class SemanticMatcher:
    def __init__(self):
        if SentenceTransformer is None:
            raise RuntimeError(
                "semantic match를 사용하려면 "
                "'sentence-transformers' 패키지가 필요합니다. "
                "터미널에서 "
                "'pip install sentence-transformers' "
                "를 실행해주세요."
            )

        print()
        print(
            "Semantic Match 모델 로딩: "
            f"{SEMANTIC_MODEL_NAME}"
        )

        self.model = SentenceTransformer(
            SEMANTIC_MODEL_NAME
        )

        print("Semantic Match 모델 로딩 완료")

    def evaluate(
        self,
        reference: str,
        hypothesis: str,
    ):
        reference = str(reference or "").strip()
        hypothesis = str(hypothesis or "").strip()

        if not reference and not hypothesis:
            return {
                "semantic_score": 1.0,
                "semantic_label": "MATCH",
                "semantic_match": True,
                "semantic_flags": "",
                "needs_llm_review": False,
            }

        if not reference or not hypothesis:
            return {
                "semantic_score": 0.0,
                "semantic_label": "MISMATCH",
                "semantic_match": False,
                "semantic_flags": "empty_text",
                "needs_llm_review": True,
            }

        flags = detect_semantic_flags(
            reference,
            hypothesis,
        )

        reference_normalized = normalize_semantic(
            reference
        )
        hypothesis_normalized = normalize_semantic(
            hypothesis
        )

        # 표기 정규화 후 완전히 같으면 임베딩 호출 없이 의미 일치로 처리
        if reference_normalized == hypothesis_normalized:
            return {
                "semantic_score": 1.0,
                "semantic_label": "MATCH",
                "semantic_match": True,
                "semantic_flags": "",
                "needs_llm_review": False,
            }

        embeddings = self.model.encode(
            [
                reference,
                hypothesis,
            ],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        semantic_score = float(
            embeddings[0] @ embeddings[1]
        )

        # 임베딩 점수가 높더라도 부정/숫자 차이는 의미가 크게 바뀔 수 있으므로
        # 자동 MATCH로 확정하지 않고 LLM 검토 대상으로 보낸다.
        if (
            semantic_score
            >= SEMANTIC_MATCH_THRESHOLD
            and not flags
        ):
            label = "MATCH"
            semantic_match = True
            needs_llm_review = False

        elif (
            semantic_score
            < SEMANTIC_REVIEW_THRESHOLD
        ):
            label = "MISMATCH"
            semantic_match = False
            needs_llm_review = True

        else:
            label = "REVIEW"
            semantic_match = False
            needs_llm_review = True

        return {
            "semantic_score": round(
                semantic_score,
                6,
            ),
            "semantic_label": label,
            "semantic_match": semantic_match,
            "semantic_flags": ",".join(flags),
            "needs_llm_review": needs_llm_review,
        }


def backfill_semantic_results(
    results,
    semantic_matcher,
):
    updated = 0

    for row in results.values():
        if not is_success(
            row.get(
                "success",
                False,
            )
        ):
            continue

        existing_score = str(
            row.get(
                "semantic_score",
                "",
            )
        ).strip()

        if existing_score:
            continue

        semantic = semantic_matcher.evaluate(
            row.get(
                "reference_text",
                "",
            ),
            row.get(
                "stt_text",
                "",
            ),
        )

        row.update(semantic)
        updated += 1

    return updated


def export_llm_review_jsonl(results):
    LLM_REVIEW_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    ordered_results = sorted(
        results.values(),
        key=lambda row: (
            int(row.get("age", 0) or 0),
            str(row.get("file_name", "")),
        ),
    )

    with LLM_REVIEW_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        for row in ordered_results:
            payload = {
                "file_name": row.get(
                    "file_name",
                    "",
                ),
                "age": row.get(
                    "age",
                    "",
                ),
                "reference_text": row.get(
                    "reference_text",
                    "",
                ),
                "stt_text": row.get(
                    "stt_text",
                    "",
                ),
                "raw_cer_percent": row.get(
                    "raw_cer_percent",
                    "",
                ),
                "normalized_cer_percent": row.get(
                    "normalized_cer_percent",
                    "",
                ),
                "semantic_score": row.get(
                    "semantic_score",
                    "",
                ),
                "semantic_label": row.get(
                    "semantic_label",
                    "",
                ),
                "semantic_flags": row.get(
                    "semantic_flags",
                    "",
                ),
                "needs_llm_review": row.get(
                    "needs_llm_review",
                    "",
                ),
                "gender": row.get(
                    "gender",
                    "",
                ),
                "school_year": row.get(
                    "school_year",
                    "",
                ),
                "snr_db": row.get(
                    "snr_db",
                    "",
                ),
                "duration_sec": row.get(
                    "duration_sec",
                    "",
                ),
                "noise_environment": row.get(
                    "noise_environment",
                    "",
                ),
                "success": row.get(
                    "success",
                    "",
                ),
                "error": row.get(
                    "error",
                    "",
                ),
            }

            f.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                )
                + "\n"
            )


def parse_snr(value):
    if value is None:
        return ""

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        str(value),
    )

    if not match:
        return ""

    try:
        return float(
            match.group()
        )
    except ValueError:
        return ""


def parse_float(value):
    if value in (
        None,
        "",
        "N/A",
    ):
        return ""

    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return ""


def load_metadata(json_path):
    metadata = {
        "gender": "",
        "school_year": "",
        "dialect": "",
        "snr_db": "",
        "duration_sec": "",
        "recording_environment": "",
        "noise_environment": "",
        "recording_device": "",
        "quality_status": "",
    }

    try:
        path = Path(json_path)

        with path.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        speaker = data.get(
            "Speaker",
            {},
        )

        wav = data.get(
            "Wav",
            {},
        )

        environment = data.get(
            "Environment",
            {},
        )

        file_info = data.get(
            "File",
            {},
        )

        other = data.get(
            "Other",
            {},
        )

        metadata[
            "gender"
        ] = speaker.get(
            "Gender",
            "",
        )

        metadata[
            "school_year"
        ] = speaker.get(
            "SchoolYear",
            "",
        )

        metadata[
            "dialect"
        ] = speaker.get(
            "Dialect",
            "",
        )

        metadata[
            "snr_db"
        ] = parse_snr(
            wav.get(
                "SignalToNoiseRatio"
            )
        )

        metadata[
            "duration_sec"
        ] = parse_float(
            file_info.get(
                "FileLength"
            )
        )

        metadata[
            "recording_environment"
        ] = environment.get(
            "RecordingEnviron",
            "",
        )

        metadata[
            "noise_environment"
        ] = environment.get(
            "NoiseEnviron",
            "",
        )

        metadata[
            "recording_device"
        ] = environment.get(
            "RecordingDevices",
            "",
        )

        metadata[
            "quality_status"
        ] = other.get(
            "QualityStatus",
            "",
        )

    except Exception as e:
        print(
            f"메타데이터 읽기 실패: "
            f"{json_path} / {e}"
        )

    return metadata


def load_manifest():
    if not MANIFEST_FILE.exists():
        raise FileNotFoundError(
            f"Manifest 파일이 없습니다: "
            f"{MANIFEST_FILE}"
        )

    samples = []

    with MANIFEST_FILE.open(
        "r",
        encoding="utf-8-sig",
    ) as f:
        reader = csv.DictReader(f)

        for row in reader:
            samples.append({
                "age": int(
                    row["age"]
                ),
                "wav_name": row[
                    "wav_name"
                ],
                "wav_path": Path(
                    row["wav_path"]
                ),
                "json_path": Path(
                    row["json_path"]
                ),
                "reference": row[
                    "reference"
                ],
            })

    return samples


def is_success(value):
    if isinstance(
        value,
        bool,
    ):
        return value

    return (
        str(value)
        .strip()
        .lower()
        == "true"
    )


def load_existing_results():
    results = {}

    if not OUTPUT_FILE.exists():
        return results

    try:
        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8-sig",
        ) as f:
            reader = csv.DictReader(f)

            for row in reader:
                file_name = row.get(
                    "file_name"
                )

                if file_name:
                    results[
                        file_name
                    ] = row

    except Exception as e:
        print(
            f"기존 결과 읽기 실패: {e}"
        )

    return results


def save_results(results):
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=FIELDNAMES,
        )

        writer.writeheader()

        for result in results.values():
            writer.writerow(result)


def print_age_summary(results):
    stats = defaultdict(
        lambda: {
            "count": 0,
            "raw_distance": 0,
            "raw_chars": 0,
            "norm_distance": 0,
            "norm_chars": 0,
            "norm_cer_sum": 0.0,
            "semantic_count": 0,
            "semantic_score_sum": 0.0,
            "semantic_match_count": 0,
            "semantic_review_count": 0,
            "semantic_mismatch_count": 0,
        }
    )

    for result in results.values():
        if not is_success(
            result.get(
                "success",
                False,
            )
        ):
            continue

        try:
            age = int(
                result["age"]
            )

            raw_distance = int(
                float(
                    result[
                        "raw_edit_distance"
                    ]
                )
            )

            raw_chars = int(
                float(
                    result[
                        "raw_ref_chars"
                    ]
                )
            )

            norm_distance = int(
                float(
                    result[
                        "normalized_edit_distance"
                    ]
                )
            )

            norm_chars = int(
                float(
                    result[
                        "normalized_ref_chars"
                    ]
                )
            )

            norm_cer = float(
                result[
                    "normalized_cer"
                ]
            )

            semantic_score_raw = str(
                result.get(
                    "semantic_score",
                    "",
                )
            ).strip()

            semantic_score = (
                float(semantic_score_raw)
                if semantic_score_raw
                else None
            )

            semantic_label = str(
                result.get(
                    "semantic_label",
                    "",
                )
            ).strip()

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        stats[age][
            "count"
        ] += 1

        stats[age][
            "raw_distance"
        ] += raw_distance

        stats[age][
            "raw_chars"
        ] += raw_chars

        stats[age][
            "norm_distance"
        ] += norm_distance

        stats[age][
            "norm_chars"
        ] += norm_chars

        stats[age][
            "norm_cer_sum"
        ] += norm_cer

        if semantic_score is not None:
            stats[age][
                "semantic_count"
            ] += 1

            stats[age][
                "semantic_score_sum"
            ] += semantic_score

            if semantic_label == "MATCH":
                stats[age][
                    "semantic_match_count"
                ] += 1

            elif semantic_label == "REVIEW":
                stats[age][
                    "semantic_review_count"
                ] += 1

            elif semantic_label == "MISMATCH":
                stats[age][
                    "semantic_mismatch_count"
                ] += 1

    print()
    print("=" * 72)
    print("연령별 CLOVA STT CER")
    print("=" * 72)

    total_raw_distance = 0
    total_raw_chars = 0
    total_norm_distance = 0
    total_norm_chars = 0

    age_norm_cers = []

    for age in TARGET_AGES:
        stat = stats[age]

        if stat["count"] == 0:
            print(
                f"{age}세 | "
                f"성공 데이터 없음"
            )
            continue

        raw_corpus_cer = (
            stat["raw_distance"]
            / stat["raw_chars"]
            if stat["raw_chars"]
            else 0
        )

        norm_corpus_cer = (
            stat["norm_distance"]
            / stat["norm_chars"]
            if stat["norm_chars"]
            else 0
        )

        average_norm_cer = (
            stat["norm_cer_sum"]
            / stat["count"]
        )

        average_semantic_score = (
            stat["semantic_score_sum"]
            / stat["semantic_count"]
            if stat["semantic_count"]
            else 0
        )

        semantic_match_rate = (
            stat["semantic_match_count"]
            / stat["semantic_count"]
            if stat["semantic_count"]
            else 0
        )

        age_norm_cers.append(
            norm_corpus_cer
        )

        print(
            f"{age}세 | "
            f"{stat['count']}개 | "
            f"Raw CER "
            f"{raw_corpus_cer * 100:.2f}% | "
            f"Normalized CER "
            f"{norm_corpus_cer * 100:.2f}% | "
            f"문장 평균 CER "
            f"{average_norm_cer * 100:.2f}% | "
            f"Semantic "
            f"{average_semantic_score:.3f} | "
            f"Match "
            f"{semantic_match_rate * 100:.1f}%"
        )

        if stat["semantic_count"]:
            print(
                f"     Semantic 분류: "
                f"MATCH "
                f"{stat['semantic_match_count']} / "
                f"REVIEW "
                f"{stat['semantic_review_count']} / "
                f"MISMATCH "
                f"{stat['semantic_mismatch_count']}"
            )

        total_raw_distance += (
            stat["raw_distance"]
        )

        total_raw_chars += (
            stat["raw_chars"]
        )

        total_norm_distance += (
            stat["norm_distance"]
        )

        total_norm_chars += (
            stat["norm_chars"]
        )

    print("-" * 72)

    overall_raw_cer = (
        total_raw_distance
        / total_raw_chars
        if total_raw_chars
        else 0
    )

    overall_norm_cer = (
        total_norm_distance
        / total_norm_chars
        if total_norm_chars
        else 0
    )

    macro_norm_cer = (
        sum(age_norm_cers)
        / len(age_norm_cers)
        if age_norm_cers
        else 0
    )

    print(
        f"전체 Corpus Raw CER: "
        f"{overall_raw_cer * 100:.2f}%"
    )

    print(
        f"전체 Corpus Normalized CER: "
        f"{overall_norm_cer * 100:.2f}%"
    )

    print(
        f"연령 Macro Normalized CER: "
        f"{macro_norm_cer * 100:.2f}%"
    )


async def main():
    load_dotenv()

    print("=" * 60)
    print("한국어 아동 음성 CLOVA STT 연령별 평가")
    print("=" * 60)

    samples = load_manifest()

    print(
        f"Manifest 평가 대상: "
        f"{len(samples)}개"
    )

    age_counts = defaultdict(int)

    for sample in samples:
        age_counts[
            sample["age"]
        ] += 1

    print("\n연령별 평가 대상")

    for age in TARGET_AGES:
        print(
            f"{age}세: "
            f"{age_counts[age]}개"
        )

    missing_wav = [
        sample
        for sample in samples
        if not sample[
            "wav_path"
        ].exists()
    ]

    if missing_wav:
        print()
        print(
            f"WAV 파일이 없는 항목: "
            f"{len(missing_wav)}개"
        )

        for sample in missing_wav[:10]:
            print(
                sample["wav_path"]
            )

        return

    existing_results = (
        load_existing_results()
    )

    semantic_matcher = SemanticMatcher()

    backfilled_count = backfill_semantic_results(
        existing_results,
        semantic_matcher,
    )

    if backfilled_count:
        print(
            f"기존 결과 Semantic Match 보완: "
            f"{backfilled_count}개"
        )

        save_results(
            existing_results
        )

    completed_files = {
        file_name
        for file_name, result
        in existing_results.items()
        if is_success(
            result.get(
                "success",
                False,
            )
        )
    }

    print(
        f"\n이미 완료된 파일: "
        f"{len(completed_files)}개"
    )

    remaining_samples = [
        sample
        for sample in samples
        if sample[
            "wav_name"
        ] not in completed_files
    ]

    print(
        f"이번 실행 대상: "
        f"{len(remaining_samples)}개"
    )

    if not remaining_samples:
        print(
            "모든 파일의 평가가 "
            "이미 완료되었습니다."
        )

        print_age_summary(
            existing_results
        )

        export_llm_review_jsonl(
            existing_results
        )

        print(
            f"LLM 검토용 로그: "
            f"{LLM_REVIEW_FILE}"
        )

        return

    stt = ClovaSTT()

    total = len(samples)

    for sample in remaining_samples:
        wav_path = sample[
            "wav_path"
        ]

        wav_name = sample[
            "wav_name"
        ]

        age = sample["age"]

        reference = sample[
            "reference"
        ]

        done_count = sum(
            1
            for result
            in existing_results.values()
            if is_success(
                result.get(
                    "success",
                    False,
                )
            )
        )

        print()
        print("=" * 60)

        print(
            f"[{done_count + 1}/{total}] "
            f"{age}세 | "
            f"{wav_name}"
        )

        print(
            f"정답 : {reference}"
        )

        metadata = load_metadata(
            sample["json_path"]
        )

        try:
            with wav_path.open(
                "rb"
            ) as f:
                audio = f.read()

            start = (
                time.perf_counter()
            )

            result = await stt.transcribe(
                audio
            )

            latency = (
                time.perf_counter()
                - start
            )

            stt_text = (
                result.text
                or ""
            )

            raw_reference = (
                normalize_basic(
                    reference
                )
            )

            raw_stt = (
                normalize_basic(
                    stt_text
                )
            )

            normalized_reference = (
                normalize_semantic(
                    reference
                )
            )

            normalized_stt = (
                normalize_semantic(
                    stt_text
                )
            )

            (
                raw_cer,
                raw_distance,
                raw_ref_chars,
            ) = calculate_cer(
                raw_reference,
                raw_stt,
            )

            (
                normalized_cer,
                normalized_distance,
                normalized_ref_chars,
            ) = calculate_cer(
                normalized_reference,
                normalized_stt,
            )

            semantic = semantic_matcher.evaluate(
                reference,
                stt_text,
            )

            print(
                f"CLOVA: {stt_text}"
            )

            print(
                f"신뢰도: "
                f"{result.confidence}"
            )

            print(
                f"Raw CER: "
                f"{raw_cer * 100:.2f}%"
            )

            print(
                f"Normalized CER: "
                f"{normalized_cer * 100:.2f}%"
            )

            print(
                f"Semantic Score: "
                f"{semantic['semantic_score']:.3f}"
            )

            print(
                f"Semantic Match: "
                f"{semantic['semantic_label']}"
            )

            if semantic["semantic_flags"]:
                print(
                    f"Semantic 경고: "
                    f"{semantic['semantic_flags']}"
                )

            if (
                raw_reference
                != normalized_reference
                or raw_stt
                != normalized_stt
            ):
                print(
                    "정규화:"
                )

                print(
                    f"  정답  -> "
                    f"{normalized_reference}"
                )

                print(
                    f"  CLOVA -> "
                    f"{normalized_stt}"
                )

            print(
                f"처리시간: "
                f"{latency:.2f}초"
            )

            row = {
                "file_name": wav_name,
                "age": age,
                **metadata,
                "reference_text": reference,
                "stt_text": stt_text,
                "raw_reference": raw_reference,
                "raw_stt": raw_stt,
                "normalized_reference": normalized_reference,
                "normalized_stt": normalized_stt,
                "confidence": result.confidence,
                "raw_cer": round(
                    raw_cer,
                    6,
                ),
                "raw_cer_percent": round(
                    raw_cer * 100,
                    2,
                ),
                "normalized_cer": round(
                    normalized_cer,
                    6,
                ),
                "normalized_cer_percent": round(
                    normalized_cer * 100,
                    2,
                ),
                "raw_edit_distance": raw_distance,
                "raw_ref_chars": raw_ref_chars,
                "normalized_edit_distance": (
                    normalized_distance
                ),
                "normalized_ref_chars": (
                    normalized_ref_chars
                ),
                **semantic,
                "latency_sec": round(
                    latency,
                    2,
                ),
                "success": True,
                "error": "",
                "tested_at": (
                    datetime.now()
                    .isoformat(
                        timespec="seconds"
                    )
                ),
            }

            existing_results[
                wav_name
            ] = row

        except Exception as e:
            print(
                f"실패: {e}"
            )

            row = {
                "file_name": wav_name,
                "age": age,
                **metadata,
                "reference_text": reference,
                "stt_text": "",
                "raw_reference": "",
                "raw_stt": "",
                "normalized_reference": "",
                "normalized_stt": "",
                "confidence": "",
                "raw_cer": "",
                "raw_cer_percent": "",
                "normalized_cer": "",
                "normalized_cer_percent": "",
                "raw_edit_distance": "",
                "raw_ref_chars": "",
                "normalized_edit_distance": "",
                "normalized_ref_chars": "",
                "semantic_score": "",
                "semantic_label": "",
                "semantic_match": "",
                "semantic_flags": "",
                "needs_llm_review": True,
                "latency_sec": "",
                "success": False,
                "error": str(e),
                "tested_at": (
                    datetime.now()
                    .isoformat(
                        timespec="seconds"
                    )
                ),
            }

            existing_results[
                wav_name
            ] = row

        save_results(
            existing_results
        )

    print()
    print("=" * 60)
    print("CLOVA STT 평가 완료")
    print("=" * 60)

    successful = [
        result
        for result
        in existing_results.values()
        if is_success(
            result.get(
                "success",
                False,
            )
        )
    ]

    print(
        f"성공: "
        f"{len(successful)}개"
    )

    print(
        f"결과 저장: "
        f"{OUTPUT_FILE}"
    )

    print_age_summary(
        existing_results
    )

    export_llm_review_jsonl(
        existing_results
    )

    print(
        f"LLM 검토용 로그: "
        f"{LLM_REVIEW_FILE}"
    )


if __name__ == "__main__":
    asyncio.run(main())