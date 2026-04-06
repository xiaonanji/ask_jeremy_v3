from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Role = Literal["system", "user", "assistant"]
ModelProvider = Literal["openai", "anthropic"]
SkillScope = Literal["project", "user"]


class ChatMessage(BaseModel):
    id: str
    role: Role
    content: str
    created_at: datetime


class SessionMetadata(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    workspace_path: Path
    model_provider: ModelProvider
    model_name: str


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    model_provider: ModelProvider
    model_name: str


class SessionDetail(BaseModel):
    session: SessionMetadata
    messages: list[ChatMessage]


class CreateSessionRequest(BaseModel):
    title: str | None = None
    model_provider: ModelProvider | None = None
    model_name: str | None = None


class CreateSessionResponse(BaseModel):
    session: SessionMetadata
    messages: list[ChatMessage] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class SendMessageResponse(BaseModel):
    session: SessionMetadata
    user_message: ChatMessage
    assistant_message: ChatMessage


class UpdateSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("title must not be empty")
        return normalized


class UpdateSessionModelRequest(BaseModel):
    model_provider: ModelProvider
    model_name: str = Field(min_length=1)


class ModelCatalogEntry(BaseModel):
    provider: ModelProvider
    model_name: str
    label: str


class ModelCatalogResponse(BaseModel):
    default_provider: ModelProvider
    default_model_name: str
    models: list[ModelCatalogEntry]


class SessionModelConfig(BaseModel):
    model_provider: ModelProvider
    model_name: str

    @field_validator("model_name")
    @classmethod
    def normalize_model_name(cls, value: str) -> str:
        return value.strip()


class SessionLogTurn(BaseModel):
    turn_id: str
    model_provider: ModelProvider
    model_name: str
    user_message_id: str
    user_message: str
    user_created_at: datetime
    user_word_count: int
    user_token_estimate: int
    assistant_message_id: str | None = None
    assistant_response: str | None = None
    assistant_created_at: datetime | None = None
    assistant_word_count: int | None = None
    assistant_token_estimate: int | None = None
    response_time_ms: int | None = None
    response_time_seconds: float | None = None


class SessionLog(BaseModel):
    session_id: str
    log_path: Path
    created_at: datetime
    updated_at: datetime
    turns: list[SessionLogTurn]


class SkillSummary(BaseModel):
    id: str
    name: str
    description: str
    scope: SkillScope
    trusted: bool
    path: Path


class SkillCatalogResponse(BaseModel):
    skills: list[SkillSummary]


class SessionSkillsResponse(BaseModel):
    session_id: str
    skills: list[SkillSummary]
