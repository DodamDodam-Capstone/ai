"""평가 세트 전체를 한 모델로 돌리고 점수를 낸다.

사용 (저장소 루트에서):
  python -m topic.run_eval gemini gemini-3.5-flash --thinking minimal
  python -m topic.run_eval ollama qwen3:8b                 # 로컬 Ollama (ollama serve + ollama pull 필요)
옵션:
  --data <경로>       평가 세트 (기본 topic/eval_data/eval_set.json). 시험셋은 저장소 밖 경로로 지정
  --out-dir <경로>    결과 폴더 (기본 topic/results/). 시험셋 결과는 저장소 밖으로 지정
  --prompt final|v0   final = 현재 프롬프트(prompt.py), v0 = 처음 프롬프트(prompt_v0.py)
  --resume <결과.json> 중단된 실행을 이어서 한다 (끝난 세션은 건너뛰고 워밍업도 생략)
  --thinking minimal  Gemini thinking 수준 (기준 점수·공정 비교용)
  --delay 초          세션 사이 대기 (gemini 기본 6초)
  --only E01,E05      일부 세션만

동작:
  - 세션이 끝날 때마다 결과 파일을 다시 저장한다. 중간에 멈춰도 끝난 세션은 남는다.
  - 한도 초과(429)를 받으면 재시도하지 않고 그날 실행을 멈춘다. 그 세션은 다음 실행에서 처음부터 다시 한다.
  - 모든 세션이 끝나면 환각 라벨링 양식을 만들고 점수를 출력한다.

결과 (--out-dir, 기본 topic/results/ 는 git에 올리지 않음):
  eval_<backend>_<model>[_think-x][_<세트>]_<prompt>_<시각>.json   세션별 예측 (각 레코드에 git_commit·prompt_sha1)
  같은 이름_meta.json     커밋 해시·프롬프트 해시·데이터 해시·모델·실행 이력
  같은 이름_halluc.json   환각 라벨링 양식 (claims·unsupported·note를 사람이 채움)
"""

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from . import pipeline
from .eval import evaluate, match_topics
from .llm_client import GeminiTopicLLM, OllamaTopicLLM, QuotaExceededError
from .repo_sqlite import SqliteRepo
from .schema import Turn

ROOT = Path(__file__).parent

ap = argparse.ArgumentParser()
ap.add_argument("backend", choices=["gemini", "ollama"])
ap.add_argument("model", nargs="?")
ap.add_argument("--delay", type=float)
ap.add_argument("--only")
ap.add_argument("--data", help="평가 세트 경로 (기본: topic/eval_data/eval_set.json)")
ap.add_argument("--out-dir", help="결과 폴더 (기본: topic/results)")
ap.add_argument("--prompt", choices=["final", "v0"], default="final")
ap.add_argument("--resume", help="이어서 실행할 결과 파일 (.json)")
ap.add_argument(
    "--thinking",
    choices=["minimal", "low", "medium", "high"],
    help="Gemini thinking 수준 (기본: 모델 기본값). 기준 점수·공정 비교에는 minimal",
)
args = ap.parse_args()

