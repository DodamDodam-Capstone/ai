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
from topic.llm_client import MockTopicLLM, QuotaExceededError
from topic.prompt import EXAMPLE_OUTPUT, EXAMPLE_TURNS
from topic.repo_sqlite import SqliteRepo
from topic.schema import Turn
from topic.validator import TopicValidationError, validate

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


def test_evaluate_joint_f1_and_lenient():
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
    assert report["topic_f1(보조)"] == 1.0
    assert report["joint_f1"] == 0.5  # 2 × 1 / (2 + 2): category는 1개만 맞음
    assert report["joint_f1_lenient(보조)"] == 1.0  # 허용 대안 포함
    assert report["category_accuracy(보조)"] == 0.5
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


def _turns(*child_texts: str) -> list[Turn]:
    """아이 발화만 지정해 Turn 목록을 만든다.

    Args:
        *child_texts: 턴 순서대로의 아이 발화.

    Returns:
        turn_id가 1부터 붙은 Turn 목록.
    """
    return [
        Turn(turn_id=i, child_text=c, ai_text="그렇구나.")
        for i, c in enumerate(child_texts, start=1)
    ]


def _one_topic(key_point: str, topic: str = "놀이터") -> dict:
    return {
        "topics": [
            {
                "category": "PLAY_GAME",
                "subtopic": None,
                "topic": topic,
                "sentiment": "positive",
                "key_point": key_point,
                "turn_ids": [1],
            }
        ]
    }


def test_person_name_in_output_is_rejected():
    turns = _turns("오늘 하준이랑 놀이터에서 놀았어. 재밌었어.")
    with pytest.raises(TopicValidationError, match="person name '하준'"):
        validate(_one_topic("하준이와 놀이터에서 놀았다고 말함"), turns)
    validate(_one_topic("친구와 놀이터에서 놀았다고 말함"), turns)


def test_pet_name_and_relation_are_allowed():
    turns = _turns("우리 강아지 보리랑 산책했어. 진짜 좋아.")
    validate(
        _one_topic("강아지 보리와 산책한 것을 좋아한다고 말함", "강아지 산책"), turns
    )
    turns = _turns("엄마랑 동생이랑 놀이터 갔어. 재밌었어.")
    validate(_one_topic("엄마, 동생과 놀이터에서 놀았다고 말함"), turns)


def _topic(name, category, turn_ids):
    return {
        "category": category,
        "subtopic": None,
        "topic": name,
        "sentiment": "unknown",
        "key_point": "-",
        "turn_ids": turn_ids,
    }


def test_matching_name_first_then_turn_iou_one_to_one():
    gold = [
        {
            "session_id": "S001",
            "topics": [
                {
                    "topic": "하늘 색깔",
                    "aliases": ["하늘색"],
                    "category": "KNOWLEDGE_CURIOSITY",
                    "turn_ids": [1, 2, 3],
                },
                {"topic": "피자", "category": "DAILY_LIFE", "turn_ids": [4, 5]},
                {"topic": "고양이", "category": "ANIMAL_NATURE", "turn_ids": [6, 7]},
            ],
        }
    ]
    pred = [
        _topic("하늘의 색", "KNOWLEDGE_CURIOSITY", [1, 2, 3]),  # "의" 정규화로 이름 짝
        _topic("저녁 식사", "DAILY_LIFE", [4, 5]),  # 이름은 다르지만 IoU 1.0
        _topic(
            "하루 이야기", "DAILY_LIFE", [1, 2, 3, 4, 5, 6, 7]
        ),  # 큰 topic: IoU 2/7 < 0.5
    ]
    report = evaluate({"S001": pred}, gold)
    assert report["matched_by_name"] == 1
    assert report["matched_by_turn"] == 1
    assert report["matched"] == 2  # 큰 topic은 고양이와 짝이 되지 않음
    assert report["joint_correct"] == 2


def test_one_prediction_cannot_match_two_gold_topics():
    gold = [
        {
            "session_id": "S001",
            "topics": [
                {"topic": "종이접기", "category": "HOBBY_CREATIVE", "turn_ids": [1, 2]},
                {"topic": "형과의 다툼", "category": "FAMILY", "turn_ids": [2, 3]},
            ],
        }
    ]
    merged = [_topic("방과후", "HOBBY_CREATIVE", [1, 2, 3])]  # 두 정답과 IoU 2/3
    report = evaluate({"S001": merged}, gold)
    assert report["matched"] == 1


def test_name_only_failures_are_saved_with_names_masked():
    repo = SqliteRepo()
    repo.add_turns(
        "S002",
        [
            {
                "turn_id": 1,
                "child_text": "나 오늘 하준이랑 놀이터에서 놀았어.",
                "ai_text": "재밌었겠다!",
            },
            {
                "turn_id": 2,
                "child_text": "그네 탔어. 하준이는 내 친구야.",
                "ai_text": "그렇구나.",
            },
        ],
    )
    leaked = {
        "topics": [
            {
                "category": "PLAY_GAME",
                "subtopic": None,
                "topic": "하준이와 놀이터",
                "sentiment": "unknown",
                "key_point": "하준이랑 놀이터에서 그네를 탔다고 말함",
                "turn_ids": [1, 2],
            }
        ]
    }
    pipeline.process_session_topic("S002", MockTopicLLM(leaked), repo)
    job = repo.get_job("S002")
    assert job["status"] == "done"
    assert job["error"] == "person names masked"
    saved = repo.get_topics("S002")[0]
    assert "하준" not in saved["topic"] + saved["key_point"]
    assert saved["topic"] == "친구와 놀이터"


def test_masking_is_not_used_when_other_errors_remain():
    bad = _mutated(lambda d: d["topics"][0].update(turn_ids=[99]))
    repo, _ = _run(bad)
    assert repo.get_job("S001")["status"] == "failed"


def test_quota_error_stops_without_retry():
    class QuotaLLM:
        calls = 0

        def analyze(self, turns, feedback=None):
            QuotaLLM.calls += 1
            raise QuotaExceededError("429")

    repo = SqliteRepo()
    repo.add_turns("S001", TURNS)
    with pytest.raises(QuotaExceededError):
        pipeline.process_session_topic("S001", QuotaLLM(), repo)
    assert QuotaLLM.calls == 1
    assert repo.get_job("S001")["status"] == "quota"
    assert repo.get_topics("S001") == []
