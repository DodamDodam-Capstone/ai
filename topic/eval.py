"""P0 평가지표 3개: Category 정확도 · Topic F1(일치율) · 요약 환각률.
보조 지표: Sentiment 정확도 (설계서상 P0 핵심 지표는 아니지만 모델 비교용으로 함께 출력).

정답 파일 형식 (eval_data/eval_set.json, 다른 키는 무시):
[{"session_id": "S001", "topics": [
   {"topic": "자동차", "aliases": ["차", "전기차"], "category": "HOBBY_CREATIVE", "sentiment": "positive",
    "category_alt": "PLAY_GAME"}]}]   # category_alt: 허용 대안 라벨 (선택, 기준서 M2)
환각 라벨 형식 (run_eval.py가 만든 *_halluc.json에 사람이 숫자를 채움, null인 항목은 건너뜀):
[{"session_id": "S001", "topic": "자동차", "claims": 2, "unsupported": 0}]
"""

import json
import re
import sys


def _key(text: str) -> str:
    """띄어쓰기 차이는 같은 표현으로 본다 ('친구와의 다툼' == '친구와의다툼')."""
    return re.sub(r"\s+", "", text)


def match_topics(pred_topics, gold_topics):
    """예측 Topic ↔ 정답 Topic 일대일 대응 (이름 또는 alias 일치). [(pred, gold)] 반환."""
    pairs, used = [], set()
    for p in pred_topics:
        for gi, g in enumerate(gold_topics):
            if gi in used:
                continue
            names = {_key(n) for n in (g["topic"], *g.get("aliases", []))}
            if _key(p["topic"]) in names:
                pairs.append((p, g))
                used.add(gi)
                break
    return pairs


def evaluate(preds: dict, gold: list, halluc: list | None = None):
    n_pred = n_gold = n_match = cat_ok = cat_ok_lenient = sent_ok = sent_n = 0
    n_alt = 0
    alt_pairs = {}
    for g in gold:
        p_topics = preds.get(g["session_id"], [])
        pairs = match_topics(p_topics, g["topics"])
        n_pred += len(p_topics)
        n_gold += len(g["topics"])
        n_match += len(pairs)
        cat_ok += sum(p["category"] == gt["category"] for p, gt in pairs)
        cat_ok_lenient += sum(
            p["category"] in (gt["category"], gt.get("category_alt")) for p, gt in pairs
        )
        for gt in g["topics"]:
            if gt.get("category_alt"):
                n_alt += 1
                k = " / ".join(sorted((gt["category"], gt["category_alt"])))
                alt_pairs[k] = alt_pairs.get(k, 0) + 1
        for p, gt in pairs:
            if "sentiment" in gt:
                sent_n += 1
                sent_ok += p["sentiment"] == gt["sentiment"]

    report = {
        "category_accuracy": (
            round(cat_ok / n_match, 3) if n_match else 0.0
        ),  # 엄격(주 라벨만, 주 지표). 대응된 Topic 기준
        "topic_f1": (
            round(2 * n_match / (n_pred + n_gold), 3) if (n_pred + n_gold) else 0.0
        ),
        "sentiment_accuracy(보조)": round(sent_ok / sent_n, 3) if sent_n else None,
        "matched": n_match,
        "pred": n_pred,
        "gold": n_gold,
    }
    if n_alt:  # 허용 대안이 있을 때만 보조 지표를 붙인다 (M2)
        report["category_accuracy_lenient(보조)"] = (
            round(cat_ok_lenient / n_match, 3) if n_match else 0.0
        )
        report["category_alt_ratio"] = f"{n_alt}/{n_gold} = {n_alt / n_gold:.1%}"
        report["category_alt_pairs"] = dict(
            sorted(alt_pairs.items(), key=lambda x: -x[1])
        )
    labeled = [h for h in (halluc or []) if h.get("claims") is not None]
    if labeled:
        claims = sum(h["claims"] for h in labeled)
        report["hallucination_rate"] = (
            round(sum(h["unsupported"] for h in labeled) / claims, 3) if claims else 0.0
        )
        report["hallucination_labeled"] = f"{len(labeled)}/{len(halluc)}"
    return report


if __name__ == "__main__":
    # 사용 (저장소 루트에서): python -m topic.eval topic/results/eval_xxx.json topic/eval_data/eval_set.json [topic/results/eval_xxx_halluc.json]
    def _load(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    preds = {r["session_id"]: r["topics"] for r in _load(sys.argv[1])}
    gold = _load(sys.argv[2])
    halluc = _load(sys.argv[3]) if len(sys.argv) > 3 else None
    print(json.dumps(evaluate(preds, gold, halluc), ensure_ascii=False, indent=2))
