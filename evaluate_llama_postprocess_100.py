import csv
import json
import re
import unicodedata
from pathlib import Path

import ollama


INPUT_FILE = Path("logs/stt_age_100_validation_fresh.csv")
OUTPUT_FILE = Path("logs/stt_age_100_llama_postprocess.csv")

MODEL_NAME = "llama3.1:8b"


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
            return 0.0

        return 1.0

    distance = levenshtein_distance(
        reference,
        hypothesis,
    )

    return (
        distance
        / len(reference)
    )


def check_ollama() -> bool:
    try:
        ollama.list()
        return True

    except Exception as error:
        print("=" * 70)
        print("Ollama 연결 실패")
        print("=" * 70)
        print(error)
        print()
        print("다른 터미널에서 먼저 실행하세요:")
        print("ollama serve")

        return False


def correct_stt_with_llama(
    stt_text: str,
):
    system_prompt = """
너는 한국어 아동 음성 STT 결과를 교정하는 후처리기다.

입력으로 CLOVA STT가 생성한 한국어 문장 하나만 주어진다.

다음 규칙을 반드시 지켜라.

1. 문장만 보고 명백한 음성 인식 오류라고 판단되는 부분만 수정한다.
2. 오류인지 확실하지 않으면 원래 문장을 그대로 유지한다.
3. 입력에 없는 새로운 정보를 추가하지 않는다.
4. 원래 문장의 의미를 바꾸지 않는다.
5. 더 자연스럽게 만들기 위한 의역이나 문장 재작성은 하지 않는다.
6. 이미 정상적인 문장은 그대로 반환한다.
7. 숫자, 고유명사, 조사 등을 근거 없이 변경하지 않는다.
8. 설명, 이유, 분석, 주석은 출력하지 않는다.

반드시 다음 JSON 형식 하나만 출력한다.

{"corrected_text": "교정된 문장"}
""".strip()

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": stt_text,
            },
        ],
        format="json",
        options={
            "temperature": 0,
            "num_predict": 100,
        },
    )

    raw_response = (
        response["message"]["content"]
        .strip()
    )

    try:
        data = json.loads(
            raw_response
        )

        corrected_text = data.get(
            "corrected_text",
            stt_text,
        )

        if not isinstance(
            corrected_text,
            str,
        ):
            corrected_text = stt_text

        corrected_text = (
            corrected_text.strip()
        )

    except (
        json.JSONDecodeError,
        AttributeError,
        TypeError,
    ):
        corrected_text = stt_text

    if not corrected_text:
        corrected_text = stt_text

    return (
        raw_response,
        corrected_text,
    )


def save_results(
    results,
):
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "file_name",
        "age",
        "reference_text",
        "clova_text",
        "llama_text",
        "raw_llama_response",
        "normalized_reference",
        "normalized_clova",
        "normalized_llama",
        "clova_cer_percent",
        "llama_cer_percent",
        "cer_improvement_percent_point",
        "result",
        "llama_changed",
        "clova_exact_match",
        "llama_exact_match",
        "exactly_fixed",
        "unnecessary_change",
        "llama_success",
        "error",
    ]

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        writer.writerows(
            results
        )


