from __future__ import annotations

import re
from pathlib import Path

from fastapi import UploadFile
from fastapi import HTTPException

PDF_SIGNATURE = b"%PDF-"
FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str, default_stem: str = "file") -> str:
    clean_name = Path(filename).name.strip()
    if not clean_name:
        return default_stem
    stem = Path(clean_name).stem or default_stem
    suffix = Path(clean_name).suffix
    stem = FILENAME_RE.sub("_", stem).strip("._") or default_stem
    suffix = FILENAME_RE.sub("", suffix)
    return f"{stem}{suffix}" if suffix else stem


async def validate_pdf_upload(upload_file: UploadFile) -> None:
    if upload_file.content_type not in {"application/pdf", "application/x-pdf"}:
        raise ValueError("Only PDF uploads are allowed.")
    head = await upload_file.read(5)
    await upload_file.seek(0)
    if head != PDF_SIGNATURE:
        raise ValueError("Uploaded file is not a valid PDF.")


async def read_upload_limited(
    upload_file: UploadFile,
    max_bytes: int,
    *,
    too_large_detail: str,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    data = bytearray()
    while True:
        chunk = await upload_file.read(chunk_size)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail=too_large_detail)
    await upload_file.seek(0)
    return bytes(data)


def ensure_pdf_suffix(filename: str) -> str:
    name = sanitize_filename(filename)
    if not name.lower().endswith(".pdf"):
        name = f"{Path(name).stem}.pdf"
    return name
