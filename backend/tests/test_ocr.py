from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import ocr
from app.services.ocr import OCRError, OCRPageText, PaddleOCRClient, extract_header_text_diagnostic, parse_paddle_jsonl


class FakeResponse:
    def __init__(self, payload=None, text: str = "", status_code: int = 200) -> None:
        self._payload = payload or {}
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpClient:
    def __init__(self, post_response: FakeResponse | None = None, get_responses: list[FakeResponse] | None = None) -> None:
        self.post_response = post_response or FakeResponse({"data": {"jobId": "job-123456"}})
        self.get_responses = get_responses or []
        self.posts: list[dict] = []
        self.gets: list[str] = []

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return self.post_response

    def get(self, url, **_kwargs):
        self.gets.append(url)
        if self.get_responses:
            return self.get_responses.pop(0)
        return FakeResponse(text='{"result":{"layoutParsingResults":[{"markdown":{"text":"姓名 张三 学号 123456"}}]}}')

    def close(self) -> None:
        pass


def test_parse_paddle_jsonl_extracts_markdown_text() -> None:
    text = "\n".join(
        [
            json.dumps({"result": {"layoutParsingResults": [{"markdown": {"text": "第一页"}}]}}),
            "not-json",
            json.dumps({"result": {"layoutParsingResults": [{"markdown": {"text": "第二页"}}]}}),
        ]
    )

    pages = parse_paddle_jsonl(text)

    assert [(page.page_no, page.text) for page in pages] == [(1, "第一页"), (2, "第二页")]


def test_parse_paddle_jsonl_extracts_regions_from_bbox_like_payload() -> None:
    text = json.dumps(
        {
            "result": {
                "layoutParsingResults": [
                    {
                        "markdown": {"text": "姓名 张三 学号 123456"},
                        "prunedResult": {
                            "layoutParsingResults": [
                                {"text": "姓名 张三", "bbox": [10, 20, 110, 50]},
                                {"text": "学号 123456", "box": [[10, 60], [160, 60], [160, 90], [10, 90]]},
                            ]
                        },
                    }
                ]
            }
        }
    )

    pages = parse_paddle_jsonl(text)

    assert pages[0].regions[0].text == "姓名 张三"
    assert pages[0].regions[0].bbox == [10, 20, 110, 50]
    assert pages[0].regions[1].bbox == [10, 60, 160, 90]


def test_paddle_ocr_client_submit_poll_and_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake-image")
    fake_client = FakeHttpClient(
        get_responses=[
            FakeResponse({"data": {"state": "running"}}),
            FakeResponse({"data": {"state": "done", "resultUrl": {"jsonUrl": "https://result.test/out.jsonl"}}}),
            FakeResponse(text=json.dumps({"result": {"layoutParsingResults": [{"markdown": {"text": "OCR text"}}]}})),
        ]
    )
    monkeypatch.setattr(settings, "paddle_ocr_api_key", "secret-key")
    monkeypatch.setattr(settings, "paddle_ocr_poll_interval_seconds", 0.001)
    monkeypatch.setattr(ocr.httpx, "Client", lambda **_kwargs: fake_client)

    result = PaddleOCRClient().extract_image_text(image_path)

    assert result == OCRPageText(page_no=1, text="OCR text", source="paddle")
    assert fake_client.posts[0]["headers"]["Authorization"] == "bearer secret-key"
    assert fake_client.gets[-1] == "https://result.test/out.jsonl"


def test_paddle_ocr_client_failed_job_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeHttpClient(get_responses=[FakeResponse({"data": {"state": "failed", "errorMsg": "bad image"}})])
    monkeypatch.setattr(settings, "paddle_ocr_api_key", "secret-key")
    monkeypatch.setattr(ocr.httpx, "Client", lambda **_kwargs: fake_client)

    with pytest.raises(OCRError, match="bad image"):
        PaddleOCRClient().poll_job("job-123")


def test_extract_header_text_diagnostic_reports_no_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "ocr_preprocess_enabled", True)
    monkeypatch.setattr(settings, "ocr_preprocess_split_header_enabled", True)
    monkeypatch.setattr(settings, "paddle_ocr_api_key", None)

    diagnostic = extract_header_text_diagnostic(tmp_path / "header.png")

    assert diagnostic.text is None
    assert diagnostic.reason == "no_api_key"


