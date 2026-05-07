from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


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