def main():
    if not INPUT_FILE.exists():
        print(
            f"입력 파일을 찾을 수 없습니다: "
            f"{INPUT_FILE}"
        )
        return

    if not check_ollama():
        return

    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print("=" * 70)
    print("CLOVA STT + Llama 후처리 평가")
    print("=" * 70)
    print(
        f"평가 대상: {len(rows)}개"
    )
    print(
        f"Llama 모델: {MODEL_NAME}"
    )

    results = []

    total_clova_distance = 0
    total_clova_ref_chars = 0

    paired_clova_distance = 0
    paired_llama_distance = 0
    paired_ref_chars = 0

    improved_count = 0
    same_count = 0
    worse_count = 0

    changed_count = 0

    clova_exact_count = 0
    llama_exact_count = 0

    exactly_fixed_count = 0
    unnecessary_change_count = 0

    success_count = 0
    error_count = 0

    for index, row in enumerate(
        rows,
        start=1,
    ):
        reference_text = (
            row.get(
                "reference_text",
                "",
            )
            .strip()
        )

        clova_text = (
            row.get(
                "stt_text",
                "",
            )
            .strip()
        )

        normalized_reference = (
            normalize_basic(
                reference_text
            )
        )

        normalized_clova = (
            normalize_basic(
                clova_text
            )
        )

        clova_distance = (
            levenshtein_distance(
                normalized_reference,
                normalized_clova,
            )
        )

        clova_cer = calculate_cer(
            normalized_reference,
            normalized_clova,
        )

        ref_chars = len(
            normalized_reference
        )

        total_clova_distance += (
            clova_distance
        )

        total_clova_ref_chars += (
            ref_chars
        )

        raw_llama_response = ""
        llama_text = ""
        error_message = ""
        llama_success = True

        try:
            (
                raw_llama_response,
                llama_text,
            ) = correct_stt_with_llama(
                clova_text
            )

        except Exception as error:
            llama_success = False
            error_count += 1

            error_message = str(
                error
            )

            llama_text = clova_text

        normalized_llama = (
            normalize_basic(
                llama_text
            )
        )

        clova_exact_match = (
            normalized_reference
            == normalized_clova
        )

        if llama_success:
            success_count += 1

            llama_distance = (
                levenshtein_distance(
                    normalized_reference,
                    normalized_llama,
                )
            )

            llama_cer = calculate_cer(
                normalized_reference,
                normalized_llama,
            )

            improvement = (
                clova_cer
                - llama_cer
            )

            llama_changed = (
                normalized_clova
                != normalized_llama
            )

            llama_exact_match = (
                normalized_reference
                == normalized_llama
            )

            exactly_fixed = (
                not clova_exact_match
                and llama_exact_match
            )

            unnecessary_change = (
                clova_exact_match
                and llama_changed
            )

            if llama_cer < clova_cer:
                result_type = "IMPROVED"
                improved_count += 1

            elif llama_cer > clova_cer:
                result_type = "WORSE"
                worse_count += 1

            else:
                result_type = "SAME"
                same_count += 1

            if llama_changed:
                changed_count += 1

            if clova_exact_match:
                clova_exact_count += 1

            if llama_exact_match:
                llama_exact_count += 1

            if exactly_fixed:
                exactly_fixed_count += 1

            if unnecessary_change:
                unnecessary_change_count += 1

            paired_clova_distance += (
                clova_distance
            )

            paired_llama_distance += (
                llama_distance
            )

            paired_ref_chars += (
                ref_chars
            )

            llama_cer_value = round(
                llama_cer * 100,
                2,
            )

            improvement_value = round(
                improvement * 100,
                2,
            )

        else:
            result_type = "ERROR"

            llama_changed = False
            llama_exact_match = False
            exactly_fixed = False
            unnecessary_change = False

            llama_cer_value = ""
            improvement_value = ""

        result = {
            "file_name": row.get(
                "file_name",
                "",
            ),
            "age": row.get(
                "age",
                "",
            ),
            "reference_text": reference_text,
            "clova_text": clova_text,
            "llama_text": llama_text,
            "raw_llama_response": raw_llama_response,
            "normalized_reference": normalized_reference,
            "normalized_clova": normalized_clova,
            "normalized_llama": normalized_llama,
            "clova_cer_percent": round(
                clova_cer * 100,
                2,
            ),
            "llama_cer_percent": llama_cer_value,
            "cer_improvement_percent_point": (
                improvement_value
            ),
            "result": result_type,
            "llama_changed": llama_changed,
            "clova_exact_match": clova_exact_match,
            "llama_exact_match": llama_exact_match,
            "exactly_fixed": exactly_fixed,
            "unnecessary_change": unnecessary_change,
            "llama_success": llama_success,
            "error": error_message,
        }

        results.append(
            result
        )

        save_results(
            results
        )

        print()
        print(
            f"[{index}/{len(rows)}] "
            f"{row.get('file_name', '')}"
        )

        print(
            f"정답  : "
            f"{reference_text}"
        )

        print(
            f"CLOVA : "
            f"{clova_text}"
        )

        print(
            f"Llama : "
            f"{llama_text}"
        )

        if llama_success:
            print(
                f"CER   : "
                f"{clova_cer * 100:.2f}%"
                f" → "
                f"{llama_cer * 100:.2f}%"
                f" [{result_type}]"
            )

            if exactly_fixed:
                print(
                    "판정  : "
                    "Llama가 정답과 완전히 일치하도록 복구"
                )

            if unnecessary_change:
                print(
                    "판정  : "
                    "CLOVA가 원래 맞았지만 Llama가 수정함"
                )

        else:
            print(
                "CER   : "
                f"{clova_cer * 100:.2f}%"
                " → 평가 제외 [ERROR]"
            )

            print(
                f"오류  : "
                f"{error_message}"
            )

    overall_clova_cer = (
        total_clova_distance
        / total_clova_ref_chars
        if total_clova_ref_chars
        else 0
    )

    paired_clova_cer = (
        paired_clova_distance
        / paired_ref_chars
        if paired_ref_chars
        else 0
    )

    overall_llama_cer = (
        paired_llama_distance
        / paired_ref_chars
        if paired_ref_chars
        else 0
    )

    cer_change = (
        paired_clova_cer
        - overall_llama_cer
    )

    unnecessary_change_rate = (
        unnecessary_change_count
        / clova_exact_count
        * 100
        if clova_exact_count
        else 0
    )

    print()
    print("=" * 70)
    print("최종 결과")
    print("=" * 70)

    print(
        f"전체 평가 대상            : "
        f"{len(rows)}개"
    )

    print(
        f"Llama 처리 성공           : "
        f"{success_count}개"
    )

    print(
        f"Llama 처리 오류           : "
        f"{error_count}개"
    )

    print()

    print(
        f"CLOVA 전체 Corpus CER     : "
        f"{overall_clova_cer * 100:.2f}%"
    )

    print(
        f"CLOVA 비교대상 Corpus CER : "
        f"{paired_clova_cer * 100:.2f}%"
    )

    print(
        f"Llama 후처리 Corpus CER   : "
        f"{overall_llama_cer * 100:.2f}%"
    )

    print(
        f"CER 변화                  : "
        f"{cer_change * 100:.2f}%p"
    )

    print()

    print(
        f"개선된 문장               : "
        f"{improved_count}개"
    )

    print(
        f"동일한 문장               : "
        f"{same_count}개"
    )

    print(
        f"악화된 문장               : "
        f"{worse_count}개"
    )

    print(
        f"Llama가 실제 수정한 문장  : "
        f"{changed_count}개"
    )

    print()

    print(
        f"CLOVA 정확 일치           : "
        f"{clova_exact_count}개"
    )

    print(
        f"Llama 정확 일치           : "
        f"{llama_exact_count}개"
    )

    print(
        f"Llama가 완전히 복구       : "
        f"{exactly_fixed_count}개"
    )

    print(
        f"불필요하게 수정           : "
        f"{unnecessary_change_count}개"
    )

    print(
        f"불필요 수정률             : "
        f"{unnecessary_change_rate:.2f}%"
    )

    print()
    print(
        f"결과 저장: "
        f"{OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()