load_dotenv()
logging.basicConfig(level=logging.WARNING, format="  %(levelname)s %(message)s")


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _git(*cmd: str) -> str:
    try:
        return subprocess.run(
            ["git", *cmd], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


if args.prompt == "v0":
    from .prompt_v0 import SYSTEM_PROMPT
else:
    from .prompt import SYSTEM_PROMPT

if args.backend == "gemini":
    model = (
        args.model
        or os.environ.get("GEMINI_MODEL")
        or sys.exit(".env의 GEMINI_MODEL 또는 모델명을 지정하세요.")
    )
    llm = GeminiTopicLLM(
        model, thinking_level=args.thinking, system_prompt=SYSTEM_PROMPT
    )
    delay = 6.0 if args.delay is None else args.delay
else:
    model = args.model or sys.exit(
        "Ollama 모델명을 지정하세요. 예: python -m topic.run_eval ollama qwen3:8b"
    )
    llm = OllamaTopicLLM(model, system_prompt=SYSTEM_PROMPT)
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


data_path = Path(args.data) if args.data else ROOT / "eval_data" / "eval_set.json"
data_text = data_path.read_text(encoding="utf-8")
data = json.loads(data_text)
if args.only:
    keep = set(args.only.split(","))
    data = [s for s in data if s["session_id"] in keep]

meta_now = {
    "git_commit": _git("rev-parse", "HEAD"),
    "git_dirty": bool(_git("status", "--porcelain", "--", ".")),
    "prompt": args.prompt,
    "prompt_sha1": _sha1(SYSTEM_PROMPT),
    "data_file": data_path.name,
    "data_sha1": _sha1(data_text),
    "backend": args.backend,
    "model": model,
    "thinking": args.thinking,
}

# 결과 파일 정하기: 새 실행이면 이름을 만들고, 이어 실행이면 기존 파일과 설정이 같은지 확인
if args.resume:
    pred_path = Path(args.resume)
    meta_path = pred_path.with_name(pred_path.stem + "_meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for k in ["prompt_sha1", "data_sha1", "backend", "model", "thinking", "git_commit"]:
        if meta[k] != meta_now[k]:
            sys.exit(
                f"이어 실행 불가: {k}가 다름 (기존 {meta[k]} / 지금 {meta_now[k]})"
            )
    records = json.loads(pred_path.read_text(encoding="utf-8"))
else:
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    def _safe(x):
        return re.sub(r"[^0-9A-Za-z._-]", "-", x)

    think_tag = f"_think-{args.thinking}" if args.thinking else ""
    set_tag = f"_{_safe(data_path.stem)}" if args.data else ""
    stem = (
        f"eval_{args.backend}_{_safe(model)}{think_tag}{set_tag}_{args.prompt}"
        f"_{datetime.now():%Y%m%d_%H%M%S}"
    )
    pred_path = out_dir / f"{stem}.json"
    meta_path = out_dir / f"{stem}_meta.json"
    meta = {**meta_now, "runs": []}
    records = []

done_ids = {r["session_id"] for r in records}
todo = [s for s in data if s["session_id"] not in done_ids]
run_log = {"started": f"{datetime.now():%Y-%m-%d %H:%M:%S}", "calls": 0}
meta["runs"].append(run_log)

print(f"평가 세트: {data_path.name} ({len(data)}세션) / 남은 세션 {len(todo)}개")
print(
    f"{args.backend} / {model} / prompt={args.prompt} ({meta_now['prompt_sha1'][:10]})"
)
print(
    f"커밋 {meta_now['git_commit'][:10]}{' (커밋 안 된 변경 있음)' if meta_now['git_dirty'] else ''}"
)
if meta_now["git_dirty"]:
    print(
        "  ⚠ 작업 트리에 커밋 안 된 변경이 있습니다. 결과를 재현하려면 먼저 커밋하세요."
    )


def save():
    """결과·메타 파일을 다시 쓴다 (세션마다 호출)."""
    pred_path.write_text(json.dumps(records, ensure_ascii=False, indent=1))
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1))


save()

# 워밍업: 모델 로딩(Ollama)·첫 연결 시간을 측정에서 빼기 위해 1회 호출하고 결과는 버린다.
# 이어 실행일 때는 생략한다 (한도 절약).
quota_hit = False
if todo and not args.resume:
    t0 = time.time()
    try:
        llm.analyze([Turn(turn_id=1, child_text="안녕", ai_text="안녕!")])
        run_log["calls"] += 1
    except QuotaExceededError:
        quota_hit = True
    except Exception as e:  # noqa: BLE001 - 워밍업 실패는 측정과 무관하므로 무시
        run_log["calls"] += 1
        print(f"  워밍업 호출 오류(무시): {type(e).__name__}: {e}")
    print(
        f"워밍업(측정 제외): {time.time() - t0:.1f}s, 생각 메타: {getattr(llm, 'last_meta', {})}\n"
    )
    if delay:
        time.sleep(delay)

