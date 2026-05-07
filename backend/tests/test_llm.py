import pytest

from app.services.llm import StructuredJsonError, _parse_completion_content
from app.schemas.ai import RubricParseResult


def test_parse_completion_content_rejects_empty_response() -> None:
    with pytest.raises(StructuredJsonError, match="empty response"):
        _parse_completion_content("", RubricParseResult)
