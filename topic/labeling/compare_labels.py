"""두 라벨러의 독립 라벨을 비교한다 (기준서 6장 4번, M2).

사용:
  python topic/labeling/compare_labels.py labels_A.csv labels_B.csv [--out compare.md]

topic 짝 맞추기:
  같은 세션 안에서 turn_ids가 가장 많이 겹치는 topic끼리 짝을 짓는다 (Jaccard >= 0.5).
  이름은 사람마다 다르게 쓰므로 짝 맞추기에 쓰지 않고, 짝이 된 뒤 이름이 다르면 aliases 후보로 보여준다.

출력:
  - topic 일치도: 두 라벨러 topic 집합의 F1 (한쪽에만 있는 topic = 불일치)
  - category 일치율과 Cohen's kappa (짝이 된 topic 기준, 참고용: 표본이 작으면 불안정)
  - 불일치 목록: category가 갈린 topic(허용 대안 후보), 한쪽에만 있는 topic, 이름이 다른 topic
  - category가 갈린 쌍의 분포 (M2: 특정 쌍에 몰리면 그 경계를 재검토)
"""

import argparse
import csv
from collections import Counter, defaultdict

CATS = [
    "SCHOOL_LEARNING",
    "FRIENDS_RELATIONSHIP",
    "FAMILY",
    "PLAY_GAME",
    "HOBBY_CREATIVE",
    "ANIMAL_NATURE",
    "DAILY_LIFE",
    "HEALTH_BODY",
    "KNOWLEDGE_CURIOSITY",
    "OTHER",
]


