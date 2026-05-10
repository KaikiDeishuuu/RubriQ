import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings


def _settings(**overrides) -> Settings:
    defaults = {
        "AI_BASE_URL": "https://base.test/v1",
        "AI_API_KEY": "base-key",
        "AI_VISION_BASE_URL": "",
        "AI_VISION_API_KEY": "",
        "AI_GRADING_BASE_URL": "",
        "AI_GRADING_API_KEY": "",
        "AI_VISION_MODEL": "vision-default",
        "AI_GRADING_MODEL": "grading-default",
        "AI_VISION_CHAIN": None,
        "AI_VISION_RUBRIC_CHAIN": None,
        "AI_VISION_STUDENT_EXTRACTION_CHAIN": None,
        "AI_VISION_SPLIT_HEADER_CHAIN": None,
        "AI_VISION_GRADING_REVIEW_CHAIN": None,
        "AI_GRADING_CHAIN": None,
        "AI_GRADING_REVIEW_MODEL": None,
        "AI_GRADING_REVIEW_CHAIN": None,
        "OCR_PREPROCESS_ENABLED": False,
        "OCR_PREPROCESS_RUBRIC_ENABLED": False,
        "OCR_PREPROCESS_STUDENT_ENABLED": True,
        "OCR_PREPROCESS_SPLIT_HEADER_ENABLED": True,
        "PADDLE_OCR_API_KEY": None,
        "OCR_SPLIT_HEADER_CONCURRENCY": 4,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_ai_and_render_settings_exist() -> None:
    assert settings.render_dpi > 0
    assert settings.ai_request_timeout_seconds > 0
    assert settings.ai_max_retries >= 0
    assert settings.ai_retry_backoff_seconds >= 0
    assert 1 <= settings.ai_grading_concurrency <= 6
    assert 1 <= settings.ai_grading_global_concurrency <= 8
    assert 1 <= settings.export_global_concurrency <= 8
    assert settings.export_submissions_zip_max_submissions >= 1
    assert 0 <= settings.ai_grading_review_low_score_ratio <= 1
    assert settings.ai_grading_review_formula_force_review is True
    assert settings.ai_grading_review_zero_score_force_review is True
    assert 1 <= settings.ocr_split_header_concurrency <= 8



def test_ai_model_candidates_fall_back_to_legacy_single_model() -> None:
    app_settings = _settings()

    vision_candidates = app_settings.ai_model_candidates("vision_student_extraction")
    grading_candidates = app_settings.ai_model_candidates("grading")

    assert [
        (candidate.profile, candidate.model, candidate.base_url, candidate.api_key, candidate.supports_vision)
        for candidate in vision_candidates
    ] == [("vision", "vision-default", "https://base.test/v1", "base-key", True)]
    assert [
        (candidate.profile, candidate.model, candidate.base_url, candidate.api_key, candidate.supports_vision)
        for candidate in grading_candidates
    ] == [("grading", "grading-default", "https://base.test/v1", "base-key", False)]



def test_ai_model_candidates_prefer_task_chain_over_generic_chain() -> None:
    app_settings = _settings(
        AI_VISION_BASE_URL="https://vision.test/v1",
        AI_VISION_API_KEY="vision-key",
        AI_VISION_CHAIN='[{"model":"generic-vision"}]',
        AI_VISION_STUDENT_EXTRACTION_CHAIN=(
            '[{"model":"gemini-ocr","base_url":"https://gemini.test/v1","api_key":"gemini-key"},'
            '{"model":"vision-backup"}]'
        ),
    )

    candidates = app_settings.ai_model_candidates("vision_student_extraction")
    rubric_candidates = app_settings.ai_model_candidates("vision_rubric")

    assert [(candidate.model, candidate.base_url, candidate.api_key) for candidate in candidates] == [
        ("gemini-ocr", "https://gemini.test/v1", "gemini-key"),
        ("vision-backup", "https://vision.test/v1", "vision-key"),
    ]
    assert [candidate.model for candidate in rubric_candidates] == ["generic-vision"]



def test_ai_model_candidates_parse_grading_chain() -> None:
    app_settings = _settings(
        AI_GRADING_BASE_URL="https://grading.test/v1",
        AI_GRADING_API_KEY="grading-key",
        AI_GRADING_CHAIN='[{"model":"grader-fast"},{"model":"grader-safe","api_key":"safe-key"}]',
    )

    candidates = app_settings.ai_model_candidates("grading")

    assert [(candidate.profile, candidate.model, candidate.base_url, candidate.api_key, candidate.supports_vision) for candidate in candidates] == [
        ("grading", "grader-fast", "https://grading.test/v1", "grading-key", False),
        ("grading", "grader-safe", "https://grading.test/v1", "safe-key", False),
    ]



def test_ai_model_candidates_reject_invalid_chain() -> None:
    app_settings = _settings(AI_VISION_CHAIN="not-json")

    with pytest.raises(ValueError, match="JSON arrays"):
        app_settings.ai_model_candidates("vision_rubric")



def test_ai_model_candidates_parse_vision_capability_flags() -> None:
    app_settings = _settings(
        AI_VISION_BASE_URL="https://vision.test/v1",
        AI_VISION_API_KEY="vision-key",
        AI_VISION_GRADING_REVIEW_CHAIN='[{"model":"text-review","supports_vision":false},{"model":"vision-review","supports_images":"true"}]',
    )

    candidates = app_settings.ai_model_candidates("vision_grading_review")

    assert [(candidate.model, candidate.supports_vision) for candidate in candidates] == [
        ("text-review", False),
        ("vision-review", True),
    ]


def test_ai_model_candidates_use_review_model_for_grading_review_route() -> None:
    app_settings = _settings(
        AI_GRADING_BASE_URL="https://grading.test/v1",
        AI_GRADING_API_KEY="grading-key",
        AI_GRADING_REVIEW_MODEL="grader-strong",
    )

    candidates = app_settings.ai_model_candidates("grading_review")

    assert [(candidate.profile, candidate.model, candidate.base_url, candidate.api_key, candidate.supports_vision) for candidate in candidates] == [
        ("grading", "grader-strong", "https://grading.test/v1", "grading-key", False)
    ]


def test_ai_model_candidates_parse_review_chain() -> None:
    app_settings = _settings(
        AI_GRADING_BASE_URL="https://grading.test/v1",
        AI_GRADING_API_KEY="grading-key",
        AI_GRADING_REVIEW_CHAIN=(
            '[{"model":"grader-strong","base_url":"https://review.test/v1","api_key":"review-key"},'
            '{"model":"grader-backup"}]'
        ),
    )

    candidates = app_settings.ai_model_candidates("grading_review")

    assert [(candidate.profile, candidate.model, candidate.base_url, candidate.api_key, candidate.supports_vision) for candidate in candidates] == [
        ("grading", "grader-strong", "https://review.test/v1", "review-key", False),
        ("grading", "grader-backup", "https://grading.test/v1", "grading-key", False),
    ]


def test_invalid_review_thresholds_are_rejected() -> None:
    with pytest.raises(ValidationError, match="AI grading review ratios"):
        _settings(AI_GRADING_REVIEW_SCORE_DELTA_RATIO=1.5)
    with pytest.raises(ValidationError, match="AI grading review ratios"):
        _settings(AI_GRADING_REVIEW_LOW_SCORE_RATIO=-0.1)
    with pytest.raises(ValidationError, match="AI_GRADING_REVIEW_VARIANCE_MIN_ANSWERS"):
        _settings(AI_GRADING_REVIEW_VARIANCE_MIN_ANSWERS=1)


def test_ocr_preprocess_is_disabled_by_default_and_requires_key() -> None:
    app_settings = _settings()

    assert app_settings.ocr_preprocess_enabled is False
    assert app_settings.ocr_enabled_for_route("vision_student_extraction") is False

    enabled_without_key = _settings(OCR_PREPROCESS_ENABLED=True, PADDLE_OCR_API_KEY=None)
    assert enabled_without_key.ocr_enabled_for_route("vision_student_extraction") is False

    enabled_with_key = _settings(OCR_PREPROCESS_ENABLED=True, PADDLE_OCR_API_KEY="ocr-key")
    assert enabled_with_key.ocr_enabled_for_route("vision_student_extraction") is True
    assert enabled_with_key.ocr_enabled_for_route("vision_split_header") is True
    assert enabled_with_key.ocr_enabled_for_route("vision_rubric") is False


def test_invalid_ocr_settings_are_rejected() -> None:
    with pytest.raises(ValidationError, match="OCR timing settings"):
        _settings(PADDLE_OCR_TIMEOUT_SECONDS=0)
    with pytest.raises(ValidationError, match="OCR_SPLIT_HEADER_MIN_CONFIDENCE"):
        _settings(OCR_SPLIT_HEADER_MIN_CONFIDENCE=1.2)
    with pytest.raises(ValidationError, match="OCR_SPLIT_HEADER_CONCURRENCY"):
        _settings(OCR_SPLIT_HEADER_CONCURRENCY=0)


def test_invalid_export_settings_are_rejected() -> None:
    with pytest.raises(ValidationError, match="EXPORT_GLOBAL_CONCURRENCY"):
        _settings(EXPORT_GLOBAL_CONCURRENCY=0)
    with pytest.raises(ValidationError, match="EXPORT_SUBMISSIONS_ZIP_MAX_SUBMISSIONS"):
        _settings(EXPORT_SUBMISSIONS_ZIP_MAX_SUBMISSIONS=0)


def test_invalid_grading_strictness_is_rejected() -> None:
    with pytest.raises(ValidationError, match="AI_GRADING_STRICTNESS"):
        Settings(AI_GRADING_STRICTNESS="random")
