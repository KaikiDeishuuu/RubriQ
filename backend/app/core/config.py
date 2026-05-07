from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ai_base_url: str = Field(default="https://example-ai-gateway.com/v1", alias="AI_BASE_URL")
    ai_api_key: str = Field(default="your_api_key", alias="AI_API_KEY")
    ai_vision_base_url: str | None = Field(default=None, alias="AI_VISION_BASE_URL")
    ai_vision_api_key: str | None = Field(default=None, alias="AI_VISION_API_KEY")
    ai_grading_base_url: str | None = Field(default=None, alias="AI_GRADING_BASE_URL")
    ai_grading_api_key: str | None = Field(default=None, alias="AI_GRADING_API_KEY")
    ai_vision_model: str = Field(default="gpt-4o", alias="AI_VISION_MODEL")
    ai_grading_model: str = Field(default="gpt-4.1", alias="AI_GRADING_MODEL")
    api_v1_prefix: str = Field(default="/api", alias="API_V1_PREFIX")
    database_url: str = Field(
        default="postgresql+psycopg://grader:grader@localhost:5432/grader",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    storage_dir: Path = Field(default=ROOT_DIR / "storage", alias="STORAGE_DIR")
    max_upload_mb: int = Field(default=25, alias="MAX_UPLOAD_MB")
    render_dpi: int = Field(default=200, alias="RENDER_DPI")
    ai_request_timeout_seconds: float = Field(default=120.0, alias="AI_REQUEST_TIMEOUT_SECONDS")
    ai_max_retries: int = Field(default=2, alias="AI_MAX_RETRIES")
    ai_retry_backoff_seconds: float = Field(default=1.0, alias="AI_RETRY_BACKOFF_SECONDS")
    cors_origins: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    app_name: str = Field(default="QuizOCR Grader", alias="APP_NAME")

    @field_validator("storage_dir", mode="before")
    @classmethod
    def _normalize_storage_dir(cls, value: Path | str) -> Path:
        storage_path = Path(value)
        if storage_path.is_absolute():
            return storage_path
        return (ROOT_DIR / storage_path).resolve()

    @property
    def effective_vision_base_url(self) -> str:
        return (self.ai_vision_base_url or self.ai_base_url).rstrip("/")

    @property
    def effective_vision_api_key(self) -> str:
        return self.ai_vision_api_key or self.ai_api_key

    @property
    def effective_grading_base_url(self) -> str:
        return (self.ai_grading_base_url or self.ai_base_url).rstrip("/")

    @property
    def effective_grading_api_key(self) -> str:
        return self.ai_grading_api_key or self.ai_api_key

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
