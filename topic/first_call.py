"""실제 Gemini로 첫 호출. 실행 (저장소 루트에서): python -m topic.first_call
1) .env의 GEMINI_MODEL이 비어 있으면 → 이 키로 쓸 수 있는 Flash 계열 모델 목록만 출력
2) 채워져 있으면 → 설계서 S001 대화를 파이프라인 전체(LLM → 검증 → 재시도 → 저장)로 처리하고
   설계서의 기대 결과와 비교한다.
가짜 대화만 사용한다. 실제 아이 대화를 넣지 않는다."""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

if not os.environ.get("GEMINI_API_KEY"):
    sys.exit(
        ".env 파일의 GEMINI_API_KEY= 뒤에 발급받은 키를 붙여넣고 저장한 뒤 다시 실행하세요."
    )

if not os.environ.get("GEMINI_MODEL"):
    from google import genai

    print(
        "이 키로 쓸 수 있는 Flash 계열 모델 (하나를 골라 .env의 GEMINI_MODEL= 뒤에 넣으세요):"
    )
    for m in genai.Client().models.list():
        name = m.name.removeprefix("models/")
        if "flash" in name and "generateContent" in (m.supported_actions or []):
            print(f"  {name:<40} {m.display_name or ''}")
    sys.exit(0)

from .llm_client import GeminiTopicLLM
from .pipeline import process_session_topic
from .repo_sqlite import SqliteRepo

# 설계서(05 DATA & API)의 입력 예시와 기대 출력
TURNS = [
    {
        "turn_id": 1,
        "child_text": "나 자동차 진짜 좋아해!",
        "ai_text": "어떤 자동차를 좋아해?",
    },
    {"turn_id": 2, "child_text": "빨간 자동차가 제일 멋있어.", "ai_text": "멋있구나!"},
    {
        "turn_id": 3,
        "child_text": "나중에 직접 자동차 만들고 싶어.",
        "ai_text": "어떤 자동차를 만들고 싶어?",
    },
    {"turn_id": 4, "child_text": "오늘 친구랑 싸웠어.", "ai_text": "무슨 일이 있었어?"},
    {
        "turn_id": 5,
        "child_text": "그래서 너무 속상했어.",
        "ai_text": "그랬구나. 더 이야기해줄래?",
    },
]
EXPECTED = [
    ("자동차", "HOBBY_CREATIVE", "positive", [1, 2, 3]),
    ("친구와의 다툼", "FRIENDS_RELATIONSHIP", "unknown", [4, 5]),
]

model = os.environ["GEMINI_MODEL"]
print(f"모델: {model}\n")
repo = SqliteRepo()
repo.add_turns("S001", TURNS)
result = process_session_topic("S001", GeminiTopicLLM(), repo)
job = repo.get_job("S001")
print(f"\n작업 상태: {job}")

# 결과를 results/에 저장. eval.py의 preds 형식(session_id·topics 목록)과 같다.
# 실패한 세션도 topics=[]로 남겨 평가에서 '못 맞힘'으로 집계되게 한다.
record = {
    "session_id": "S001",
    "model": model,
    "created_at": datetime.now().isoformat(timespec="seconds"),
    **job,
    "topics": result.model_dump(mode="json")["topics"] if result else [],
}
out_dir = Path(__file__).with_name("results")
out_dir.mkdir(exist_ok=True)
out_path = out_dir / f"first_call_{model}_{datetime.now():%Y%m%d_%H%M%S}.json"
out_path.write_text(json.dumps([record], ensure_ascii=False, indent=1))
print(f"저장: {out_path.relative_to(Path(__file__).parent)}")

if result is None:
    sys.exit("실패: 위 error를 확인하세요.")

print("\n결과:")
print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=1))

print("\n설계서 기대값과 비교 (topic 이름은 달라도 될 수 있음, 순서대로 대응):")
for i, (topic, cat, sent, tids) in enumerate(EXPECTED):
    if i >= len(result.topics):
        print(f"  [{topic}] 누락")
        continue
    t = result.topics[i]
    mark = lambda ok: "O" if ok else "X"
    print(f"  기대 {topic}/{cat}/{sent}/{tids}")
    print(
        f"  실제 {t.topic}/{t.category.value}/{t.sentiment.value}/{t.turn_ids}  "
        f"category {mark(t.category.value == cat)} sentiment {mark(t.sentiment.value == sent)} "
        f"turn_ids {mark(t.turn_ids == tids)}"
    )
if len(result.topics) > len(EXPECTED):
    print(f"  추가로 {len(result.topics) - len(EXPECTED)}개 topic 추출됨")
