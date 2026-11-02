"""
Qwen3-ASR 1.7B 아동 음성 STT 평가.

서비스와 같은 STT 엔진(stt/qwen.py)으로 평가 세트를 돌리고 CER·정확 일치·Semantic 을 낸다.

    .venv/bin/python -m stt_eval.evaluate --set age_400      # 7~10세 각 100개
    .venv/bin/python -m stt_eval.evaluate --set hard_100     # 어려운 문장 100개
    .venv/bin/python -m stt_eval.evaluate --set age_400 --limit-per-age 5   # 빠른 확인

결과는 stt_eval/results/ 에 문장별 CSV 와 요약 TXT 로 남는다. 문장별 CSV 는 한 줄씩
append 하므로 중간에 멈춰도 다시 실행하면 이어서 돈다. 처음부터 다시 돌리려면 CSV 를 지운다.
AI-Hub 정답 전사문은 저장소에 올리지 않으므로 결과 CSV 에 싣지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from stt_eval.dataset import Sample, load_eval_set
from stt_eval.metrics import SemanticMatcher, cer, normalize, normalize_basic

RESULT_DIR = Path(__file__).resolve().parent / "results"
FIELDS = [
    "wav_name",
    "age",
    "hypothesis",
    "raw_cer",
    "normalized_cer",
    "normalized_edit_distance",
    "normalized_ref_chars",
    "exact_match",
    "semantic_score",
    "semantic_label",
    "audio_duration_sec",
    "processing_time_sec",
]


def result_paths(set_name: str, model_tag: str) -> tuple[Path, Path]:
    stem = f"{model_tag}_{set_name}"
    return RESULT_DIR / f"{stem}.csv", RESULT_DIR / f"{stem}_summary.txt"


async def evaluate_one(stt, matcher, sample: Sample) -> dict:
    audio = sample.wav_path.read_bytes()
    start = time.perf_counter()
    result = await stt.transcribe(audio)
    latency = time.perf_counter() - start

    hyp = result.text
    raw, _, _ = cer(normalize_basic(sample.reference), normalize_basic(hyp))
    norm, dist, chars = cer(normalize(sample.reference), normalize(hyp))
    score, label = matcher.evaluate(sample.reference, hyp) if matcher else ("", "")
    return {
        "wav_name": sample.wav_name,
        "age": sample.age,
        "hypothesis": hyp,
        "raw_cer": f"{raw:.6f}",
        "normalized_cer": f"{norm:.6f}",
        "normalized_edit_distance": dist,
        "normalized_ref_chars": chars,
        "exact_match": normalize(sample.reference) == normalize(hyp),
        "semantic_score": score,
        "semantic_label": label,
        "audio_duration_sec": result.raw.get("audio_duration_sec", ""),
        "processing_time_sec": f"{latency:.3f}",
    }


def summarize(rows: list[dict], title: str) -> str:
    def block(label: str, group: list[dict]) -> list[str]:
        n = len(group)
        sent_cer = statistics.mean(float(r["normalized_cer"]) for r in group)
        corpus = sum(int(r["normalized_edit_distance"]) for r in group) / max(
            1, sum(int(r["normalized_ref_chars"]) for r in group)
        )
        exact = sum(str(r["exact_match"]) == "True" for r in group)
        latency = [float(r["processing_time_sec"]) for r in group]
        lines = [
            f"{label} | {n}개",
            f"  Normalized CER  문장 평균 {sent_cer * 100:.2f}% | Corpus {corpus * 100:.2f}%",
            f"  정확 일치       {exact}개 ({exact / n * 100:.1f}%)",
            f"  처리 시간       중간값 {statistics.median(latency):.2f}초 | "
            f"최소 {min(latency):.2f}초 | 최대 {max(latency):.2f}초",
        ]
        labels = Counter(r["semantic_label"] for r in group if r["semantic_label"])
        if labels:
            sem = statistics.mean(float(r["semantic_score"]) for r in group)
            lines.append(
                f"  Semantic        평균 {sem:.3f} | MATCH {labels['MATCH']} / "
                f"REVIEW {labels['REVIEW']} / MISMATCH {labels['MISMATCH']}"
            )
        return lines

    by_age = defaultdict(list)
    for r in rows:
        by_age[int(r["age"])].append(r)

    lines = [title, "=" * len(title), ""]
    lines += block("전체", rows)
    for age in sorted(by_age):
        lines += [""] + block(f"{age}세", by_age[age])
    return "\n".join(lines) + "\n"


async def run_all(stt, matcher, todo, result_csv: Path, write_header: bool) -> None:
    with open(result_csv, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        for i, sample in enumerate(todo, 1):
            row = await evaluate_one(stt, matcher, sample)
            writer.writerow(row)
            f.flush()
            print(
                f"[{i}/{len(todo)}] {sample.age}세 CER {float(row['normalized_cer']) * 100:5.1f}% "
                f"{row['processing_time_sec']}s"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--set", default="age_400", choices=["age_400", "hard_100"])
    parser.add_argument("--limit-per-age", type=int, default=None)
    parser.add_argument("--no-semantic", action="store_true", help="Semantic 평가 생략")
    args = parser.parse_args()

    from stt.qwen import QwenSTT  # 무거운 import 는 실행 시점에

    samples = load_eval_set(args.set, args.limit_per_age)
    stt = QwenSTT()
    model_tag = stt.model_name.split("/")[-1].lower()
    result_csv, summary_txt = result_paths(args.set, model_tag)
    matcher = None if args.no_semantic else SemanticMatcher()

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    done = set()
    if result_csv.exists():
        with open(result_csv, encoding="utf-8") as f:
            done = {r["wav_name"] for r in csv.DictReader(f)}

    todo = [s for s in samples if s.wav_name not in done]
    print(f"{args.set}: 전체 {len(samples)}개, 남은 {len(todo)}개, 모델 {stt.model_name}")
    asyncio.run(run_all(stt, matcher, todo, result_csv, write_header=not done))

    names = {s.wav_name for s in samples}
    with open(result_csv, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["wav_name"] in names]
    title = f"Qwen3-ASR STT 평가: {args.set} ({stt.model_name})"
    summary = summarize(rows, title)
    summary_txt.write_text(summary, encoding="utf-8")
    print("\n" + summary)


if __name__ == "__main__":
    main()
