"""주제 분석 평가 지표.

주 지표
  - 결합 F1 (joint_f1): topic 짝이 맞고 category(주 라벨)도 맞은 것만 정답으로 센 F1.
    2 × (짝 맞음 ∧ category 맞음) / (예측 topic 수 + 정답 topic 수)
  - 요약 환각률 (hallucination_rate): 사람이 라벨링한 key_point 주장 중 대화에 근거 없는 비율.
보조 지표
  - Topic F1: category와 무관하게 topic 짝만 본 F1.
  - Category 정확도: 짝지어진 topic 중 category가 맞은 비율 (분모가 짝 수에 따라 바뀌므로 보조).
  - 허용 대안(category_alt) 포함 결합 F1, Sentiment 정확도.
  - 이전 방식(띄어쓰기만 무시한 이름·aliases 짝짓기) Topic F1·Category 정확도: 채점 규칙 변경 전후 비교용.

짝짓기 규칙 (2026-11-27 확정, 시험셋 평가 전 고정)
  1. 1:1 짝짓기. 정답 하나에 예측 하나만 짝짓는다. 예측 하나가 정답 여러 개와 짝이 되지 않는다.
  2. 먼저 이름으로 짝짓는다: 예측 topic 이름이 정답 topic 이름 또는 aliases와 정규화 후 같으면 짝.
     정규화: 띄어쓰기 앞의 조사 "의"를 지우고("하늘의 색" → "하늘 색"), 띄어쓰기를 모두 지운다.
  3. 남은 것끼리 근거 turn 겹침으로 짝짓는다: 겹침 = IoU = |예측 turn ∩ 정답 turn| / |예측 turn ∪ 정답 turn|.
     IoU 0.5 이상인 쌍만 후보로 하고, IoU가 큰 순서로 확정한다.
     (대화 전체를 덮는 큰 topic이 아무 정답과나 짝이 되지 않도록 포함 비율이 아니라 IoU를 쓴다.
      0.5는 라벨러 비교 도구 labeling/compare_labels.py와 같은 정의·기준값이다.)
  같은 세션 안에서만 짝짓는다.

실패 세션 처리 (시험셋 평가 전 고정)
  파이프라인 재시도는 최대 3회(pipeline.MAX_ATTEMPTS). 3회 모두 사람 이름 때문에만 실패하면 이름을 가려 저장한다.
  그래도 실패한 세션은 예측 topic이 없는 것으로 채점한다 (그 세션의 정답 topic은 모두 놓침 = 0점).
  실패율은 run_eval이 따로 출력하고 보고서에 따로 적는다.

정답 파일 형식 (eval_data/eval_set.json, 다른 키는 무시):
[{"session_id": "S001", "topics": [
   {"topic": "자동차", "aliases": ["차", "전기차"], "category": "HOBBY_CREATIVE", "sentiment": "positive",
    "turn_ids": [1, 2], "category_alt": "PLAY_GAME"}]}]   # category_alt: 허용 대안 라벨 (선택, 기준서 M2)
환각 라벨 형식 (run_eval.py가 만든 *_halluc.json에 사람이 숫자를 채움, null인 항목은 건너뜀.
판정 기준은 guidelines/환각_판정_기준.md):
[{"session_id": "S001", "topic": "자동차", "claims": 2, "unsupported": 0}]
"""

import json
import re
import sys

IOU_THRESHOLD = 0.5


def _key(text: str) -> str:
    """이름 비교용 정규화: 띄어쓰기 앞 조사 '의' 제거 후 띄어쓰기 제거.

    Args:
        text: topic 이름.

    Returns:
        정규화한 문자열 ("하늘의 색" → "하늘색", "친구와의 다툼" → "친구와다툼").
    """
    return re.sub(r"\s+", "", re.sub(r"의(?=\s)", "", text))


