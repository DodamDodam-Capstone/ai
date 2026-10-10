import csv
from collections import defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "stt_age_100_llama_postprocess.csv"
LOG_FILE = BASE_DIR / "stt_age_100_llama_run.log"
SUMMARY_FILE = BASE_DIR / "stt_age_100_llama_summary.txt"


def str_to_bool(value):
    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
    }


def levenshtein_distance(
    reference: str,
    hypothesis: str,
) -> int:
    previous = list(
        range(len(hypothesis) + 1)
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


def load_results():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"결과 CSV를 찾을 수 없습니다: "
            f"{INPUT_FILE}"
        )

    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f)
        return list(reader)


def make_run_log(rows):
    lines = []

    lines.append("=" * 72)
    lines.append(
        "CLOVA STT + Llama 후처리 상세 평가 로그"
    )
    lines.append("=" * 72)
    lines.append("")

    lines.append(
        f"평가 대상: {len(rows)}개"
    )
    lines.append("")

    for index, row in enumerate(
        rows,
        start=1,
    ):
        file_name = row.get(
            "file_name",
            "",
        )

        age = row.get(
            "age",
            "",
        )

        reference = row.get(
            "reference_text",
            "",
        )

        clova = row.get(
            "clova_text",
            "",
        )

        llama = row.get(
            "llama_text",
            "",
        )

        clova_cer = row.get(
            "clova_cer_percent",
            "",
        )

        llama_cer = row.get(
            "llama_cer_percent",
            "",
        )

        result = row.get(
            "result",
            "",
        )

        exactly_fixed = str_to_bool(
            row.get(
                "exactly_fixed",
                False,
            )
        )

        unnecessary_change = str_to_bool(
            row.get(
                "unnecessary_change",
                False,
            )
        )

        llama_changed = str_to_bool(
            row.get(
                "llama_changed",
                False,
            )
        )

        llama_success = str_to_bool(
            row.get(
                "llama_success",
                True,
            )
        )

        error = row.get(
            "error",
            "",
        )

        lines.append(
            f"[{index}/{len(rows)}] "
            f"{file_name}"
        )

        lines.append(
            f"연령  : {age}세"
        )

        lines.append(
            f"정답  : {reference}"
        )

        lines.append(
            f"CLOVA : {clova}"
        )

        lines.append(
            f"Llama : {llama}"
        )

        if llama_success:
            lines.append(
                f"CER   : "
                f"{clova_cer}%"
                f" → "
                f"{llama_cer}% "
                f"[{result}]"
            )
        else:
            lines.append(
                f"CER   : "
                f"{clova_cer}% "
                f"→ 평가 제외 [ERROR]"
            )

        if exactly_fixed:
            lines.append(
                "판정  : "
                "Llama가 CLOVA 오류를 "
                "정답과 완전히 일치하도록 복구"
            )

        elif unnecessary_change:
            lines.append(
                "판정  : "
                "CLOVA가 원래 맞았지만 "
                "Llama가 불필요하게 수정"
            )

        elif llama_changed:
            lines.append(
                "판정  : "
                "Llama가 CLOVA 문장을 수정"
            )

        else:
            lines.append(
                "판정  : "
                "Llama가 CLOVA 문장을 유지"
            )

        if error:
            lines.append(
                f"오류  : {error}"
            )

        lines.append("")

    return "\n".join(lines)


