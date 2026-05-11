from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def test_grading_prompt_accepts_equivalent_formula_forms() -> None:
    prompt = (PROMPTS_DIR / "grading.system.md").read_text(encoding="utf-8")

    assert "mathematically equivalent forms" in prompt
    assert "unsimplified forms" in prompt
    assert "cancelled/simplified forms" in prompt
    assert "missing final numeric values" in prompt
    assert "rubric explicitly requires" in prompt


def test_grading_prompt_prioritizes_supplemental_instructions() -> None:
    prompt = (PROMPTS_DIR / "grading.system.md").read_text(encoding="utf-8")

    assert "supplemental_instructions" in prompt
    assert "higher priority" in prompt
    assert "priority_order" in prompt
    assert "do not add rubric_evaluation rows" in prompt
    assert "do not change the question max_score cap" in prompt


def test_review_prompt_prioritizes_formula_images_and_formula_only_credit() -> None:
    prompt = (PROMPTS_DIR / "grading_review.user.md").read_text(encoding="utf-8")

    assert "The attached page images are the primary source of truth" in prompt
    assert "Treat mathematically equivalent formulas as correct" in prompt
    assert "Formula-only full credit" in prompt
    assert "do not deduct for missing final numeric values" in prompt


def test_review_prompt_prioritizes_supplemental_instructions() -> None:
    prompt = (PROMPTS_DIR / "grading_review.user.md").read_text(encoding="utf-8")

    assert "Supplemental instructions priority" in prompt
    assert "supplemental_instructions" in prompt
    assert "override conflicting interpretations" in prompt
    assert "priority_order" in prompt
    assert "do not add `rubric_evaluation` rows" in prompt
    assert "do not change the question `max_score` cap" in prompt


def test_review_prompt_uses_images_and_ocr_to_correct_extraction_compression() -> None:
    prompt = (PROMPTS_DIR / "grading_review.user.md").read_text(encoding="utf-8")

    assert "OCR reference text" in prompt
    assert "semantically compressed" in prompt
    assert "directional words" in prompt
    assert "smaller/larger" in prompt
    assert "do not rely only on `student_answer`" in prompt
