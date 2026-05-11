from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from app.services.ocr import OCRRegion

BBox = list[int]


@dataclass(slots=True)
class RedactionResult:
    method: str
    success: bool


def find_pii_bboxes(regions: list[OCRRegion], *, exam=None, submission=None) -> list[BBox]:
    known_names = {submission.student_name for submission in [submission] if submission is not None and submission.student_name}
    known_ids = {submission.student_id for submission in [submission] if submission is not None and submission.student_id}
    if exam is not None:
        for entry in getattr(exam, "roster_entries", []) or []:
            if entry.student_name:
                known_names.add(entry.student_name)
            if entry.student_id:
                known_ids.add(entry.student_id)
    boxes: list[BBox] = []
    for region in regions:
        text = region.text.strip()
        if not text:
            continue
        if re.search(r"\b\d{6,12}\b", text) or any(student_id and student_id in text for student_id in known_ids):
            boxes.append(region.bbox)
            continue
        if any(name and name in text for name in known_names):
            boxes.append(region.bbox)
            continue
        if re.search(r"(?:姓名|学生|Name)\s*[:：]?\s*[一-鿿]{2,4}", text, flags=re.IGNORECASE):
            boxes.append(region.bbox)
            continue
        if re.search(r"(?:学号|学籍号|考号|student\s*id)\s*[:：]?", text, flags=re.IGNORECASE):
            boxes.append(region.bbox)
    return boxes


def redact_image(
    image_path: Path,
    route_key: str,
    regions: list[OCRRegion],
    out_path: Path,
    *,
    exam=None,
    submission=None,
) -> RedactionResult:
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(image_path) as image:
            redacted = image.convert("RGB")
            if route_key == "vision_split_header":
                redacted.save(out_path)
                return RedactionResult(method="no_pii_detected", success=True)
            boxes = find_pii_bboxes(regions, exam=exam, submission=submission)
            draw = ImageDraw.Draw(redacted)
            if boxes:
                for box in boxes:
                    draw.rectangle(tuple(box), fill=(0, 0, 0))
                method = "ocr_bbox"
            else:
                method = "no_pii_detected"
            redacted.save(out_path)
            return RedactionResult(method=method, success=True)
    except Exception:
        return RedactionResult(method="skipped_image", success=False)


def create_placeholder_image(source_path: Path, out_path: Path, case_id: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source_path) as source:
            size = source.size
    except Exception:
        size = (800, 600)
    image = Image.new("RGB", size, (128, 128, 128))
    draw = ImageDraw.Draw(image)
    draw.text((20, max(20, size[1] // 2)), f"REDACTION FAILED - id: {case_id}", fill=(255, 255, 255))
    image.save(out_path)
