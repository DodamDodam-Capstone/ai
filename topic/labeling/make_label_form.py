"""독립 재라벨링용 빈 양식을 만든다 (기준서 6장 3번).

정답·모델 결과는 넣지 않는다. 대화만 보고 라벨링하기 위함이다.

사용:
  python topic/labeling/make_label_form.py                          # topic/eval_data/eval_set.json 기준
  python topic/labeling/make_label_form.py <다른 세트.json> --out <폴더>

만드는 파일 (--out 폴더, 기본 labeling/):
  conversations.md     세션별 대화 (읽기용)
  label_template.csv   라벨 입력 양식. 라벨러마다 복사해서 채운다 (labels_A.csv, labels_B.csv).

CSV 입력 규칙:
  - topic 하나당 한 줄. 같은 세션에 topic이 여러 개면 session_id를 반복해서 줄을 추가한다.
  - topic이 하나도 없는 세션은 session_id만 두고 나머지를 비운다 (그 줄을 지우지 않는다).
  - turn_ids: 근거 turn 번호를 공백으로 구분 (예: 1 2 5). topic 짝 맞추기에 쓰이므로 반드시 채운다.
  - category: 10개 enum 값 그대로 (예: PLAY_GAME).
  - aliases: 같은 뜻의 다른 이름을 | 로 구분 (예: 하늘 색깔|노을 색).
  - media: 시청·독서·캐릭터 관련이면 1, 아니면 비움.
  - memo: 애매했던 이유 (경계 사례 확인용, 자유롭게).
"""

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["session_id", "topic", "category", "turn_ids", "aliases", "media", "memo"]

ap = argparse.ArgumentParser()
ap.add_argument("data", nargs="?", default=str(ROOT / "eval_data" / "eval_set.json"))
ap.add_argument("--out", default=str(ROOT / "labeling"))
args = ap.parse_args()

sessions = json.loads(Path(args.data).read_text(encoding="utf-8"))
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)

lines = [
    "# 재라벨링용 대화",
    "",
    "기준서(guidelines/category_topic_기준서_v1.md)만 보고 라벨링한다. 정답·모델 결과는 보지 않는다.",
    "",
]
for s in sessions:
    lines += [f"## {s['session_id']}", "", "| turn | 아이 | AI |", "|---|---|---|"]
    for t in s["turns"]:
        child = t.get("child_text", "").replace("|", "\\|")
        ai = t.get("ai_text", "").replace("|", "\\|")
        lines.append(f"| {t['turn_id']} | {child} | {ai} |")
    lines.append("")
(out / "conversations.md").write_text("\n".join(lines), encoding="utf-8")

with open(
    out / "label_template.csv", "w", newline="", encoding="utf-8-sig"
) as f:  # 엑셀 한글 깨짐 방지
    w = csv.writer(f)
    w.writerow(FIELDS)
    for s in sessions:
        w.writerow([s["session_id"]] + [""] * (len(FIELDS) - 1))

print(
    f"{len(sessions)}개 세션 → {out / 'conversations.md'}, {out / 'label_template.csv'}"
)