def load(path):
    """CSV → {session_id: [topic dict]}. topic이 빈 줄은 '세션 있음, topic 없음'."""
    by_sess, errors = defaultdict(list), []
    with open(path, encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            sid = (row.get("session_id") or "").strip()
            if not sid:
                continue
            by_sess.setdefault(sid, [])
            topic = (row.get("topic") or "").strip()
            if not topic:
                continue
            cat = (row.get("category") or "").strip()
            if cat not in CATS:
                errors.append(f"{path}:{i} category 값 오류: {cat!r}")
            try:
                turns = {
                    int(x)
                    for x in (row.get("turn_ids") or "").replace(",", " ").split()
                }
            except ValueError:
                turns = set()
            if not turns:
                errors.append(f"{path}:{i} turn_ids 없음 또는 형식 오류 ({topic})")
            by_sess[sid].append(
                {
                    "topic": topic,
                    "category": cat,
                    "turns": turns,
                    "aliases": [
                        a.strip()
                        for a in (row.get("aliases") or "").split("|")
                        if a.strip()
                    ],
                    "media": (row.get("media") or "").strip()
                    in ("1", "true", "True", "y", "Y"),
                    "memo": (row.get("memo") or "").strip(),
                }
            )
    return by_sess, errors


def pair_topics(a_list, b_list, threshold=0.5):
    """turn_ids Jaccard가 큰 순서로 일대일 짝짓기."""
    cands = []
    for i, a in enumerate(a_list):
        for j, b in enumerate(b_list):
            union = a["turns"] | b["turns"]
            jac = len(a["turns"] & b["turns"]) / len(union) if union else 0.0
            if jac >= threshold:
                cands.append((jac, i, j))
    pairs, used_a, used_b = [], set(), set()
    for jac, i, j in sorted(cands, reverse=True):
        if i not in used_a and j not in used_b:
            pairs.append((a_list[i], b_list[j]))
            used_a.add(i)
            used_b.add(j)
    only_a = [a for i, a in enumerate(a_list) if i not in used_a]
    only_b = [b for j, b in enumerate(b_list) if j not in used_b]
    return pairs, only_a, only_b


def cohen_kappa(labels_a, labels_b):
    n = len(labels_a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(labels_a, labels_b)) / n
    ca, cb = Counter(labels_a), Counter(labels_b)
    pe = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def fmt(t):
    return (
        f"{t['topic']} / {t['category']} / turns {sorted(t['turns'])}"
        + (" / media" if t["media"] else "")
        + (f" / 메모: {t['memo']}" if t["memo"] else "")
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    A, err_a = load(args.a)
    B, err_b = load(args.b)
    out = []
    if err_a or err_b:
        out += (
            ["## 입력 오류 (먼저 고칠 것)", ""]
            + [f"- {e}" for e in err_a + err_b]
            + [""]
        )

    sessions = sorted(set(A) | set(B))
    missing = [s for s in sessions if s not in A or s not in B]
    all_pairs, cat_diff, only, name_diff, media_diff = [], [], [], [], []
    n_a = n_b = 0
    for sid in sessions:
        a_list, b_list = A.get(sid, []), B.get(sid, [])
        n_a += len(a_list)
        n_b += len(b_list)
        pairs, only_a, only_b = pair_topics(a_list, b_list)
        for a, b in pairs:
            all_pairs.append((a, b))
            if a["category"] != b["category"]:
                cat_diff.append((sid, a, b))
            if a["topic"].replace(" ", "") != b["topic"].replace(" ", ""):
                name_diff.append((sid, a, b))
            if a["media"] != b["media"]:
                media_diff.append((sid, a, b))
        only += [(sid, "A", t) for t in only_a] + [(sid, "B", t) for t in only_b]

    n_pair = len(all_pairs)
    f1 = 2 * n_pair / (n_a + n_b) if (n_a + n_b) else 0.0
    agree = sum(a["category"] == b["category"] for a, b in all_pairs)
    kappa = cohen_kappa(
        [a["category"] for a, _ in all_pairs], [b["category"] for _, b in all_pairs]
    )
    pair_dist = Counter(
        tuple(sorted((a["category"], b["category"]))) for _, a, b in cat_diff
    )

    out += [
        "## 요약",
        "",
        f"- 세션 {len(sessions)}개"
        + (f" (한쪽에만 있는 세션: {', '.join(missing)})" if missing else ""),
        f"- topic 수: A {n_a}개, B {n_b}개, 짝지어진 topic {n_pair}개",
        f"- **topic 일치도(F1): {f1:.3f}**",
        (
            f"- **category 일치율: {agree}/{n_pair} = {agree / n_pair:.3f}**"
            if n_pair
            else "- category 일치율: -"
        ),
        (
            f"- **Cohen's kappa: {kappa:.3f}** (참고용. 표본이 작으면 불안정, 기준서 M2)"
            if kappa is not None
            else "- kappa: -"
        ),
        f"- category가 갈린 topic 비율: {len(cat_diff)}/{n_pair}"
        + (f" = {len(cat_diff) / n_pair:.1%}" if n_pair else "")
        + " (20~30% 이상이면 category 정의 문제로 보고 M1 재검토)",
        "",
    ]

    out += ["## 1. category가 갈린 topic (허용 대안 후보)", ""]
    out += [f"- **{sid}** A: {fmt(a)}  \n  B: {fmt(b)}" for sid, a, b in cat_diff] or [
        "- 없음"
    ]
    out += ["", "### 갈린 쌍 분포", ""]
    out += [f"- {x} ↔ {y}: {n}건" for (x, y), n in pair_dist.most_common()] or [
        "- 없음"
    ]
    out += [
        "",
        "## 2. 한쪽에만 있는 topic (topic으로 뽑을지 판단이 갈림, 기준서 4-1·4-2)",
        "",
    ]
    out += [f"- **{sid}** {who}만: {fmt(t)}" for sid, who, t in only] or ["- 없음"]
    out += ["", "## 3. 이름이 다른 topic (aliases 후보, 기준서 4-3)", ""]
    out += [
        f"- **{sid}** A: {a['topic']} / B: {b['topic']}" for sid, a, b in name_diff
    ] or ["- 없음"]
    out += ["", "## 4. media 표시가 갈린 topic", ""]
    out += [
        f"- **{sid}** {a['topic']}: A {'O' if a['media'] else 'X'} / B {'O' if b['media'] else 'X'}"
        for sid, a, b in media_diff
    ] or ["- 없음"]

    text = "\n".join(out)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("# 두 라벨러 비교 결과\n\n" + text + "\n")
        print(f"→ {args.out}")
    print(text)


if __name__ == "__main__":
    main()
