"""
AI-Hub 「011.한국어 아동 음성 데이터」 Validation / kor_free 로더.

평가 세트(eval_sets/*.csv)에는 파일 이름과 나이만 있다. 데이터는 AI-Hub 이용 약관상
저장소에 올리지 않으므로, 음성 경로와 정답 전사문은 각자 내려받은 원본에서 찾는다.

데이터 위치는 AIHUB_CHILD_SPEECH_ROOT 환경변수로 바꿀 수 있다. 기본값은 저장소 상위 폴더
(~/Desktop/DodamDodam) 이고, 그 아래에 다음 두 폴더가 있어야 한다.

    011.한국어_아동_음성_데이터_원천/01.데이터/2.Validation/원천데이터/kor_free/...
    011.한국어_아동_음성_데이터_라벨링/01.데이터/2.Validation/라벨링데이터/kor_free/...
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path

EVAL_SET_DIR = Path(__file__).resolve().parent / "eval_sets"
DEFAULT_ROOT = Path(__file__).resolve().parents[2]

AUDIO_SUBDIR = Path("011.한국어_아동_음성_데이터_원천/01.데이터/2.Validation/원천데이터")
LABEL_SUBDIR = Path("011.한국어_아동_음성_데이터_라벨링/01.데이터/2.Validation/라벨링데이터")


@dataclass
class Sample:
    wav_name: str
    age: int
    wav_path: Path
    reference: str


def dataset_root() -> Path:
    return Path(os.environ.get("AIHUB_CHILD_SPEECH_ROOT") or DEFAULT_ROOT)


def load_eval_set(name: str, limit_per_age: int | None = None) -> list[Sample]:
    """평가 세트를 읽어 음성 경로와 정답을 붙인다.

    Args:
        name: eval_sets 아래 파일 이름 (age_400, hard_100).
        limit_per_age: 나이별 앞에서 몇 개만 쓸지. None 이면 전부.
    """
    with open(EVAL_SET_DIR / f"{name}.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if limit_per_age is not None:
        taken: dict[str, int] = {}
        picked = []
        for row in rows:
            if taken.get(row["age"], 0) < limit_per_age:
                taken[row["age"]] = taken.get(row["age"], 0) + 1
                picked.append(row)
        rows = picked

    root = dataset_root()
    audio_dir, label_dir = root / AUDIO_SUBDIR, root / LABEL_SUBDIR
    if not audio_dir.is_dir() or not label_dir.is_dir():
        raise FileNotFoundError(
            f"AI-Hub 데이터를 찾을 수 없음: {root}\n"
            "AIHUB_CHILD_SPEECH_ROOT 로 데이터 위치를 지정하세요."
        )

    wanted = {row["wav_name"] for row in rows}
    wav_paths = {p.name: p for p in audio_dir.rglob("*.wav") if p.name in wanted}
    missing = wanted - wav_paths.keys()
    if missing:
        raise FileNotFoundError(f"음성 파일 {len(missing)}개 없음 (예: {sorted(missing)[0]})")

    samples = []
    for row in rows:
        wav_path = wav_paths[row["wav_name"]]
        # 라벨 JSON 은 음성과 같은 하위 경로에 확장자만 다르다.
        label_path = label_dir / wav_path.relative_to(audio_dir).with_suffix(".json")
        with open(label_path, encoding="utf-8") as f:
            reference = json.load(f)["Transcription"]["LabelText"].strip()
        samples.append(
            Sample(
                wav_name=row["wav_name"],
                age=int(row["age"]),
                wav_path=wav_path,
                reference=reference,
            )
        )
    return samples
