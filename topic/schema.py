"""출력 스키마 정의 (schema_version 1.2).
LLM 구조화 출력용 JSON Schema와 결과 검증에 같은 모델을 재사용한다."""

from enum import Enum

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.2"


class Category(str, Enum):
    SCHOOL_LEARNING = "SCHOOL_LEARNING"
    FRIENDS_RELATIONSHIP = "FRIENDS_RELATIONSHIP"
    FAMILY = "FAMILY"
    PLAY_GAME = "PLAY_GAME"
    HOBBY_CREATIVE = "HOBBY_CREATIVE"
    ANIMAL_NATURE = "ANIMAL_NATURE"
    DAILY_LIFE = "DAILY_LIFE"
    HEALTH_BODY = "HEALTH_BODY"
    KNOWLEDGE_CURIOSITY = "KNOWLEDGE_CURIOSITY"
    OTHER = "OTHER"


class Sentiment(str, Enum):
    positive = "positive"
    negative = "negative"
    neutral = "neutral"
    mixed = "mixed"
    unknown = "unknown"


class TopicItem(BaseModel):
    category: Category
    subtopic: str | None = None  # P0: 항상 null
    topic: str = Field(min_length=1, max_length=30)
    sentiment: Sentiment
    key_point: str = Field(min_length=1, max_length=200)
    turn_ids: list[int] = Field(min_length=1)  # 빈 근거 금지


class LLMTopicOutput(BaseModel):
    """LLM이 반환하는 부분. session_id·schema_version은 서버가 붙인다."""

    topics: list[TopicItem]


class SessionTopics(BaseModel):
    schema_version: str = SCHEMA_VERSION
    session_id: str
    topics: list[TopicItem]


class Turn(BaseModel):
    turn_id: int
    child_text: str = ""
    ai_text: str = ""
