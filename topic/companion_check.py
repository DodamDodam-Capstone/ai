"""보조 검사: 아이가 함께한 사람을 말한 topic에서 key_point에 그 관계가 남았는지 (기준서 4-4).

사용 (저장소 루트에서):
  python -m topic.companion_check topic/results/<결과>.json [topic/results/<다른 결과>.json ...]

판정:
  - topic의 근거 turn 아동 발화에서 "엄마랑", "친구하고", "아빠와 같이"처럼 동행을 나타내는 표현을 찾는다.
    사람 이름(지우랑 등)도 동행으로 본다. 반려동물 이름은 제외한다.
  - 관계어로 말했으면 key_point에 같은 관계어(또는 같은 뜻의 말)가 있어야 포함으로 본다.
    이름으로 말했으면 key_point에 관계어가 하나라도 있으면 포함으로 본다 (이름은 쓰면 안 되므로).
규칙 기반이라 완전하지 않다. 비율과 함께 놓친 목록을 보고 판단한다.
"""

import json
import re
import sys
from pathlib import Path

from .schema import Turn
from .validator import person_names

ROOT = Path(__file__).parent

# 관계어 → key_point에서 인정할 표현
RELATIONS = {
    "엄마아빠": ["엄마아빠", "부모님", "엄마와 아빠", "엄마, 아빠"],
    "부모님": ["부모님", "엄마아빠", "엄마와 아빠"],
    "할머니": ["할머니"],
    "할아버지": ["할아버지"],
    "엄마": ["엄마", "어머니"],
    "아빠": ["아빠", "아버지"],
    "형": ["형"],
    "누나": ["누나"],
    "언니": ["언니"],
    "오빠": ["오빠"],
    "동생": ["동생"],
    "친구들": ["친구"],
    "친구": ["친구"],
    "짝꿍": ["짝꿍", "짝", "친구"],
    "선생님": ["선생님"],
    "이모": ["이모"],
    "삼촌": ["삼촌"],
    "고모": ["고모"],
    "사촌": ["사촌"],
}
ALL_RELATION_WORDS = sorted(
    {w for ws in RELATIONS.values() for w in ws}, key=len, reverse=True
)
_WITH = r"(?:이랑|랑|하고|와 같이|과 같이|와 함께|과 함께)"
_REL_RE = re.compile(
    rf"(?<![가-힣])({'|'.join(sorted(RELATIONS, key=len, reverse=True))}){_WITH}"
)


def companions(texts: list[str], names: set[str]) -> list[str]:
    """아동 발화에서 동행 표현을 찾는다.

    Args:
        texts: 근거 turn의 아동 발화.
        names: 세션의 사람 이름 후보 (반려동물 제외).

    Returns:
        관계어 또는 "이름:<이름>" 목록.
    """
    found = []
    for text in texts:
        found += _REL_RE.findall(text)
        for name in names:
            if re.search(rf"(?<![가-힣]){name}(?:이)?{_WITH}", text):
                found.append(f"이름:{name}")
    return sorted(set(found))


def check(result_path, gold):
    """결과 파일 하나에서 동행 관계 포함 비율을 계산한다.

    Args:
        result_path: run_eval 결과 파일.
        gold: 평가셋 (대화 원문용).

    Returns:
        (포함 수, 대상 수, 놓친 목록).
    """
    sessions = {s["session_id"]: s for s in gold}
    hit = total = 0
    misses = []
    for r in json.loads(Path(result_path).read_text(encoding="utf-8")):
        s = sessions[r["session_id"]]
        turns = [Turn(**t) for t in s["turns"]]
        by_id = {t.turn_id: t.child_text for t in turns}
        names = person_names(turns)
        for t in r["topics"]:
            comp = companions([by_id.get(i, "") for i in t["turn_ids"]], names)
            if not comp:
                continue
            kp = t["key_point"]
            for c in comp:
                total += 1
                ok = (
                    any(w in kp for w in ALL_RELATION_WORDS)
                    if c.startswith("이름:")
                    else any(w in kp for w in RELATIONS[c])
                )
                hit += ok
                if not ok:
                    misses.append(f"{r['session_id']} {t['topic']} ({c}): {kp}")
    return hit, total, misses


def main():
    """결과 파일들의 동행 관계 포함 비율을 출력한다."""
    gold = json.loads(
        (ROOT / "eval_data" / "eval_set.json").read_text(encoding="utf-8")
    )
    for path in sys.argv[1:]:
        hit, total, misses = check(path, gold)
        rate = f"{hit / total:.0%}" if total else "-"
        print(f"\n{Path(path).name}: {hit}/{total} = {rate}")
        for m in misses:
            print(f"  놓침: {m}")


if __name__ == "__main__":
    main()
