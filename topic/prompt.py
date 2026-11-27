"""Topic Analysis 프롬프트. 출력 형식은 response schema로 강제하므로
프롬프트에 JSON Schema를 다시 붙이지 않는다.
RMM(Prospective Reflection)의 추출 프롬프트처럼 입출력 예시 1개를 함께 준다."""

import json

from .schema import Turn

RULES = """역할: 아동과 AI의 한 세션 대화에서 주제 정보를 추출한다.
입력: turn_id가 있는 전체 세션 대화.

분석 요구사항:
1. 아동의 발화를 중심으로 주제가 일관된 대화 구간을 식별한다.
2. 각 구간에 고정 Category 10개 중 하나를 부여한다. 키워드가 아니라 구간의 중심 의도로 판단한다.
   (예: 자동차로 놀았다=PLAY_GAME, 자동차를 만들고 싶다=HOBBY_CREATIVE, 전기차는 왜 움직여=KNOWLEDGE_CURIOSITY)
3. 실제 이야기한 구체적인 Topic을 짧은 명사로 추출하고 동의어를 정규화한다. 세부 의미는 key_point에 남긴다.
4. 주제에 대한 태도(sentiment)를 positive, negative, neutral, mixed, unknown 중 하나로 판단한다.
   sentiment는 주제에 대한 평가·선호다. "속상했어" 같은 감정 표현만으로는 판단하지 않는다.
5. key_point는 실제 아동 발화에 근거해 한 문장으로 요약한다.
6. 근거가 되는 turn_ids를 반드시 1개 이상 포함한다. 아동 발화가 있는 턴만 넣는다.
7. AI 응답만으로 아이의 취향·관심사·태도를 단정하지 않는다.
8. AI 질문에 대한 짧은 동의('응', '맞아')만으로 sentiment=positive나 지속적 선호를 확정하지 않는다.
   다른 아동 발화로 뒷받침되지 않으면 unknown으로 둔다.
9. neutral(중립적 태도)과 unknown(판단 근거 부족)을 혼동하지 않는다.
10. subtopic은 항상 null로 반환한다.
11. 아이의 이름, 학교, 주소 등 식별 가능한 정보를 topic·key_point에 남기지 않는다.
12. 없는 사실을 만들지 않는다. 의미 있는 주제가 없으면 topics를 빈 배열로 반환한다."""

# few-shot 예시. 평가용 대화(tests/test_topic_pipeline.py의 S001 등)와 겹치지 않게 유지한다.
# 보여주는 규칙: 명시적 선호(positive) / 짧은 동의(unknown) / 명시적 부정 평가(negative) / 감정 표현만 있음(unknown)
EXAMPLE_TURNS = [
    {
        "turn_id": 1,
        "child_text": "나 공룡 진짜 좋아해. 티라노가 제일 멋있어.",
        "ai_text": "티라노사우루스를 좋아하는구나!",
    },
    {
        "turn_id": 2,
        "child_text": "공룡 책도 맨날 봐.",
        "ai_text": "책을 자주 보는구나. 축구도 좋아해?",
    },
    {"turn_id": 3, "child_text": "응", "ai_text": "그렇구나! 오늘 저녁은 뭐 먹었어?"},
    {
        "turn_id": 4,
        "child_text": "카레 먹었는데 당근은 진짜 싫어.",
        "ai_text": "당근이 싫었구나.",
    },
    {
        "turn_id": 5,
        "child_text": "그리고 동생이 내 장난감 망가뜨려서 화났어.",
        "ai_text": "그랬구나, 무슨 장난감이었어?",
    },
]
EXAMPLE_OUTPUT = {
    "topics": [
        {
            "category": "ANIMAL_NATURE",
            "subtopic": None,
            "topic": "공룡",
            "sentiment": "positive",
            "key_point": "공룡을 좋아하고 공룡 책을 자주 본다고 말함",
            "turn_ids": [1, 2],
        },
        {
            "category": "HEALTH_BODY",
            "subtopic": None,
            "topic": "축구",
            "sentiment": "unknown",
            "key_point": "AI의 축구 선호 질문에 짧게 동의함",
            "turn_ids": [3],
        },
        {
            "category": "DAILY_LIFE",
            "subtopic": None,
            "topic": "당근",
            "sentiment": "negative",
            "key_point": "저녁으로 카레를 먹었으며 당근은 싫다고 말함",
            "turn_ids": [4],
        },
        {
            "category": "FAMILY",
            "subtopic": None,
            "topic": "동생과의 갈등",
            "sentiment": "unknown",
            "key_point": "동생이 장난감을 망가뜨려 화가 났다고 말함",
            "turn_ids": [5],
        },
    ]
}


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


SYSTEM_PROMPT = (
    RULES
    + "\n\n예시 (형식과 판단 기준 참고용. 예시의 내용을 실제 분석 결과에 옮기지 않는다.)\n"
    + "입력:\n"
    + _dump(EXAMPLE_TURNS)
    + "\n출력:\n"
    + _dump(EXAMPLE_OUTPUT)
)


def build_user_prompt(turns: list[Turn], feedback: str | None = None) -> str:
    """feedback: 직전 시도가 검증에 실패했을 때의 이전 출력과 실패 사유."""
    prompt = "다음 세션 대화를 분석하라.\n" + _dump([t.model_dump() for t in turns])
    if feedback:
        prompt += (
            "\n\n이전 시도의 출력이 검증에서 거부되었다. 아래 사유를 고쳐 전체 결과를 다시 출력하라.\n"
            + feedback
        )
    return prompt
