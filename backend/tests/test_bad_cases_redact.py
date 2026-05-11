from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.services.bad_cases_redact import OCRRegion, find_pii_bboxes, redact_image


def test_find_pii_bboxes_detects_student_id_and_labelled_name() -> None:
    regions = [
        OCRRegion(text="姓名 张三", bbox=[10, 10, 90, 40]),
        OCRRegion(text="学号 12345678", bbox=[10, 50, 160, 80]),
        OCRRegion(text="答案", bbox=[10, 90, 60, 120]),
    ]

    boxes = find_pii_bboxes(regions)

    assert [10, 10, 90, 40] in boxes
    assert [10, 50, 160, 80] in boxes


def test_redact_image_blacks_detected_bbox(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "out.png"
    Image.new("RGB", (200, 120), "white").save(source)

    result = redact_image(source, "vision_student_extraction", [OCRRegion(text="学号 12345678", bbox=[10, 10, 60, 40])], output)

    assert result.success is True
    assert result.method == "ocr_bbox"
    with Image.open(output) as image:
        assert image.getpixel((20, 20)) == (0, 0, 0)
        assert image.getpixel((100, 100)) == (255, 255, 255)


def test_split_header_redaction_skips_image(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "out.png"
    Image.new("RGB", (100, 60), "white").save(source)

    result = redact_image(source, "vision_split_header", [OCRRegion(text="学号 12345678", bbox=[1, 1, 50, 20])], output)

    assert result.success is True
    assert result.method == "no_pii_detected"
    with Image.open(output) as image:
        assert image.getpixel((10, 10)) == (255, 255, 255)
