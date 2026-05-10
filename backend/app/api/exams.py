from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from app.api.common import (
    load_exam_detail,
    load_question_detail,
    recalculate_exam_total,
    recalculate_question_and_exam_totals,
    serialize_exam_detail,
    serialize_exam_list_item,
    serialize_question,
)
from app.api.deps import get_db, require_admin_token
from app.core.config import settings
from app.models import Exam, ExamFile, Question, RubricItem, Submission
from app.schemas.exam import (
    ExamCreate,
    ExamDetail,
    ExamListItem,
    ExamResultsResponse,
    QuestionRead,
    QuestionUpdate,
    RubricItemCreate,
    RubricItemUpdate,
)
from app.schemas.submission import PageUploadResponse, SubmissionUploadResponse, SubmissionSummary
from app.services.export import (
    ExportBusyError,
    ExportLimitError,
    build_exam_deductions_csv,
    build_exam_deductions_xlsx,
    build_exam_results_csv,
    build_exam_results_data,
    build_exam_results_pdf,
    build_exam_results_xlsx,
    build_exam_submissions_zip,
    export_slot,
)
from app.services.pipeline import PipelineError, _to_decimal, parse_rubric_for_exam
from app.storage.local import get_storage_service
from app.utils.errors import public_error_message
from app.utils.files import read_upload_limited, validate_pdf_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exams", tags=["exams"])


