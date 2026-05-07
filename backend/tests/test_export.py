from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.services import export


def test_build_exam_results_pdf_returns_pdf_bytes(monkeypatch) -> None:
    def fake_results_data(_session: Any, exam_id: int) -> dict[str, Any]:
        return {
            "exam": SimpleNamespace(id=exam_id, title="Sample Exam"),
            "questions": [
                SimpleNamespace(question_no="1.1"),
                SimpleNamespace(question_no="1.2"),
            ],
            "rows": [
                {
                    "student_name": "Alice",
                    "student_id": "S001",
                    "status": "graded",
                    "total_score": 8.5,
                    "needs_human_review": False,
                    "question_scores": {"1.1": 4.0, "1.2": 4.5},
                },
                {
                    "student_name": "Bob",
                    "student_id": "S002",
                    "status": "needs_review",
                    "total_score": 3.0,
                    "needs_human_review": True,
                    "question_scores": {"1.1": 3.0},
                },
            ],
        }

    monkeypatch.setattr(export, "build_exam_results_data", fake_results_data)

    pdf_bytes = export.build_exam_results_pdf(None, 1)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000


def test_export_exam_results_pdf_endpoint(monkeypatch) -> None:
    def fake_get_db():
        yield None

    monkeypatch.setattr("app.api.exams.build_exam_results_pdf", lambda _session, exam_id: b"%PDF-1.4 fake")
    app.dependency_overrides[deps.get_db] = fake_get_db
    try:
        response = TestClient(app).get("/api/exams/12/export.pdf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="exam-12-results.pdf"'
    assert response.content == b"%PDF-1.4 fake"
