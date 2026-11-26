"""주제 분석 파이프라인 회귀 테스트 (Mock LLM, API 키 불필요).

LLM 출력이 검증 규칙을 어기면 재시도 끝에 실패로 기록되고, 정상 출력은 저장되는지 확인한다.
재시도 때 직전 실패 사유가 다음 호출에 전달되는지, few-shot 예시가 검증을 통과하는지,
평가 지표(엄격·허용 대안)가 기대대로 계산되는지도 함께 본다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from topic import pipeline
from topic.eval import evaluate
from topic.llm_client import MockTopicLLM
from topic.prompt import EXAMPLE_OUTPUT, EXAMPLE_TURNS
from topic.repo_sqlite import SqliteRepo
from topic.schema import Turn
from topic.validator import validate

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
    {"turn_id": 6, "child_text": "응", "ai_text": "공룡도 좋아해?"},
]
GOOD = {
    "topics": [
        {
            "category": "HOBBY_CREATIVE",
            "subtopic": None,
            "topic": "자동차",
            "sentiment": "positive",
            "key_point": "자동차를 좋아하며 직접 만들어 보고 싶다고 말함",
            "turn_ids": [1, 2, 3],
        },
        {
            "category": "FRIENDS_RELATIONSHIP",
            "subtopic": None,
            "topic": "친구와의 다툼",
            "sentiment": "unknown",
            "key_point": "친구와 다툰 경험을 이야기함",
            "turn_ids": [4, 5],
        },
    ]
}


def _mutated(mutate) -> dict:
    """GOOD 출력을 복사해 일부만 바꾼다.

    Args:
        mutate: 복사본을 받아 제자리에서 수정하는 함수.

    Returns:
        수정된 LLM 출력.
    """
    out = copy.deepcopy(GOOD)
    mutate(out)
    return out


SHORT_AGREEMENT_TOPIC = {
    "category": "ANIMAL_NATURE",
    "subtopic": None,
    "topic": "공룡",
    "sentiment": "positive",
    "key_point": "공룡을 좋아함",
    "turn_ids": [6],
}

# (이름, LLM 출력, 실패 사유에 들어 있어야 할 문자열)
INVALID_CASES = [
    (
        "빈 turn_ids",
        _mutated(lambda d: d["topics"][0].update(turn_ids=[])),
        "too_short",
    ),
    (
        "없는 turn_id",
        _mutated(lambda d: d["topics"][0].update(turn_ids=[1, 99])),
        "unknown turn_id 99",
    ),
    (
        "잘못된 category",
        _mutated(lambda d: d["topics"][0].update(category="CARS")),
        "category",
    ),
    (
        "잘못된 sentiment",
        _mutated(lambda d: d["topics"][0].update(sentiment="happy")),
        "sentiment",
    ),
    (
        "subtopic 채움",
        _mutated(lambda d: d["topics"][0].update(subtopic="스포츠카")),
        "subtopic must be null",
    ),
    (
        "짧은 동의→positive",
        _mutated(lambda d: d["topics"].append(dict(SHORT_AGREEMENT_TOPIC))),
        "short agreement",
    ),
    (
        "개인정보",
        _mutated(lambda d: d["topics"][1].update(key_point="햇살초등학교 친구와 다툼")),
        "possible PII",
    ),
]


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    """재시도 사이 대기를 없애 테스트를 빠르게 한다."""
    monkeypatch.setattr(pipeline.time, "sleep", lambda _s: None)


def _run(*outputs: dict) -> tuple[SqliteRepo, MockTopicLLM]:
    """메모리 DB에 TURNS를 넣고 Mock 출력으로 파이프라인을 한 번 돌린다.

    Args:
        *outputs: 호출마다 순서대로 돌려줄 LLM 출력.

    Returns:
        결과가 저장된 저장소와 사용한 Mock LLM.
    """
    repo = SqliteRepo()
    repo.add_turns("S001", TURNS)
    llm = MockTopicLLM(*outputs)
    pipeline.process_session_topic("S001", llm, repo)
    return repo, llm


def test_valid_output_is_saved():
    repo, _ = _run(GOOD)
    job = repo.get_job("S001")
    assert job["status"] == "done"
    assert job["attempts"] == 1
    assert len(repo.get_topics("S001")) == 2


@pytest.mark.parametrize(
    ("name", "output", "reason"), INVALID_CASES, ids=[c[0] for c in INVALID_CASES]
)
def test_invalid_output_fails_after_retries(name, output, reason):
    repo, _ = _run(output)
    job = repo.get_job("S001")
    assert job["status"] == "failed", name
    assert job["attempts"] == 3, name
    assert repo.get_topics("S001") == [], name
    assert reason in job["error"], (name, job["error"])


def test_retry_passes_previous_failure_to_next_call():
    bad = INVALID_CASES[1][1]  # 없는 turn_id
    repo, llm = _run(bad, GOOD)
    job = repo.get_job("S001")
    assert job["status"] == "done"
    assert job["attempts"] == 2
    assert llm.feedbacks[0] is None
    assert "unknown turn_id 99" in llm.feedbacks[1]


def test_few_shot_example_passes_validation():
    validate(EXAMPLE_OUTPUT, [Turn(**t) for t in EXAMPLE_TURNS])


def test_evaluate_strict_and_lenient_category():
    gold = [
        {
            "session_id": "S001",
            "topics": [
                {
                    "topic": "자동차",
                    "aliases": ["차"],
                    "category": "PLAY_GAME",
                    "category_alt": "HOBBY_CREATIVE",
                },
                {
                    "topic": "친구와의 다툼",
                    "aliases": ["친구 다툼"],
                    "category": "FRIENDS_RELATIONSHIP",
                },
            ],
        }
    ]
    halluc = [
        {"session_id": "S001", "topic": "자동차", "claims": 2, "unsupported": 0},
        {"session_id": "S001", "topic": "친구와의 다툼", "claims": 1, "unsupported": 1},
    ]
    report = evaluate({"S001": GOOD["topics"]}, gold, halluc)
    assert report["topic_f1"] == 1.0
    assert report["category_accuracy"] == 0.5  # 주 라벨만
    assert report["category_accuracy_lenient(보조)"] == 1.0  # 허용 대안 포함
    assert report["hallucination_rate"] == round(1 / 3, 3)


def test_eval_set_is_well_formed():
    path = Path(__file__).resolve().parents[1] / "topic" / "eval_data" / "eval_set.json"
    sessions = json.loads(path.read_text(encoding="utf-8"))
    categories = {
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
    }
    ids = [s["session_id"] for s in sessions]
    assert len(ids) == len(set(ids))
    for s in sessions:
        turn_ids = {t["turn_id"] for t in s["turns"]}
        for t in s["topics"]:
            assert t["category"] in categories, (s["session_id"], t["topic"])
            assert t.get("category_alt") in categories | {None}, (
                s["session_id"],
                t["topic"],
            )
            assert set(t["turn_ids"]) <= turn_ids, (s["session_id"], t["topic"])