def test_extract_header_text_diagnostic_reports_empty_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "ocr_preprocess_enabled", True)
    monkeypatch.setattr(settings, "ocr_preprocess_split_header_enabled", True)
    monkeypatch.setattr(settings, "paddle_ocr_api_key", "secret-key")
    monkeypatch.setattr(ocr, "_cached_or_extract_text_with_cache_status", lambda *_args, **_kwargs: ("   ", True))

    diagnostic = extract_header_text_diagnostic(tmp_path / "header.png")

    assert diagnostic.text is None
    assert diagnostic.reason == "ocr_empty_text"
    assert diagnostic.cache_hit is True


def test_cached_or_extract_text_uses_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    from app.storage.local import get_storage_service

    get_storage_service.cache_clear()
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake-image")
    cache_dir = settings.storage_dir / "ocr-cache"
    cache_dir.mkdir(parents=True)
    cache_path = cache_dir / f"{ocr.hash_file(image_path)}.json"
    cache_path.write_text(
        json.dumps({"provider": "paddle", "model": settings.paddle_ocr_model, "text": "cached text"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(PaddleOCRClient, "extract_image_text", lambda *_args, **_kwargs: pytest.fail("provider called"))
    try:
        assert ocr._cached_or_extract_text(image_path) == "cached text"
    finally:
        get_storage_service.cache_clear()


def test_cached_text_reads_missing_regions_as_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    from app.storage.local import get_storage_service

    get_storage_service.cache_clear()
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake-image")
    cache_dir = settings.storage_dir / "ocr-cache"
    cache_dir.mkdir(parents=True)
    cache_path = cache_dir / f"{ocr.hash_file(image_path)}.json"
    cache_path.write_text(
        json.dumps({"provider": "paddle", "model": settings.paddle_ocr_model, "text": "cached"}),
        encoding="utf-8",
    )
    try:
        cached = ocr.read_cached_ocr_result(image_path)
    finally:
        get_storage_service.cache_clear()

    assert cached is not None
    assert cached.text == "cached"
    assert cached.regions == []


def test_build_ocr_reference_text_uses_pdf_text_before_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    page = SimpleNamespace(page_no=1, image_path=tmp_path / "page.png", extracted_text="A" * 100)
    monkeypatch.setattr(settings, "ocr_preprocess_enabled", True)
    monkeypatch.setattr(settings, "paddle_ocr_api_key", "secret-key")
    monkeypatch.setattr(settings, "ocr_min_text_chars_for_reference", 80)
    monkeypatch.setattr(PaddleOCRClient, "extract_image_text", lambda *_args, **_kwargs: pytest.fail("provider called"))

    reference = ocr.build_ocr_reference_text([page], "vision_student_extraction")

    assert "[Page 1]" in reference
    assert "A" * 20 in reference


def test_build_ocr_reference_text_enqueues_failed_page_when_context_is_available(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    from app.storage.local import get_storage_service

    get_storage_service.cache_clear()
    storage = get_storage_service()
    image_path = storage.path_for("rendered/submissions/1/pages/page-001.png")
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake-image")
    page = SimpleNamespace(page_no=1, image_path=image_path, extracted_text="")
    calls: list[dict] = []
    monkeypatch.setattr(settings, "ocr_preprocess_enabled", True)
    monkeypatch.setattr(settings, "paddle_ocr_api_key", "secret-key")
    monkeypatch.setattr(PaddleOCRClient, "extract_image_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OCRError("provider down")))
    monkeypatch.setattr(ocr.bad_cases, "enqueue", lambda _session=None, **kwargs: calls.append(kwargs) or 1)

    try:
        reference = ocr.build_ocr_reference_text(
            [page],
            "vision_student_extraction",
            session=object(),
            exam_id=2,
            submission_id=1,
        )
    finally:
        get_storage_service.cache_clear()

    assert reference == ""
    assert calls[0]["route_key"] == "vision_student_extraction"
    assert calls[0]["trigger_reason"] == "ocr_request_failed"
    assert calls[0]["ocr_error_message"] == "provider down"
    assert calls[0]["image_storage_path"] == "rendered/submissions/1/pages/page-001.png"
    assert calls[0]["exam_id"] == 2
    assert calls[0]["submission_id"] == 1
