"""Topic Analysis 프롬프트. 출력 형식은 response schema로 강제하므로
프롬프트에 JSON Schema를 다시 붙이지 않는다.
RMM(Prospective Reflection)의 추출 프롬프트처럼 입출력 예시 1개를 함께 준다."""

import json

from .schema import Turn

RULES = """역할: 아동과 AI의 한 세션 대화에서 주제 정보를 추출한다.
입력: turn_id가 있는 전체 세션 대화.

분석 요구사항:
1. 아동의 발화를 중심으로 주제가 일관된 대화 구간을 식별한다. 아래 'Topic 추출 기준'을 따른다.
2. 각 구간에 아래 'Category 판정 기준'에 따라 Category 하나를 부여한다.
   (예: 자동차로 놀았다=PLAY_GAME, 자동차를 만들고 싶다=HOBBY_CREATIVE, 전기차는 왜 움직여=KNOWLEDGE_CURIOSITY)
3. Topic 이름은 아래 'Topic 추출 기준'의 이름 짓기 규칙을 따른다. 세부 의미는 key_point에 남긴다.
4. 주제에 대한 태도(sentiment)를 positive, negative, neutral, mixed, unknown 중 하나로 판단한다.
   sentiment는 주제에 대한 평가·선호다. "속상했어" 같은 감정 표현만으로는 판단하지 않는다.
5. key_point는 실제 아동 발화에 근거해 한 문장으로 요약한다.
   - 아이가 함께한 사람을 말했다면 관계를 반드시 넣는다(예: "엄마와 ~했다고 말함", "친구와 ~했다고 말함").
     category를 정할 때 쓰지 않은 동행 정보가 여기에만 남기 때문이다.
   - 사람 이름은 쓰지 않고 관계(친구, 동생, 할머니 등)로 쓴다.
   - topic으로 따로 내지 않은 세부 내용(어려웠던 부분, 먹은 것 등)은 여기에 담는다.
   - AI가 제안하거나 물은 내용만으로는 쓰지 않는다.
6. 근거가 되는 turn_ids를 반드시 1개 이상 포함한다. 아동 발화가 있는 턴만 넣는다.
7. AI 응답만으로 아이의 취향·관심사·태도를 단정하지 않는다.
8. AI가 꺼낸 주제에 아이가 짧은 대답('응', '맞아', '좋아', '몰라')만 했다면 그 주제는 topic으로 만들지 않는다.
   topic 안에 섞인 짧은 동의만으로 sentiment=positive를 확정하지 않는다.
9. neutral(중립적 태도)과 unknown(판단 근거 부족)을 혼동하지 않는다.
10. subtopic은 항상 null로 반환한다.
11. 아이의 이름, 학교, 주소 등 식별 가능한 정보를 topic·key_point에 남기지 않는다.
12. 없는 사실을 만들지 않는다. 의미 있는 주제가 없으면 topics를 빈 배열로 반환한다.

Category 판정 기준
원칙:
- 장소가 아니라 내용으로 판단한다. 학교에서 있었던 일이라도 내용이 친구 관계면 FRIENDS_RELATIONSHIP이다.
- 키워드가 아니라 아이가 말하려는 중심으로 판단한다.
- 함께한 사람(친구·가족)은 category를 정하지 않는다. 그 사람을 다른 사람으로 바꿔도
  이야기가 그대로 성립하면 활동을 기준으로 분류한다.

판정 순서 (위에서부터 처음 해당하는 것 하나):
1. KNOWLEDGE_CURIOSITY: 원리·사실을 궁금해하거나("왜?", "어떻게?") 알고 있는 원리를 이야기한다.
   단, 학교 수업·교육에서 배운 내용을 전하는 것은 7번, 동물·식물·자연에 대해 아는 사실(이름·생김새·특징)은 4번.
2. FRIENDS_RELATIONSHIP / FAMILY: 특정 사람 자체, 그 사람과의 관계, 그 사람에게 일어난 일이 중심이다
   (다툼, 놀림, 우정, 동생이 생김, 생일, 혼남, 그리움, 함께 보낸 시간 자체). 친구·또래는 FRIENDS_RELATIONSHIP, 가족은 FAMILY.
   사람이 함께 등장하기만 한 활동은 해당하지 않는다.
3. HEALTH_BODY: 아프거나 다친 일, 병원, 몸 상태, 수면, 운동(신체 단련, 규칙 있는 스포츠).
4. ANIMAL_NATURE: 동물·식물·자연을 직접 보거나 돌보거나 키운 일, 또는 그것을 좋아하거나 아는 것을 이야기한다.
   눈·모래·물이 놀이 재료일 뿐이거나, 바다·산이 여행 장소일 뿐이면 해당하지 않는다.
5. HOBBY_CREATIVE: 무언가를 만들었거나 만들고 싶다고 말한다(블록·요리·게임 안에서 만든 것 포함).
   그리기·악기·노래·춤 같은 표현 활동, 배우는 예체능도 여기.
6. PLAY_GAME: 장난감·게임·놀이를 하고 즐긴 이야기다(만든 것 없이 노는 것, 캐릭터 이야기 포함).
7. SCHOOL_LEARNING: 공부, 수업, 숙제, 시험, 선생님, 학교에서 배운 교육 내용.
8. DAILY_LIFE: 식사, 하루 일과, 외출·방문·여행, 집안일, 갖고 싶은 것·선물, 용돈, 이사, 내용 없이 영상·책을 봤다는 이야기.
9. OTHER: 내용은 분명한데 1–8 어디에도 맞지 않는다(예: 장래희망). 판단이 애매하다는 이유로 OTHER를 고르지 않는다.

Topic 추출 기준
무엇을 topic으로 뽑나:
- 아이가 그 대상에 대해 자기 말로 내용을 말한 것만 topic이 된다. AI가 꺼낸 주제라도
  아이가 내용을 보탰으면 topic이다.
- 다음은 topic이 아니다: 대화를 끝내는 지나가는 말, 대화의 틀 자체(선생님께 말하기, 계획 세우기 같은
  대화 방식), 대화 전체를 묶는 너무 넓은 이름(학교 생활, 일상, 경험), 함께한 사람만 따로 떼어낸 것,
  대상 없이 감정만 말한 것(감정의 원인이 있으면 원인이 topic).

topic 하나의 범위:
- 중심 대상이나 사건 하나가 topic 하나다. 세부 내용(어려웠던 부분, 들른 곳, 먹은 것, 그 사건 안에서 한 일)은
  별도 topic으로 내지 않고 key_point에 넣는다.
- 같은 대상이 대화 중에 다시 나오면 하나의 topic으로 묶고 turn_ids를 합친다.
- 같은 대상을 두 개 이상의 topic으로 내지 않는다.
- 서로 다른 대상이면 나눈다. 활동과 사람 이야기를 둘 다 충분히 했으면 나눈다.

이름 짓기:
- 2–8자 정도의 짧은 명사구. 문장·설명을 쓰지 않는다.
- 대상이 중심이면 대상 이름, 사건이 중심이면 "대상 + 사건"(예: 동생과의 갈등).
- 방문·여행처럼 상위 사건이 있으면 상위 사건을 이름으로 한다.
- 줄임말·발음이 틀린 말은 표준 표현으로 바꾼다.
- 사람 이름은 쓰지 않고 관계(친구, 동생 등)로 쓴다."""

# few-shot 예시. 평가용 대화(tests/test_topic_pipeline.py의 S001 등)와 겹치지 않게 유지한다.
# 보여주는 규칙: 명시적 선호(positive)·key_point에 동행 관계 / 짧은 동의만 있음(topic 없음) / 명시적 부정 평가(negative) / 감정 표현만 있음(unknown)
EXAMPLE_TURNS = [
    {
        "turn_id": 1,
        "child_text": "나 공룡 진짜 좋아해. 티라노가 제일 멋있어.",
        "ai_text": "티라노사우루스를 좋아하는구나!",
    },
    {
        "turn_id": 2,
        "child_text": "아빠랑 공룡 책도 맨날 봐.",
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
            "key_point": "공룡을 좋아하며 아빠와 공룡 책을 자주 본다고 말함",
            "turn_ids": [1, 2],
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
