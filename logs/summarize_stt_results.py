import csv
from datetime import datetime
from pathlib import Path

INPUT_FILE = Path("logs/stt_child_validation.csv")
OUTPUT_FILE = Path("logs/stt_child_validation_summary.txt")


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


with INPUT_FILE.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

successful = [
    row
    for row in rows
    if str(row.get("success", "")).lower() == "true"
]

failed = [
    row
    for row in rows
    if str(row.get("success", "")).lower() != "true"
]

cer_values = [
    safe_float(row.get("cer"))
    for row in successful
]

cer_values = [
    cer
    for cer in cer_values
    if cer is not None
]

latencies = [
    safe_float(row.get("latency_sec"))
    for row in successful
]

latencies = [
    latency
    for latency in latencies
    if latency is not None
]

avg_cer = (
    sum(cer_values) / len(cer_values)
    if cer_values
    else 0
)

avg_latency = (
    sum(latencies) / len(latencies)
    if latencies
    else 0
)

exact_matches = sum(
    cer == 0
    for cer in cer_values
)

under_5 = sum(
    cer <= 0.05
    for cer in cer_values
)

under_10 = sum(
    cer <= 0.10
    for cer in cer_values
)

over_20 = sum(
    cer > 0.20
    for cer in cer_values
)

summary = f"""
DodamDodam CLOVA STT Evaluation
========================================

Dataset
- AI-Hub 한국어 아동 음성 데이터
- Split: Validation
- Type: kor_free
- 평가 샘플 수: {len(rows)}

Result
- 성공: {len(successful)}
- 실패: {len(failed)}
- 평균 CER: {avg_cer * 100:.2f}%
- 완전 일치: {exact_matches}/{len(cer_values)}
- CER <= 5%: {under_5}/{len(cer_values)}
- CER <= 10%: {under_10}/{len(cer_values)}
- CER > 20%: {over_20}/{len(cer_values)}
- 평균 처리 시간: {avg_latency:.2f} sec

Generated At
- {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Source
- logs/stt_child_validation.csv
""".strip()

OUTPUT_FILE.write_text(
    summary,
    encoding="utf-8"
)

print(summary)
print()
print(f"요약 로그 저장 완료: {OUTPUT_FILE}")