from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.config import AIRouteKey, settings
from app.services.pdf import RenderedPage, hash_file
from app.storage.local import get_storage_service

logger = logging.getLogger(__name__)


class OCRError(RuntimeError):
    pass


@dataclass(slots=True)
class OCRPageText:
    page_no: int
    text: str
    source: str = "paddle"


@dataclass(slots=True)
class OCRResult:
    page_texts: list[OCRPageText]
    raw_text: str | None = None

    @property
    def combined_text(self) -> str:
        return "\n\n".join(
            f"[Page {page.page_no}]\n{page.text.strip()}" for page in self.page_texts if page.text.strip()
        ).strip()


@dataclass(slots=True)
class HeaderOCRDiagnostic:
    text: str | None
    reason: str
    text_chars: int = 0
    cache_hit: bool | None = None
    error_message: str | None = None


class PaddleOCRClient:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=settings.paddle_ocr_timeout_seconds)
        self._base_url = settings.paddle_ocr_base_url.rstrip("/")
        self._headers = {"Authorization": f"bearer {settings.paddle_ocr_api_key or ''}"}

    def close(self) -> None:
        self._client.close()

    def extract_image_text(self, image_path: Path) -> OCRPageText:
        started_at = time.perf_counter()
        job_id = self.submit_image(image_path)
        json_url = self.poll_job(job_id)
        page_texts = self.fetch_jsonl_result(json_url)
        text = "\n\n".join(page.text for page in page_texts if page.text.strip()).strip()
        logger.info(
            "PaddleOCR image completed job=%s duration_seconds=%.2f text_chars=%s",
            _safe_job_id(job_id),
            time.perf_counter() - started_at,
            len(text),
        )
        return OCRPageText(page_no=1, text=text, source="paddle")

    def submit_image(self, image_path: Path) -> str:
        if not settings.paddle_ocr_api_key:
            raise OCRError("PaddleOCR API key is not configured")
        data = {
            "model": settings.paddle_ocr_model,
            "optionalPayload": json.dumps(
                {
                    "useDocOrientationClassify": False,
                    "useDocUnwarping": False,
                    "useChartRecognition": False,
                }
            ),
        }
        try:
            with image_path.open("rb") as file_obj:
                response = self._client.post(
                    self._base_url,
                    headers=self._headers,
                    data=data,
                    files={"file": file_obj},
                )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - provider failures must fall back safely
            raise OCRError(f"PaddleOCR job submit failed: {exc}") from exc
        job_id = ((payload.get("data") or {}).get("jobId") or "").strip()
        if not job_id:
            raise OCRError("PaddleOCR response did not include a job id")
        return job_id

    def poll_job(self, job_id: str) -> str:
        deadline = time.monotonic() + settings.paddle_ocr_max_poll_seconds
        while time.monotonic() < deadline:
            try:
                response = self._client.get(f"{self._base_url}/{job_id}", headers=self._headers)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:  # noqa: BLE001 - provider failures must fall back safely
                raise OCRError(f"PaddleOCR job poll failed: {exc}") from exc
            data = payload.get("data") or {}
            state = data.get("state")
            if state == "done":
                json_url = (((data.get("resultUrl") or {}).get("jsonUrl")) or "").strip()
                if not json_url:
                    raise OCRError("PaddleOCR completed without a JSON result URL")
                return json_url
            if state == "failed":
                raise OCRError(f"PaddleOCR job failed: {data.get('errorMsg') or 'unknown error'}")
            time.sleep(settings.paddle_ocr_poll_interval_seconds)
        raise OCRError("PaddleOCR job timed out")

    def fetch_jsonl_result(self, json_url: str) -> list[OCRPageText]:
        try:
            response = self._client.get(json_url)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - provider failures must fall back safely
            raise OCRError(f"PaddleOCR JSONL fetch failed: {exc}") from exc
        return parse_paddle_jsonl(response.text)


def parse_paddle_jsonl(text: str) -> list[OCRPageText]:
    page_texts: list[OCRPageText] = []
    page_no = 1
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed PaddleOCR JSONL line")
            continue
        result = payload.get("result") or {}
        for layout_result in result.get("layoutParsingResults") or []:
            markdown = layout_result.get("markdown") or {}
            markdown_text = str(markdown.get("text") or "").strip()
            if markdown_text:
                page_texts.append(OCRPageText(page_no=page_no, text=markdown_text, source="paddle"))
                page_no += 1
    return page_texts