def calculate_statistics(rows):
    success_rows = [
        row
        for row in rows
        if str_to_bool(
            row.get(
                "llama_success",
                True,
            )
        )
    ]

    error_rows = [
        row
        for row in rows
        if not str_to_bool(
            row.get(
                "llama_success",
                True,
            )
        )
    ]

    improved_count = sum(
        row.get("result") == "IMPROVED"
        for row in success_rows
    )

    same_count = sum(
        row.get("result") == "SAME"
        for row in success_rows
    )

    worse_count = sum(
        row.get("result") == "WORSE"
        for row in success_rows
    )

    changed_count = sum(
        str_to_bool(
            row.get(
                "llama_changed",
                False,
            )
        )
        for row in success_rows
    )

    clova_exact_count = sum(
        str_to_bool(
            row.get(
                "clova_exact_match",
                False,
            )
        )
        for row in success_rows
    )

    llama_exact_count = sum(
        str_to_bool(
            row.get(
                "llama_exact_match",
                False,
            )
        )
        for row in success_rows
    )

    exactly_fixed_count = sum(
        str_to_bool(
            row.get(
                "exactly_fixed",
                False,
            )
        )
        for row in success_rows
    )

    unnecessary_change_count = sum(
        str_to_bool(
            row.get(
                "unnecessary_change",
                False,
            )
        )
        for row in success_rows
    )

    total_clova_distance = 0
    total_llama_distance = 0
    total_ref_chars = 0

    age_stats = defaultdict(
        lambda: {
            "count": 0,
            "clova_distance": 0,
            "llama_distance": 0,
            "ref_chars": 0,
            "improved": 0,
            "same": 0,
            "worse": 0,
        }
    )

    for row in success_rows:
        reference = row.get(
            "normalized_reference",
            "",
        )

        clova = row.get(
            "normalized_clova",
            "",
        )

        llama = row.get(
            "normalized_llama",
            "",
        )

        ref_chars = len(reference)

        clova_distance = (
            levenshtein_distance(
                reference,
                clova,
            )
        )

        llama_distance = (
            levenshtein_distance(
                reference,
                llama,
            )
        )

        total_clova_distance += (
            clova_distance
        )

        total_llama_distance += (
            llama_distance
        )

        total_ref_chars += (
            ref_chars
        )

        age = row.get(
            "age",
            "unknown",
        )

        stat = age_stats[age]

        stat["count"] += 1
        stat["clova_distance"] += (
            clova_distance
        )
        stat["llama_distance"] += (
            llama_distance
        )
        stat["ref_chars"] += (
            ref_chars
        )

        result = row.get(
            "result",
            "",
        )

        if result == "IMPROVED":
            stat["improved"] += 1

        elif result == "SAME":
            stat["same"] += 1

        elif result == "WORSE":
            stat["worse"] += 1

    clova_cer = (
        total_clova_distance
        / total_ref_chars
        if total_ref_chars
        else 0
    )

    llama_cer = (
        total_llama_distance
        / total_ref_chars
        if total_ref_chars
        else 0
    )

    cer_change = (
        clova_cer
        - llama_cer
    )

    unnecessary_change_rate = (
        unnecessary_change_count
        / clova_exact_count
        * 100
        if clova_exact_count
        else 0
    )

    return {
        "total_count": len(rows),
        "success_count": len(
            success_rows
        ),
        "error_count": len(
            error_rows
        ),
        "clova_cer": clova_cer,
        "llama_cer": llama_cer,
        "cer_change": cer_change,
        "improved_count": improved_count,
        "same_count": same_count,
        "worse_count": worse_count,
        "changed_count": changed_count,
        "clova_exact_count": clova_exact_count,
        "llama_exact_count": llama_exact_count,
        "exactly_fixed_count": (
            exactly_fixed_count
        ),
        "unnecessary_change_count": (
            unnecessary_change_count
        ),
        "unnecessary_change_rate": (
            unnecessary_change_rate
        ),
        "age_stats": age_stats,
    }


