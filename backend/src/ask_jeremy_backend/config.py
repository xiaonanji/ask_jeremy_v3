from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    person_wiki_root: Path | None = None
    mcp_config_path: Path = Path(__file__).resolve().parents[2] / "mcp.json"
    tool_timeout_seconds: int = 30
    default_database_backend: str = "sqlite"
    sqlite_database_path: Path | None = None
    sql_query_max_rows: int = 1_000
    sql_query_timeout_seconds: int = 30
    snowflake_account: str | None = None
    snowflake_user: str | None = None
    snowflake_role: str | None = None
    snowflake_warehouse: str | None = None
    snowflake_database: str | None = None
    snowflake_schema: str | None = None
    snowflake_authenticator: str = "externalbrowser"
    default_model_provider: str = "openai"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    default_openai_model: str = "gpt-5.4"
    openai_available_models: str | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    default_anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_available_models: str | None = None
    anthropic_max_tokens: int = 1024
    max_history_messages: int = 20
    jeremy_prompt_path: Path | None = None
    system_prompt: str | None = None

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

    @field_validator("default_database_backend")
    @classmethod
    def validate_database_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"sqlite", "snowflake"}:
            raise ValueError(
                "DEFAULT_DATABASE_BACKEND must be either 'sqlite' or 'snowflake'"
            )
        return normalized

    @field_validator("tool_timeout_seconds", "sql_query_max_rows", "sql_query_timeout_seconds")
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Timeouts and row limits must be at least 1.")
        return value

    @property
    def resolved_jeremy_prompt_path(self) -> Path:
        path = self.jeremy_prompt_path or (self.project_root / "jeremy.md")
        if not path.is_absolute():
            path = self.project_root / path
        return path

    @property
    def resolved_system_prompt(self) -> str:
        if self.system_prompt and self.system_prompt.strip():
            return self.system_prompt.strip()

        prompt_path = self.resolved_jeremy_prompt_path
        if not prompt_path.exists():
            raise FileNotFoundError(f"Jeremy prompt not found at {prompt_path}")
        return prompt_path.read_text(encoding="utf-8").strip()

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