def build_ocr_reference_text(pages: list[RenderedPage], route_key: AIRouteKey) -> str:
    if not settings.ocr_enabled_for_route(route_key):
        return ""
    reference_pages: list[OCRPageText] = []
    for page in pages:
        text = _best_text_for_page(page)
        if text:
            reference_pages.append(OCRPageText(page_no=page.page_no, text=text, source="paddle_or_pdf"))
    return OCRResult(reference_pages).combined_text


def format_ocr_reference_text(text: str | None) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return ""
    return (
        "OCR reference text below is provided only as an aid. If it conflicts with the attached images, "
        "trust the image content.\n\n[OCR Reference Text]\n"
        f"{normalized}"
    )


def extract_header_text(image_path: Path, page_hash: str | None = None) -> str | None:
    return extract_header_text_diagnostic(image_path, page_hash=page_hash).text


def extract_header_text_diagnostic(image_path: Path, page_hash: str | None = None) -> HeaderOCRDiagnostic:
    if not settings.ocr_preprocess_enabled:
        return HeaderOCRDiagnostic(text=None, reason="ocr_disabled_global")
    if not settings.ocr_preprocess_split_header_enabled:
        return HeaderOCRDiagnostic(text=None, reason="ocr_disabled_split_header")
    if not settings.paddle_ocr_api_key:
        return HeaderOCRDiagnostic(text=None, reason="no_api_key")
    try:
        text, cache_hit = _cached_or_extract_text_with_cache_status(image_path, page_hash=page_hash)
    except OCRError as exc:
        logger.warning("PaddleOCR header extraction failed; falling back to vision: %s", exc)
        return HeaderOCRDiagnostic(text=None, reason="ocr_request_failed", error_message=str(exc))
    stripped = text.strip()
    if not stripped:
        return HeaderOCRDiagnostic(text=None, reason="ocr_empty_text", text_chars=0, cache_hit=cache_hit)
    return HeaderOCRDiagnostic(text=stripped, reason="ocr_text_extracted", text_chars=len(stripped), cache_hit=cache_hit)


def _best_text_for_page(page: RenderedPage) -> str:
    pdf_text = page.extracted_text.strip()
    if len(pdf_text) >= settings.ocr_min_text_chars_for_reference:
        return pdf_text
    try:
        ocr_text = _cached_or_extract_text(page.image_path).strip()
    except OCRError as exc:
        logger.warning("PaddleOCR page extraction failed; using PDF text/vision fallback: %s", exc)
        return pdf_text
    return ocr_text or pdf_text


def _cached_or_extract_text(image_path: Path, page_hash: str | None = None) -> str:
    text, _cache_hit = _cached_or_extract_text_with_cache_status(image_path, page_hash=page_hash)
    return text


def _cached_or_extract_text_with_cache_status(image_path: Path, page_hash: str | None = None) -> tuple[str, bool]:
    cache_path = _cache_path_for_image(image_path, page_hash=page_hash)
    cached_text = _read_cached_text(cache_path)
    if cached_text is not None:
        return cached_text, True
    client = PaddleOCRClient()
    try:
        result = client.extract_image_text(image_path)
    finally:
        client.close()
    _write_cached_text(cache_path, image_path=image_path, text=result.text)
    return result.text, False


def _cache_path_for_image(image_path: Path, page_hash: str | None = None) -> Path:
    source_hash = page_hash or hash_file(image_path)
    storage = get_storage_service()
    cache_dir = storage.path_for("ocr-cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{source_hash}.json"


def _read_cached_text(cache_path: Path) -> str | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("provider") != "paddle" or payload.get("model") != settings.paddle_ocr_model:
        return None
    text = payload.get("text")
    return text if isinstance(text, str) else None


def _write_cached_text(cache_path: Path, *, image_path: Path, text: str) -> None:
    payload: dict[str, Any] = {
        "provider": "paddle",
        "model": settings.paddle_ocr_model,
        "image_name": image_path.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "text": text,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_job_id(job_id: str) -> str:
    return f"...{job_id[-6:]}" if len(job_id) > 6 else job_id