started_all = time.time()
for i, s in enumerate(todo):
    if quota_hit:
        break
    sid = s["session_id"]
    repo = SqliteRepo()
    repo.add_turns(sid, s["turns"])
    timed = TimedLLM(llm)
    try:
        result = pipeline.process_session_topic(sid, timed, repo)
    except QuotaExceededError:
        run_log["calls"] += len(timed.metas)
        quota_hit = True
        break
    run_log["calls"] += len(timed.metas)
    elapsed = round(timed.seconds, 1)
    job = repo.get_job(sid)
    topics = result.model_dump(mode="json")["topics"] if result else []
    records.append(
        {
            "session_id": sid,
            "model": model,
            "backend": args.backend,
            "prompt": args.prompt,
            "prompt_sha1": meta_now["prompt_sha1"],
            "git_commit": meta_now["git_commit"],
            **job,
            "elapsed_sec": elapsed,
            "calls": timed.metas,
            "topics": topics,
        }
    )
    save()

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
                if p["sentiment"] == g.get("sentiment")
                else f" sent✗:{p['sentiment']}→정답 {g.get('sentiment')}"
            )
            shown.append(f"{p['topic']}{c}{se}" if (c or se) else f"{p['topic']}✓")
    missed = [
        g["topic"] for g in s["topics"] if all(g is not v for v in pairs.values())
    ]
    status = (
        ""
        if job["status"] == "done"
        else f" [{job['status']}: {(job['error'] or '')[:60]}]"
    )
    print(
        f"{sid} {elapsed:5.1f}s{status} | {', '.join(shown) or '(topic 없음)'}"
        + (f" | 놓침: {', '.join(missed)}" if missed else "")
    )
    if delay and i < len(todo) - 1:
        time.sleep(delay)

run_log["ended"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
run_log["quota_hit"] = quota_hit
save()

done_ids = {r["session_id"] for r in records}
remaining = [s["session_id"] for s in data if s["session_id"] not in done_ids]
print(f"\n이번 실행 호출 수: {run_log['calls']} / 완료 {len(done_ids)}/{len(data)}세션")
print(f"저장: {pred_path}\n      {meta_path}")
if remaining:
    if quota_hit:
        print("한도 초과(429)로 멈춤. 재시도하지 않았습니다.")
    print(
        f"남은 세션 {len(remaining)}개. 이어서 실행:\n"
        f"  python -m topic.run_eval {args.backend} {model}"
        + (f" --thinking {args.thinking}" if args.thinking else "")
        + (f" --data {data_path}" if args.data else "")
        + f" --prompt {args.prompt} --resume {pred_path}"
    )
    sys.exit(2 if quota_hit else 0)

# 모두 끝났으면: 환각 라벨링 양식 + 점수
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
        "note": None,  # 근거 없음 유형(H1–H6)과 이유 (guidelines/환각_판정_기준.md)
    }
    for r in records
    for t in r["topics"]
]
halluc_path = pred_path.with_name(pred_path.stem + "_halluc.json")
if not halluc_path.exists():  # 사람이 채우던 양식을 덮어쓰지 않는다
    halluc_path.write_text(json.dumps(halluc, ensure_ascii=False, indent=1))

preds = {r["session_id"]: r["topics"] for r in records}
report = evaluate(preds, data)
failed = [r["session_id"] for r in records if r["status"] != "done"]
times = [r["elapsed_sec"] for r in records if r["status"] == "done"]
print(f"\n점수: {json.dumps(report, ensure_ascii=False)}")
print(
    f"실패율: {len(failed)}/{len(records)} (실패 세션은 예측 없음으로 채점 = 그 세션 정답 topic 모두 놓침)"
)
print(
    f"실패 세션: {failed or '없음'} / 재시도 발생: "
    f"{[r['session_id'] for r in records if r['attempts'] > 1] or '없음'} / 이름 가림: "
    f"{[r['session_id'] for r in records if r.get('error') == 'person names masked'] or '없음'}"
)
if times:
    print(
        f"세션당 평균 {sum(times) / len(times):.1f}s (최대 {max(times):.1f}s, 워밍업 제외, LLM 호출 시간만)"
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
print(f"환각 라벨링 양식: {halluc_path}")
