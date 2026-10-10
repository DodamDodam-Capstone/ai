import json
from pathlib import Path
from collections import Counter

LABEL_DIR = Path("../011.한국어_아동_음성_데이터_라벨링")

age_counter = Counter()
error_count = 0

for json_path in LABEL_DIR.rglob("*.json"):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        age = data.get("Speaker", {}).get("Age")

        if age is None:
            age_counter["missing"] += 1
            continue

        age = str(age).strip()

        if age.isdigit():
            age_counter[int(age)] += 1
        else:
            age_counter[age] += 1

    except Exception as e:
        error_count += 1
        print(f"읽기 오류: {json_path} - {e}")

print("\n나이별 데이터 개수")
print("-" * 30)

numeric_ages = sorted(
    age for age in age_counter
    if isinstance(age, int)
)

for age in numeric_ages:
    print(f"{age}세: {age_counter[age]:,}개")

for age, count in age_counter.items():
    if not isinstance(age, int):
        print(f"{age}: {count:,}개")

print("-" * 30)
print(f"전체 JSON: {sum(age_counter.values()):,}개")
print(f"읽기 오류: {error_count:,}개")