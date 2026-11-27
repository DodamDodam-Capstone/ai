"""두 평가 결과를 세션별로 비교한다 (프롬프트 수정 전 → 후).

사용 (저장소 루트에서):
  python -m topic.compare_runs topic/results/<수정 전>.json topic/results/<수정 후>.json

세션마다 정답 topic별로 '짝 맞음 + category 맞음'(✓) / 'category 틀림'(✗) / '못 찾음'(놓침)과
(짝짓기는 eval.match_topics: 이름 우선, 남은 것은 근거 turn IoU 0.5 이상, 1:1)
정답에 없는 topic(초과)을 비교해, 맞게 된 것·틀리게 된 것·여전히 틀린 것을 나눠 보여준다.
"""

import json
import sys
from pathlib import Path

from .eval import evaluate, match_topics

ROOT = Path(__file__).parent


def _load(path):
    """JSON 파일을 읽는다.

    Args:
        path: 파일 경로.

    Returns:
        읽은 객체.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def session_view(pred_topics, gold_topics):
    """한 세션의 정답 대비 상태를 정리한다.

    Args:
        pred_topics: 모델이 낸 topic 목록.
        gold_topics: 정답 topic 목록.

    Returns:
        (정답 topic별 상태 dict, 초과 topic 이름 목록). 상태는 "✓", "✗:<예측 category>", "놓침".
    """
    pairs = match_topics(pred_topics, gold_topics)
    matched_pred = {id(p) for p, _ in pairs}
    status = {g["topic"]: "놓침" for g in gold_topics}
    for p, g in pairs:
        status[g["topic"]] = (
            "✓" if p["category"] == g["category"] else f"✗:{p['category']}"
        )
    extra = [p["topic"] for p in pred_topics if id(p) not in matched_pred]
    return status, extra


def main():
    """두 결과 파일을 비교해 출력한다."""
    before, after = _load(sys.argv[1]), _load(sys.argv[2])
    gold = _load(ROOT / "eval_data" / "eval_set.json")
    pb = {r["session_id"]: r["topics"] for r in before}
    pa = {r["session_id"]: r["topics"] for r in after}

    rb, ra = evaluate(pb, gold), evaluate(pa, gold)
    print("| 지표 | 수정 전 | 수정 후 |\n|---|---|---|")
    for k in [
        "joint_f1",
        "joint_correct",
        "topic_f1(보조)",
        "category_accuracy(보조)",
        "matched",
        "pred",
        "gold",
    ]:
        print(f"| {k} | {rb[k]} | {ra[k]} |")

    fixed, broken, still, extra_changes = [], [], [], []
    for g in gold:
        sid = g["session_id"]
        sb, eb = session_view(pb.get(sid, []), g["topics"])
        sa, ea = session_view(pa.get(sid, []), g["topics"])
        for t in g["topics"]:
            name, want = t["topic"], t["category"]
            b, a = sb[name], sa[name]
            line = f"{sid} {name} (정답 {want}): {b} → {a}"
            if b != "✓" and a == "✓":
                fixed.append(line)
            elif b == "✓" and a != "✓":
                broken.append(line)
            elif a != "✓":
                still.append(line)
        if eb != ea:
            extra_changes.append(f"{sid}: {eb or '-'} → {ea or '-'}")

    for title, rows in [
        ("맞게 된 것", fixed),
        ("틀리게 된 것", broken),
        ("여전히 틀린 것", still),
        ("정답에 없는 topic(초과) 변화", extra_changes),
    ]:
        print(f"\n## {title} ({len(rows)})")
        print("\n".join(f"- {r}" for r in rows) or "- 없음")


if __name__ == "__main__":
    main()
