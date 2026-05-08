from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]
AIRequestProfile = Literal["vision", "grading"]
AIRouteKey = Literal["vision_rubric", "vision_student_extraction", "vision_split_header", "grading", "grading_review"]


@dataclass(frozen=True, slots=True)
class AIModelCandidate:
    profile: AIRequestProfile
    model: str
    base_url: str
    api_key: str


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
    ai_grading_review_enabled: bool = Field(default=False, alias="AI_GRADING_REVIEW_ENABLED")
    ai_grading_review_model: str | None = Field(default=None, alias="AI_GRADING_REVIEW_MODEL")
    ai_grading_review_score_delta_ratio: float = Field(default=0.15, alias="AI_GRADING_REVIEW_SCORE_DELTA_RATIO")
    ai_grading_review_variance_min_answers: int = Field(default=3, alias="AI_GRADING_REVIEW_VARIANCE_MIN_ANSWERS")
    ai_grading_review_variance_range_ratio: float = Field(default=0.45, alias="AI_GRADING_REVIEW_VARIANCE_RANGE_RATIO")
    ai_grading_strictness: str = Field(default="moderate", alias="AI_GRADING_STRICTNESS")
    ai_grading_concurrency: int = Field(default=4, alias="AI_GRADING_CONCURRENCY")
    ai_grading_global_concurrency: int = Field(default=4, alias="AI_GRADING_GLOBAL_CONCURRENCY")
    ai_vision_chain: str | None = Field(default=None, alias="AI_VISION_CHAIN")
    ai_vision_rubric_chain: str | None = Field(default=None, alias="AI_VISION_RUBRIC_CHAIN")
    ai_vision_student_extraction_chain: str | None = Field(default=None, alias="AI_VISION_STUDENT_EXTRACTION_CHAIN")
    ai_vision_split_header_chain: str | None = Field(default=None, alias="AI_VISION_SPLIT_HEADER_CHAIN")
    ai_grading_chain: str | None = Field(default=None, alias="AI_GRADING_CHAIN")
    ai_grading_review_chain: str | None = Field(default=None, alias="AI_GRADING_REVIEW_CHAIN")

    @field_validator("ai_grading_strictness")
    @classmethod
    def _validate_strictness(cls, value: str) -> str:
        allowed = {"strict", "moderate", "lenient"}
        if value.lower() not in allowed:
            raise ValueError(f"AI_GRADING_STRICTNESS must be one of {allowed}")
        return value.lower()

    @field_validator("ai_grading_concurrency")
    @classmethod
    def _validate_grading_concurrency(cls, value: int) -> int:
        if value < 1 or value > 6:
            raise ValueError("AI_GRADING_CONCURRENCY must be between 1 and 6")
        return value

    @field_validator("ai_grading_global_concurrency")
    @classmethod
    def _validate_grading_global_concurrency(cls, value: int) -> int:
        if value < 1 or value > 8:
            raise ValueError("AI_GRADING_GLOBAL_CONCURRENCY must be between 1 and 8")
        return value

    @field_validator("ai_grading_review_score_delta_ratio", "ai_grading_review_variance_range_ratio")
    @classmethod
    def _validate_review_ratio(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("AI grading review ratios must be between 0 and 1")
        return value

    @field_validator("ai_grading_review_variance_min_answers")
    @classmethod
    def _validate_review_min_answers(cls, value: int) -> int:
        if value < 2:
            raise ValueError("AI_GRADING_REVIEW_VARIANCE_MIN_ANSWERS must be at least 2")
        return value

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
    cors_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ORIGINS")
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

    def ai_model_candidates(self, route_key: AIRouteKey) -> list[AIModelCandidate]:
        profile = _route_profile(route_key)
        chain_value = self._route_chain_value(route_key)
        if chain_value:
            return self._parse_model_chain(chain_value, profile)
        if profile == "vision":
            return [
                AIModelCandidate(
                    profile="vision",
                    model=self.ai_vision_model,
                    base_url=self.effective_vision_base_url,
                    api_key=self.effective_vision_api_key,
                )
            ]
        return [
            AIModelCandidate(
                profile="grading",
                model=self.effective_grading_model_for_route(route_key),
                base_url=self.effective_grading_base_url,
                api_key=self.effective_grading_api_key,
            )
        ]

    def _route_chain_value(self, route_key: AIRouteKey) -> str | None:
        if route_key == "vision_rubric" and self.ai_vision_rubric_chain:
            return self.ai_vision_rubric_chain
        if route_key == "vision_student_extraction" and self.ai_vision_student_extraction_chain:
            return self.ai_vision_student_extraction_chain
        if route_key == "vision_split_header" and self.ai_vision_split_header_chain:
            return self.ai_vision_split_header_chain
        if _route_profile(route_key) == "vision" and self.ai_vision_chain:
            return self.ai_vision_chain
        if route_key == "grading_review" and self.ai_grading_review_chain:
            return self.ai_grading_review_chain
        if route_key == "grading" and self.ai_grading_chain:
            return self.ai_grading_chain
        return None

    def _parse_model_chain(self, chain_value: str, profile: AIRequestProfile) -> list[AIModelCandidate]:
        try:
            raw_candidates = json.loads(chain_value)
        except json.JSONDecodeError as exc:
            raise ValueError("AI model chain settings must be JSON arrays") from exc
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise ValueError("AI model chain settings must be non-empty JSON arrays")
        candidates: list[AIModelCandidate] = []
        for index, raw_candidate in enumerate(raw_candidates, start=1):
            if not isinstance(raw_candidate, dict):
                raise ValueError(f"AI model chain candidate #{index} must be an object")
            model = _clean_optional_string(raw_candidate.get("model"))
            if not model:
                raise ValueError(f"AI model chain candidate #{index} must include a model")
            base_url = _clean_optional_string(raw_candidate.get("base_url")) or self._default_base_url_for_profile(profile)
            api_key = _clean_optional_string(raw_candidate.get("api_key")) or self._default_api_key_for_profile(profile)
            candidates.append(AIModelCandidate(profile=profile, model=model, base_url=base_url.rstrip("/"), api_key=api_key))
        return candidates

    def _default_base_url_for_profile(self, profile: AIRequestProfile) -> str:
        return self.effective_vision_base_url if profile == "vision" else self.effective_grading_base_url

    def _default_api_key_for_profile(self, profile: AIRequestProfile) -> str:
        return self.effective_vision_api_key if profile == "vision" else self.effective_grading_api_key

    def effective_grading_model_for_route(self, route_key: AIRouteKey) -> str:
        if route_key == "grading_review":
            return self.ai_grading_review_model or self.ai_grading_model
        return self.ai_grading_model

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def _route_profile(route_key: AIRouteKey) -> AIRequestProfile:
    return "grading" if route_key in {"grading", "grading_review"} else "vision"



def _clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    normalized = value.strip()
    return normalized or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
