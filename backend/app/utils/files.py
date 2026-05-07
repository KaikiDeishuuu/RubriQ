from __future__ import annotations

import re
from pathlib import Path

from fastapi import UploadFile

PDF_SIGNATURE = b"%PDF-"
FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str, default_stem: str = "file") -> str:
    clean_name = Path(filename).name.strip()
    if not clean_name:
        return f"{default_stem}.pdf"
    stem = Path(clean_name).stem or default_stem
    suffix = Path(clean_name).suffix or ".pdf"
    stem = FILENAME_RE.sub("_", stem).strip("._") or default_stem
    suffix = ".pdf" if suffix.lower() != ".pdf" else ".pdf"
    return f"{stem}{suffix}"


async def validate_pdf_upload(upload_file: UploadFile) -> None:
    if upload_file.content_type not in {"application/pdf", "application/x-pdf"}:
        raise ValueError("Only PDF uploads are allowed.")
    head = await upload_file.read(5)
    await upload_file.seek(0)
    if head != PDF_SIGNATURE:
        raise ValueError("Uploaded file is not a valid PDF.")


def ensure_pdf_suffix(filename: str) -> str:
    name = sanitize_filename(filename)
    if not name.lower().endswith(".pdf"):
        name = f"{Path(name).stem}.pdf"
    return name
