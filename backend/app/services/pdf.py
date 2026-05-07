from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image


@dataclass(slots=True)
class RenderedPage:
    page_no: int
    image_path: Path
    extracted_text: str


def render_pdf_to_images(pdf_path: Path, output_dir: Path, dpi: int = 300) -> list[RenderedPage]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(str(pdf_path)) as document:
        scale = dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        rendered_pages: list[RenderedPage] = []

        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = output_dir / f"page-{page_index + 1:03d}.png"
            pixmap.save(str(image_path))
            rendered_pages.append(
                RenderedPage(
                    page_no=page_index + 1,
                    image_path=image_path,
                    extracted_text=page.get_text("text").strip(),
                )
            )

        rendered_image_paths = {page.image_path for page in rendered_pages}
        for stale_image_path in output_dir.glob("page-*.png"):
            if stale_image_path not in rendered_image_paths:
                stale_image_path.unlink()

        return rendered_pages


def get_pdf_page_count(pdf_path: Path) -> int:
    with fitz.open(str(pdf_path)) as document:
        return document.page_count


def split_pdf_pages(pdf_path: Path, page_ranges: Iterable[tuple[int, int]], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    with fitz.open(str(pdf_path)) as source_document:
        for index, (start_page, end_page) in enumerate(page_ranges, start=1):
            output_path = output_dir / f"submission-{index:03d}-pages-{start_page}-{end_page}.pdf"
            with fitz.open() as target_document:
                target_document.insert_pdf(
                    source_document,
                    from_page=start_page - 1,
                    to_page=end_page - 1,
                )
                target_document.save(str(output_path))
            output_paths.append(output_path)
    return output_paths


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def crop_top_region(image_path: Path, output_path: Path, ratio: float = 0.28) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as image:
        width, height = image.size
        crop_height = max(1, int(height * ratio))
        cropped = image.crop((0, 0, width, crop_height))
        cropped.save(output_path)
    return output_path