@router.post("", response_model=ExamDetail)
def create_exam(
    payload: ExamCreate,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = Exam(title=payload.title, description=payload.description)
    session.add(exam)
    session.commit()
    return serialize_exam_detail(load_exam_detail(session, exam.id))


@router.get("", response_model=list[ExamListItem])
def list_exams(
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    stmt = select(Exam).options(selectinload(Exam.questions), selectinload(Exam.submissions))
    exams = session.execute(stmt).scalars().all()
    response: list[ExamListItem] = []
    for exam in exams:
        response.append(
            serialize_exam_list_item(
                exam,
                question_count=len(exam.questions),
                submission_count=len(exam.submissions),
            )
        )
    return response


@router.get("/{exam_id}", response_model=ExamDetail)
def get_exam_detail(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    return serialize_exam_detail(exam)


@router.post("/{exam_id}/rubric/upload", response_model=PageUploadResponse)
async def upload_rubric_pdf(
    exam_id: int,
    file: UploadFile = File(...),
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    await _validate_pdf_upload_or_400(file)
    data = await read_upload_limited(
        file,
        settings.max_upload_bytes,
        too_large_detail="Uploaded rubric PDF is too large",
    )
    storage = get_storage_service()
    stored = storage.save_bytes(storage.unique_pdf_path(f"exams/{exam.id}/rubric", file.filename or "rubric.pdf"), data)
    exam_file = ExamFile(
        exam_id=exam.id,
        file_type="rubric_pdf",
        original_filename=file.filename or "rubric.pdf",
        storage_path=stored.relative_path,
    )
    exam.needs_rubric_review = True
    session.add(exam_file)
    session.commit()
    response = PageUploadResponse(
        message="Rubric PDF uploaded successfully",
        exam_file=None,
    )
    response.exam_file = _exam_file_to_read(exam_file)
    return response


@router.post("/{exam_id}/rubric/parse", response_model=ExamDetail)
def parse_rubric(
    exam_id: int,
    exam_file_id: int | None = Query(default=None),
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    try:
        exam = parse_rubric_for_exam(session, exam_id, exam_file_id=exam_file_id)
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=public_error_message(exc, "Request failed")) from exc
    return serialize_exam_detail(exam)


@router.post("/{exam_id}/rubric/confirm", response_model=ExamDetail)
def confirm_rubric(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    if not exam.questions:
        raise HTTPException(status_code=400, detail="请先解析评分标准并至少保留一道题再确认")
    exam.needs_rubric_review = False
    session.commit()
    return serialize_exam_detail(load_exam_detail(session, exam_id))


@router.post("/{exam_id}/rubric/reopen", response_model=ExamDetail)
def reopen_rubric(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    exam.needs_rubric_review = True
    session.commit()
    return serialize_exam_detail(load_exam_detail(session, exam_id))


@router.get("/{exam_id}/questions", response_model=list[QuestionRead])
def list_questions(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    return [serialize_question(question) for question in exam.questions]


@router.put("/questions/{question_id}", response_model=QuestionRead)
def update_question(
    question_id: int,
    payload: QuestionUpdate,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    question = load_question_detail(session, question_id)
    if payload.question_no is not None:
        normalized_question_no = payload.question_no.strip()
        if not normalized_question_no:
            raise HTTPException(status_code=400, detail="Question number cannot be empty")
        duplicate = session.execute(
            select(Question.id).where(
                Question.exam_id == question.exam_id,
                func.lower(Question.question_no) == normalized_question_no.lower(),
                Question.id != question.id,
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Question number already exists in this exam")
        question.question_no = normalized_question_no
    if payload.title is not None:
        question.title = payload.title
    if payload.max_score is not None:
        question.max_score = _to_decimal(payload.max_score)
    if payload.order_index is not None:
        question.order_index = payload.order_index
    recalculate_exam_total(session, question.exam_id)
    session.commit()
    return serialize_question(load_question_detail(session, question_id))


@router.post("/questions/{question_id}/rubric-items", response_model=QuestionRead)
def create_rubric_item(
    question_id: int,
    payload: RubricItemCreate,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    question = load_question_detail(session, question_id)
    rubric_item = RubricItem(
        question_id=question.id,
        description=payload.description,
        max_score=_to_decimal(payload.max_score),
        keywords=payload.keywords,
        order_index=payload.order_index,
    )
    session.add(rubric_item)
    # Rubric item changes do NOT auto-update question.max_score or exam.total_score —
    # the AI-parsed/teacher-entered question max is authoritative. Recalculating
    # would overwrite question max with sum(rubric_items), which can drift up or down.
    session.commit()
    return serialize_question(load_question_detail(session, question_id))


@router.put("/rubric-items/{item_id}", response_model=QuestionRead)
def update_rubric_item(
    item_id: int,
    payload: RubricItemUpdate,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    rubric_item = _load_rubric_item_or_404(session, item_id)
    if payload.description is not None:
        rubric_item.description = payload.description
    if payload.max_score is not None:
        rubric_item.max_score = _to_decimal(payload.max_score)
    if payload.keywords is not None:
        rubric_item.keywords = payload.keywords
    if payload.order_index is not None:
        rubric_item.order_index = payload.order_index
    # Same as create: do NOT touch question.max_score / exam.total_score from rubric items.
    session.commit()
    return serialize_question(load_question_detail(session, rubric_item.question_id))


@router.delete("/rubric-items/{item_id}")
def delete_rubric_item(
    item_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    rubric_item = _load_rubric_item_or_404(session, item_id)
    question_id = rubric_item.question_id
    session.delete(rubric_item)
    session.commit()
    return {"message": "Rubric item deleted"}


@router.post("/{exam_id}/submissions/upload", response_model=SubmissionUploadResponse)
async def upload_submissions(
    exam_id: int,
    files: list[UploadFile] = File(...),
    student_name: str | None = Form(default=None),
    student_id: str | None = Form(default=None),
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    if len(files) > settings.submissions_upload_max_files:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多上传 {settings.submissions_upload_max_files} 份答卷，请分批上传。",
        )
    storage = get_storage_service()
    created_submissions: list[SubmissionSummary] = []
    for file in files:
        await _validate_pdf_upload_or_400(file)
        data = await read_upload_limited(
            file,
            settings.max_upload_bytes,
            too_large_detail="Uploaded submission PDF is too large",
        )
        stored = storage.save_bytes(
            storage.unique_pdf_path(f"exams/{exam.id}/submissions", file.filename or "submission.pdf"),
            data,
        )
        submission = Submission(
            exam_id=exam.id,
            student_name=student_name,
            student_id=student_id,
            original_pdf_path=stored.relative_path,
            status="uploaded",
        )
        session.add(submission)
        session.flush()
        session.refresh(submission)
        created_submissions.append(SubmissionSummary.model_validate(submission))
    session.commit()
    return SubmissionUploadResponse(submissions=created_submissions)


@router.get("/{exam_id}/results", response_model=ExamResultsResponse)
def get_exam_results(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    from app.schemas.exam import ExamDetail, ExamResultRow, QuestionRead

    data = build_exam_results_data(session, exam_id)
    exam = data["exam"]
    questions = [QuestionRead.model_validate(question) for question in data["questions"]]
    rows = [ExamResultRow.model_validate(row) for row in data["rows"]]
    return ExamResultsResponse(
        exam=ExamDetail.model_validate(exam),
        questions=questions,
        rows=rows,
        ai_review_active=data.get("ai_review_active", False),
        ai_review_statuses=data.get("ai_review_statuses", []),
    )


@router.get("/{exam_id}/export.csv")
def export_exam_results_csv(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    try:
        with export_slot():
            csv_content = build_exam_results_csv(session, exam_id)
    except ExportBusyError as exc:
        raise HTTPException(status_code=429, detail=public_error_message(exc, "Request failed")) from exc
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="exam-{exam_id}-results.csv"'},
    )


@router.get("/{exam_id}/export.xlsx")
def export_exam_results_xlsx(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    try:
        with export_slot():
            xlsx_bytes = build_exam_results_xlsx(session, exam_id)
    except ExportBusyError as exc:
        raise HTTPException(status_code=429, detail=public_error_message(exc, "Request failed")) from exc
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="exam-{exam_id}-results.xlsx"'},
    )


@router.get("/{exam_id}/export.pdf")
def export_exam_results_pdf(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    try:
        with export_slot():
            pdf_bytes = build_exam_results_pdf(session, exam_id)
    except ExportBusyError as exc:
        raise HTTPException(status_code=429, detail=public_error_message(exc, "Request failed")) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="exam-{exam_id}-results.pdf"'},
    )


@router.get("/{exam_id}/export-deductions.csv")
def export_exam_deductions_csv(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    _load_exam_or_404(session, exam_id)
    try:
        with export_slot():
            csv_content = build_exam_deductions_csv(session, exam_id)
    except ExportBusyError as exc:
        raise HTTPException(status_code=429, detail=public_error_message(exc, "Request failed")) from exc
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="exam-{exam_id}-deductions.csv"'},
    )


@router.get("/{exam_id}/export-deductions.xlsx")
def export_exam_deductions_xlsx(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    _load_exam_or_404(session, exam_id)
    try:
        with export_slot():
            xlsx_bytes = build_exam_deductions_xlsx(session, exam_id)
    except ExportBusyError as exc:
        raise HTTPException(status_code=429, detail=public_error_message(exc, "Request failed")) from exc
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="exam-{exam_id}-deductions.xlsx"'},
    )


@router.get("/{exam_id}/export-submissions.zip")
def export_exam_submissions_zip(
    exam_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    try:
        with export_slot():
            zip_bytes, total, failure_count = build_exam_submissions_zip(session, exam_id)
    except ExportBusyError as exc:
        raise HTTPException(status_code=429, detail=public_error_message(exc, "Request failed")) from exc
    except ExportLimitError as exc:
        raise HTTPException(status_code=413, detail=public_error_message(exc, "Request failed")) from exc
    from urllib.parse import quote

    safe_title = (exam.title or f"exam-{exam_id}").strip() or f"exam-{exam_id}"
    ascii_fallback = f"exam-{exam_id}-submissions.zip"
    quoted_filename = quote(f"{safe_title}-评分说明.zip", safe="")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_fallback}"; '
            f"filename*=UTF-8''{quoted_filename}"
        ),
        "X-Submission-Total": str(total),
        "X-Submission-Failures": str(failure_count),
    }
    return Response(content=zip_bytes, media_type="application/zip", headers=headers)


def _load_exam_or_404(session: Session, exam_id: int) -> Exam:
    try:
        return load_exam_detail(session, exam_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=public_error_message(exc, "Request failed")) from exc


@router.delete("/{exam_id}")
def delete_exam(
    exam_id: int,
    session: Session = Depends(get_db),
    _: None = Depends(require_admin_token),
):
    exam = _load_exam_or_404(session, exam_id)
    file_paths = [exam_file.storage_path for exam_file in exam.files]
    tree_paths = [f"rendered/exams/{exam.id}"]
    for submission in exam.submissions:
        file_paths.append(submission.original_pdf_path)
        tree_paths.append(f"rendered/submissions/{submission.id}")
    for batch in exam.batches:
        file_paths.append(batch.source_storage_path)
        tree_paths.append(f"rendered/batches/{batch.id}")
        for candidate in batch.candidates:
            if candidate.source_storage_path:
                file_paths.append(candidate.source_storage_path)
    session.delete(exam)
    session.commit()
    storage = get_storage_service()
    for file_path in _dedupe_storage_paths(file_paths):
        _remove_storage_file(storage, file_path)
    for tree_path in _dedupe_storage_paths(tree_paths):
        _remove_storage_tree(storage, tree_path)
    return {"message": f"Exam {exam_id} deleted"}


@router.delete("/{exam_id}/rubric/files/{file_id}")
def delete_rubric_file(
    exam_id: int,
    file_id: int,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    rubric_file = session.get(ExamFile, file_id)
    if rubric_file is None or rubric_file.exam_id != exam_id:
        raise HTTPException(status_code=404, detail="Rubric file not found")
    file_path = rubric_file.storage_path
    tree_path = f"rendered/exams/{exam_id}/rubric/{file_id}"
    session.delete(rubric_file)
    exam.needs_rubric_review = True
    session.commit()
    storage = get_storage_service()
    _remove_storage_file(storage, file_path)
    _remove_storage_tree(storage, tree_path)
    return {"message": f"Rubric file {file_id} deleted"}


def _load_rubric_item_or_404(session: Session, item_id: int) -> RubricItem:
    rubric_item = session.get(RubricItem, item_id)
    if rubric_item is None:
        raise HTTPException(status_code=404, detail=f"Rubric item {item_id} not found")
    return rubric_item


def _exam_file_to_read(exam_file: ExamFile):
    from app.schemas.exam import ExamFileRead

    return ExamFileRead.model_validate(exam_file)


async def _validate_pdf_upload_or_400(file: UploadFile) -> None:
    try:
        await validate_pdf_upload(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=public_error_message(exc, "Request failed")) from exc


def _dedupe_storage_paths(paths: list[str]) -> list[str]:
    return list(dict.fromkeys(paths))


def _remove_storage_file(storage, storage_path: str) -> None:
    try:
        storage.delete(storage_path)
    except Exception as exc:  # noqa: BLE001 - cleanup failures should not block API deletion
        logger.warning("Failed to delete storage file %s: %s", storage_path, exc)


def _remove_storage_tree(storage, storage_path: str) -> None:
    try:
        storage.delete_tree(storage_path)
    except Exception as exc:  # noqa: BLE001 - cleanup failures should not block API deletion
        logger.warning("Failed to delete storage directory %s: %s", storage_path, exc)
