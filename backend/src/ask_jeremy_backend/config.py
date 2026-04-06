from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SYSTEM_PROMPT = """
You are Ask Jeremy, the foundation assistant for a data analytical agent.
Be concise, collaborative, and explicit about uncertainty.
For now, focus on general conversation and project setup guidance.
Use the provided current date/time in the runtime context for time-sensitive questions.
Do not guess today's date from model memory when the runtime context provides it.

For every user message, first judge whether the request is:
- a simple single-step ask, or
- a multi-step ask that requires multiple actions, checks, or phases to produce a solid response.

If the ask is simple and single-step:
- answer directly
- do not include a plan section unless it genuinely helps clarity

If the ask is multi-step:
- always include a `Plan` section in your response
- the plan must list action items
- every action item must include one of these exact statuses: `not started`, `in progress`, `completed`
- keep the plan compact and practical
- after the plan, provide the actual response content

When you include a plan:
- use flat bullets
- format each item like: `Action item - status`
- only mark an item `completed` if it is already resolved in the current response
- mark an item `in progress` if it is the main work currently being reasoned through
- mark remaining future items `not started`
""".strip()


class Settings(BaseSettings):
    app_name: str = "Ask Jeremy Backend"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173"
    project_root: Path = Path(__file__).resolve().parents[3]
    session_root: Path = Path(__file__).resolve().parents[2] / "data" / "sessions"
    langgraph_checkpoint_path: Path = (
        Path(__file__).resolve().parents[2] / "data" / "langgraph_checkpoints.sqlite"
    )
    project_skill_root: Path = Path(__file__).resolve().parents[3] / ".agents" / "skills"
    user_skill_root: Path = Path.home() / ".agents" / "skills"
    enable_project_skills: bool = True
    enable_user_skills: bool = True
    trust_project_skills: bool = False
    max_auto_activated_skills: int = 3
    default_model_provider: str = "openai"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    default_openai_model: str = "gpt-4o-mini"
    openai_available_models: str | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    default_anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_available_models: str | None = None
    anthropic_max_tokens: int = 1024
    max_history_messages: int = 20
    system_prompt: str = SYSTEM_PROMPT

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("default_model_provider")
    @classmethod
    def validate_model_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"openai", "anthropic"}:
            raise ValueError("DEFAULT_MODEL_PROVIDER must be either 'openai' or 'anthropic'")
        return normalized

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