def make_summary(stats):
    lines = []

    lines.append("=" * 72)
    lines.append(
        "CLOVA STT + Llama 후처리 성능 평가 요약"
    )
    lines.append("=" * 72)
    lines.append("")

    lines.append(
        f"전체 평가 대상: "
        f"{stats['total_count']}개"
    )

    lines.append(
        f"Llama 처리 성공: "
        f"{stats['success_count']}개"
    )

    lines.append(
        f"Llama 처리 오류: "
        f"{stats['error_count']}개"
    )

    lines.append("")
    lines.append("-" * 72)
    lines.append("전체 CER 비교")
    lines.append("-" * 72)

    lines.append(
        f"CLOVA Corpus CER: "
        f"{stats['clova_cer'] * 100:.2f}%"
    )

    lines.append(
        f"Llama 후처리 Corpus CER: "
        f"{stats['llama_cer'] * 100:.2f}%"
    )

    lines.append(
        f"CER 변화: "
        f"{stats['cer_change'] * 100:+.2f}%p"
    )

    lines.append("")

    if stats["cer_change"] > 0:
        lines.append(
            "결과: Llama 후처리 후 "
            "전체 CER가 감소했습니다."
        )

    elif stats["cer_change"] < 0:
        lines.append(
            "결과: Llama 후처리 후 "
            "전체 CER가 증가했습니다."
        )

    else:
        lines.append(
            "결과: Llama 후처리 전후 "
            "CER가 동일합니다."
        )

    lines.append("")
    lines.append("-" * 72)
    lines.append("문장별 결과")
    lines.append("-" * 72)

    lines.append(
        f"IMPROVED: "
        f"{stats['improved_count']}개"
    )

    lines.append(
        f"SAME: "
        f"{stats['same_count']}개"
    )

    lines.append(
        f"WORSE: "
        f"{stats['worse_count']}개"
    )

    lines.append(
        f"Llama가 실제 수정한 문장: "
        f"{stats['changed_count']}개"
    )

    lines.append("")
    lines.append("-" * 72)
    lines.append("정확 일치 / 안정성")
    lines.append("-" * 72)

    lines.append(
        f"CLOVA 정확 일치: "
        f"{stats['clova_exact_count']}개"
    )

    lines.append(
        f"Llama 정확 일치: "
        f"{stats['llama_exact_count']}개"
    )

    lines.append(
        f"Llama가 완전히 복구한 문장: "
        f"{stats['exactly_fixed_count']}개"
    )

    lines.append(
        f"불필요하게 수정한 문장: "
        f"{stats['unnecessary_change_count']}개"
    )

    lines.append(
        f"불필요 수정률: "
        f"{stats['unnecessary_change_rate']:.2f}%"
    )

    lines.append("")
    lines.append("-" * 72)
    lines.append("연령별 결과")
    lines.append("-" * 72)

    def age_sort_key(age):
        try:
            return int(age)
        except ValueError:
            return 999

    for age in sorted(
        stats["age_stats"],
        key=age_sort_key,
    ):
        stat = stats["age_stats"][age]

        ref_chars = stat["ref_chars"]

        clova_cer = (
            stat["clova_distance"]
            / ref_chars
            if ref_chars
            else 0
        )

        llama_cer = (
            stat["llama_distance"]
            / ref_chars
            if ref_chars
            else 0
        )

        lines.append(
            f"{age}세 | "
            f"{stat['count']}개 | "
            f"CLOVA CER "
            f"{clova_cer * 100:.2f}% | "
            f"Llama CER "
            f"{llama_cer * 100:.2f}% | "
            f"IMPROVED "
            f"{stat['improved']} | "
            f"SAME "
            f"{stat['same']} | "
            f"WORSE "
            f"{stat['worse']}"
        )

    lines.append("")
    lines.append("-" * 72)
    lines.append("실험 해석")
    lines.append("-" * 72)

    if stats["cer_change"] > 0:
        lines.append(
            "Llama 기반 텍스트 후처리를 적용했을 때 "
            "CLOVA 단독 결과보다 전체 CER가 감소했습니다."
        )
    else:
        lines.append(
            "Llama 기반 텍스트 후처리가 "
            "CLOVA 단독 결과의 전체 CER를 "
            "개선하지 못했습니다."
        )

    if (
        stats["unnecessary_change_count"]
        > 0
    ):
        lines.append(
            "CLOVA가 이미 정답과 정확히 일치한 문장을 "
            "Llama가 변경한 사례도 확인되었습니다."
        )

        lines.append(
            "따라서 모든 STT 결과에 Llama 후처리를 "
            "일괄 적용하는 방식은 주의가 필요합니다."
        )

    lines.append("")
    lines.append(
        "다음 단계: 동일한 음성 데이터에 Whisper를 적용해 "
        "CLOVA와 STT 자체 성능을 비교합니다."
    )

    return "\n".join(lines)


def main():
    print("=" * 72)
    print("Llama 후처리 결과 정리 시작")
    print("=" * 72)

    rows = load_results()

    print(
        f"결과 CSV 로드: {len(rows)}개"
    )

    run_log = make_run_log(
        rows
    )

    stats = calculate_statistics(
        rows
    )

    summary = make_summary(
        stats
    )

    LOG_FILE.write_text(
        run_log,
        encoding="utf-8",
    )

    SUMMARY_FILE.write_text(
        summary,
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("로그 생성 완료")
    print("=" * 72)

    print(
        f"상세 로그: "
        f"{LOG_FILE}"
    )

    print(
        f"요약 결과: "
        f"{SUMMARY_FILE}"
    )


if __name__ == "__main__":
    main()