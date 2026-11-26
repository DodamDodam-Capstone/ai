"""평가셋(eval_data/eval_set.json) 전체를 한 모델로 돌리고 점수를 낸다.

사용 (저장소 루트에서):
  python -m topic.run_eval gemini                          # .env의 GEMINI_MODEL
  python -m topic.run_eval gemini gemini-3.5-flash         # 모델 지정
  python -m topic.run_eval ollama qwen3:8b                 # 로컬 Ollama (ollama serve + ollama pull 필요)
옵션:
  --delay 초   세션 사이 대기 (Gemini 무료 한도의 분당 요청 수 제한 대비, gemini 기본 6초)
  --only E01,E05   일부 세션만

결과 (topic/results/, git에 올리지 않음):
  eval_<backend>_<model>_<시각>.json         예측 결과 (eval.py preds 형식 + 상태·소요 시간)
  eval_<backend>_<model>_<시각>_halluc.json  환각 라벨링 양식 (claims·unsupported를 사람이 채움)
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from . import pipeline
from .eval import evaluate, match_topics
from .llm_client import GeminiTopicLLM, OllamaTopicLLM
from .repo_sqlite import SqliteRepo

ROOT = Path(__file__).parent

ap = argparse.ArgumentParser()
ap.add_argument("backend", choices=["gemini", "ollama"])
ap.add_argument("model", nargs="?")
ap.add_argument("--delay", type=float)
ap.add_argument("--only")
args = ap.parse_args()

load_dotenv()
logging.basicConfig(level=logging.WARNING, format="  %(levelname)s %(message)s")

if args.backend == "gemini":
    model = (
        args.model
        or os.environ.get("GEMINI_MODEL")
        or sys.exit(".env의 GEMINI_MODEL 또는 모델명을 지정하세요.")
    )
    llm = GeminiTopicLLM(model)
    delay = 6.0 if args.delay is None else args.delay
else:
    model = args.model or sys.exit(
        "Ollama 모델명을 지정하세요. 예: python -m topic.run_eval ollama qwen3:8b"
    )
    llm = OllamaTopicLLM(model)
    delay = args.delay or 0.0


class TimedLLM:
    """LLM 호출 시간만 잰다 (재시도 사이 대기 시간 제외). 호출별 메타(생각 토큰 등)도 모은다."""

    def __init__(self, inner):
        self.inner, self.seconds, self.metas = inner, 0.0, []

    def analyze(self, turns, feedback=None):
        t0 = time.time()
        try:
            return self.inner.analyze(turns, feedback)
        finally:
            self.seconds += time.time() - t0
            self.metas.append(dict(getattr(self.inner, "last_meta", {}) or {}))


data = json.loads((ROOT / "eval_data" / "eval_set.json").read_text(encoding="utf-8"))
if args.only:
    keep = set(args.only.split(","))
    data = [s for s in data if s["session_id"] in keep]

print(f"{args.backend} / {model} / 세션 {len(data)}개")

# 워밍업: 모델 로딩(Ollama)·첫 연결 시간을 측정에서 빼기 위해 1회 호출하고 결과는 버린다.
from .schema import Turn

t0 = time.time()
try:
    llm.analyze([Turn(turn_id=1, child_text="안녕", ai_text="안녕!")])
except Exception as e:  # noqa: BLE001 - 워밍업 실패는 측정과 무관하므로 무시
    print(f"  워밍업 호출 오류(무시): {type(e).__name__}: {e}")
print(
    f"워밍업(측정 제외): {time.time() - t0:.1f}s, 생각 메타: {getattr(llm, 'last_meta', {})}\n"
)
if delay:
    time.sleep(delay)

records, started_all = [], time.time()
for i, s in enumerate(data):
    sid = s["session_id"]
    repo = SqliteRepo()
    repo.add_turns(sid, s["turns"])
    timed = TimedLLM(llm)
    result = pipeline.process_session_topic(sid, timed, repo)
    elapsed = round(timed.seconds, 1)
    job = repo.get_job(sid)
    topics = result.model_dump(mode="json")["topics"] if result else []
    records.append(
        {
            "session_id": sid,
            "model": model,
            "backend": args.backend,
            **job,
            "elapsed_sec": elapsed,
            "calls": timed.metas,
            "topics": topics,
        }
    )

    # 세션별 한 줄 요약: 정답과 짝지어진 topic은 category·sentiment 일치 여부 표시
    pairs = {id(p): g for p, g in match_topics(topics, s["topics"])}
    shown = []
    for p in topics:
        g = pairs.get(id(p))
        if g is None:
            shown.append(f"{p['topic']}(정답 없음)")
        else:
            c = (
                ""
                if p["category"] == g["category"]
                else f" cat✗:{p['category']}→정답 {g['category']}"
            )
            se = (
                ""
                if p["sentiment"] == g["sentiment"]
                else f" sent✗:{p['sentiment']}→정답 {g['sentiment']}"
            )
            shown.append(f"{p['topic']}{c}{se}" if (c or se) else f"{p['topic']}✓")
    missed = [
        g["topic"] for g in s["topics"] if all(g is not v for v in pairs.values())
    ]
    status = (
        "" if job["status"] == "done" else f" [{job['status']}: {job['error'][:60]}]"
    )
    print(
        f"{sid} {elapsed:5.1f}s{status} | {', '.join(shown) or '(topic 없음)'}"
        + (f" | 놓침: {', '.join(missed)}" if missed else "")
    )

    if delay and i < len(data) - 1:
        time.sleep(delay)

# 저장
out_dir = ROOT / "results"
out_dir.mkdir(exist_ok=True)
stem = f"eval_{args.backend}_{re.sub(r'[^0-9A-Za-z._-]', '-', model)}_{datetime.now():%Y%m%d_%H%M%S}"
pred_path = out_dir / f"{stem}.json"
pred_path.write_text(json.dumps(records, ensure_ascii=False, indent=1))

turn_text = {
    (s["session_id"], t["turn_id"]): t["child_text"] for s in data for t in s["turns"]
}
halluc = [
    {
        "session_id": r["session_id"],
        "topic": t["topic"],
        "key_point": t["key_point"],
        "근거_아동발화": [
            turn_text.get((r["session_id"], tid), "") for tid in t["turn_ids"]
        ],
        "claims": None,
        "unsupported": None,
    }
    for r in records
    for t in r["topics"]
]
halluc_path = out_dir / f"{stem}_halluc.json"
halluc_path.write_text(json.dumps(halluc, ensure_ascii=False, indent=1))

# 점수
preds = {r["session_id"]: r["topics"] for r in records}
report = evaluate(preds, data)
failed = [r["session_id"] for r in records if r["status"] != "done"]
times = [r["elapsed_sec"] for r in records if r["status"] == "done"]
print(f"\n점수: {json.dumps(report, ensure_ascii=False)}")
print(
    f"실패 세션: {failed or '없음'} / 재시도 발생: "
    f"{[r['session_id'] for r in records if r['attempts'] > 1] or '없음'}"
)
if times:
    print(
        f"세션당 평균 {sum(times) / len(times):.1f}s (최대 {max(times):.1f}s, 워밍업 제외, LLM 호출 시간만, "
        f"성공 세션 {len(times)}개 기준) / 전체 경과 {time.time() - started_all:.0f}s"
    )

# 생각 모드 확인: Ollama는 thinking 글자 수, Gemini는 thinking 토큰 수가 0이어야 '꺼짐'
metas = [m for r in records for m in r["calls"]]
think = [m.get("thinking_chars", m.get("thinking_tokens", 0)) or 0 for m in metas]
prompt_tok = [m["prompt_tokens"] for m in metas if m.get("prompt_tokens")]
unit = "자" if args.backend == "ollama" else "토큰"
line = f"생각 모드: 호출 {len(metas)}회 중 생각 출력 있음 {sum(t > 0 for t in think)}회 (합계 {sum(think)}{unit})"
if prompt_tok:
    line += f" / 입력 토큰 최대 {max(prompt_tok)}"
    if args.backend == "ollama" and max(prompt_tok) >= OllamaTopicLLM.NUM_CTX * 0.9:
        line += " ⚠ 문맥 길이 한도에 근접: 프롬프트가 잘렸을 수 있음"
print(line)
print(
    f"저장: {pred_path.relative_to(ROOT)}\n      {halluc_path.relative_to(ROOT)} (환각 라벨링 양식)"
)