def _iou(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def _name_pairs(pred_topics, gold_topics, key):
    pairs, used = [], set()
    for p in pred_topics:
        for gi, g in enumerate(gold_topics):
            if gi in used:
                continue
            if key(p["topic"]) in {key(n) for n in (g["topic"], *g.get("aliases", []))}:
                pairs.append((p, g))
                used.add(gi)
                break
    return pairs


def match_by_name(pred_topics, gold_topics):
    """이름·aliases만으로 1:1 짝짓기 (정규화 포함).

    Args:
        pred_topics: 모델이 낸 topic 목록.
        gold_topics: 정답 topic 목록.

    Returns:
        [(pred, gold)] 목록.
    """
    return _name_pairs(pred_topics, gold_topics, _key)


def match_topics(pred_topics, gold_topics, threshold: float = IOU_THRESHOLD):
    """1:1 짝짓기: 이름 일치를 먼저 확정하고, 남은 것끼리 근거 turn IoU가 큰 순서로 짝짓는다.

    Args:
        pred_topics: 모델이 낸 topic 목록.
        gold_topics: 정답 topic 목록 (turn_ids가 없으면 이름 짝짓기만 한다).
        threshold: turn 겹침으로 짝지을 최소 IoU.

    Returns:
        [(pred, gold)] 목록.
    """
    pairs = match_by_name(pred_topics, gold_topics)
    used_p = {id(p) for p, _ in pairs}
    used_g = {id(g) for _, g in pairs}
    cands = []
    for i, p in enumerate(pred_topics):
        if id(p) in used_p:
            continue
        for j, g in enumerate(gold_topics):
            if id(g) in used_g or "turn_ids" not in g:
                continue
            iou = _iou(p.get("turn_ids", []), g["turn_ids"])
            if iou >= threshold:
                cands.append((iou, i, j))
    for _value, i, j in sorted(cands, key=lambda c: (-c[0], c[1], c[2])):
        p, g = pred_topics[i], gold_topics[j]
        if id(p) not in used_p and id(g) not in used_g:
            pairs.append((p, g))
            used_p.add(id(p))
            used_g.add(id(g))
    return pairs


def _f1(n_ok: int, n_pred: int, n_gold: int) -> float:
    return round(2 * n_ok / (n_pred + n_gold), 3) if (n_pred + n_gold) else 0.0


def evaluate(preds: dict, gold: list, halluc: list | None = None):
    """평가 지표를 계산한다.

    Args:
        preds: {session_id: 예측 topic 목록}.
        gold: 정답 세션 목록.
        halluc: 사람이 채운 환각 라벨 목록 (선택).

    Returns:
        지표 dict. 주 지표는 joint_f1과 hallucination_rate.
    """
    n_pred = n_gold = n_match = n_match_name = cat_ok = cat_ok_lenient = 0
    old_match = old_cat_ok = sent_ok = sent_n = n_alt = 0
    alt_pairs = {}

    def old_key(t):  # 이전 방식: 띄어쓰기만 무시
        return re.sub(r"\s+", "", t)

    for g in gold:
        p_topics = preds.get(g["session_id"], [])
        n_pred += len(p_topics)
        n_gold += len(g["topics"])

        pairs = match_topics(p_topics, g["topics"])
        n_match += len(pairs)
        n_match_name += len(match_by_name(p_topics, g["topics"]))
        cat_ok += sum(p["category"] == gt["category"] for p, gt in pairs)
        cat_ok_lenient += sum(
            p["category"] in (gt["category"], gt.get("category_alt")) for p, gt in pairs
        )
        for p, gt in pairs:
            if "sentiment" in gt:
                sent_n += 1
                sent_ok += p["sentiment"] == gt["sentiment"]

        old = _name_pairs(p_topics, g["topics"], old_key)
        old_match += len(old)
        old_cat_ok += sum(p["category"] == gt["category"] for p, gt in old)

        for gt in g["topics"]:
            if gt.get("category_alt"):
                n_alt += 1
                k = " / ".join(sorted((gt["category"], gt["category_alt"])))
                alt_pairs[k] = alt_pairs.get(k, 0) + 1

    report = {
        "joint_f1": _f1(cat_ok, n_pred, n_gold),  # 주 지표
        "topic_f1(보조)": _f1(n_match, n_pred, n_gold),
        "category_accuracy(보조)": round(cat_ok / n_match, 3) if n_match else 0.0,
        "sentiment_accuracy(보조)": round(sent_ok / sent_n, 3) if sent_n else None,
        "joint_correct": cat_ok,
        "matched": n_match,
        "matched_by_name": n_match_name,
        "matched_by_turn": n_match - n_match_name,
        "pred": n_pred,
        "gold": n_gold,
        "topic_f1_이전방식": _f1(old_match, n_pred, n_gold),
        "category_accuracy_이전방식": (
            round(old_cat_ok / old_match, 3) if old_match else 0.0
        ),
    }
    if n_alt:  # 허용 대안이 있을 때만 (M2)
        report["joint_f1_lenient(보조)"] = _f1(cat_ok_lenient, n_pred, n_gold)
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
    # 사용 (저장소 루트에서):
    # python -m topic.eval topic/results/eval_xxx.json topic/eval_data/eval_set.json [halluc.json]
    def _load(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    preds = {r["session_id"]: r["topics"] for r in _load(sys.argv[1])}
    gold = _load(sys.argv[2])
    halluc = _load(sys.argv[3]) if len(sys.argv) > 3 else None
    print(json.dumps(evaluate(preds, gold, halluc), ensure_ascii=False, indent=2))
