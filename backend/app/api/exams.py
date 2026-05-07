from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.common import (
    load_exam_detail,
    load_question_detail,
    recalculate_exam_total,
    recalculate_question_and_exam_totals,
    serialize_exam_detail,
    serialize_exam_list_item,
    serialize_question,
    serialize_rubric_item,
)
from app.api.deps import get_db
from app.core.config import settings
from app.models import Exam, ExamFile, Question, RubricItem, Submission
from app.schemas.exam import (
    ExamCreate,
    ExamDetail,
    ExamListItem,
    ExamResultsResponse,
    ExamUpdate,
    QuestionCreate,
    QuestionRead,
    QuestionUpdate,
    RubricItemCreate,
    RubricItemRead,
    RubricItemUpdate,
)
from app.schemas.submission import PageUploadResponse, SubmissionUploadResponse, SubmissionSummary
from app.services.export import build_exam_results_csv, build_exam_results_data, build_exam_results_xlsx
from app.services.pipeline import PipelineError, parse_rubric_for_exam
from app.storage.local import get_storage_service
from app.utils.files import validate_pdf_upload

router = APIRouter(prefix="/exams", tags=["exams"])


@router.post("", response_model=ExamDetail)
def create_exam(payload: ExamCreate, session: Session = Depends(get_db)):
    exam = Exam(title=payload.title, description=payload.description)
    session.add(exam)
    session.commit()
    return serialize_exam_detail(load_exam_detail(session, exam.id))


@router.get("", response_model=list[ExamListItem])
def list_exams(session: Session = Depends(get_db)):
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
def get_exam_detail(exam_id: int, session: Session = Depends(get_db)):
    exam = _load_exam_or_404(session, exam_id)
    return serialize_exam_detail(exam)


@router.post("/{exam_id}/rubric/upload", response_model=PageUploadResponse)
async def upload_rubric_pdf(
    exam_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    await validate_pdf_upload(file)
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Uploaded rubric PDF is too large")
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
    session: Session = Depends(get_db),
):
    try:
        exam = parse_rubric_for_exam(session, exam_id, exam_file_id=exam_file_id)
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_exam_detail(exam)


@router.get("/{exam_id}/questions", response_model=list[QuestionRead])
def list_questions(exam_id: int, session: Session = Depends(get_db)):
    exam = _load_exam_or_404(session, exam_id)
    return [serialize_question(question) for question in exam.questions]


@router.put("/questions/{question_id}", response_model=QuestionRead)
def update_question(question_id: int, payload: QuestionUpdate, session: Session = Depends(get_db)):
    question = load_question_detail(session, question_id)
    if payload.question_no is not None:
        question.question_no = payload.question_no
    if payload.title is not None:
        question.title = payload.title
    if payload.max_score is not None:
        question.max_score = Decimal(str(payload.max_score))
    if payload.order_index is not None:
        question.order_index = payload.order_index
    recalculate_exam_total(session, question.exam_id)
    session.commit()
    return serialize_question(load_question_detail(session, question_id))


@router.post("/questions/{question_id}/rubric-items", response_model=QuestionRead)
def create_rubric_item(
    question_id: int,
    payload: RubricItemCreate,
    session: Session = Depends(get_db),
):
    question = load_question_detail(session, question_id)
    rubric_item = RubricItem(
        question_id=question.id,
        description=payload.description,
        max_score=Decimal(str(payload.max_score)),
        keywords=payload.keywords,
        order_index=payload.order_index,
    )
    session.add(rubric_item)
    recalculate_question_and_exam_totals(session, question_id)
    session.commit()
    return serialize_question(load_question_detail(session, question_id))


@router.put("/rubric-items/{item_id}", response_model=QuestionRead)
def update_rubric_item(
    item_id: int,
    payload: RubricItemUpdate,
    session: Session = Depends(get_db),
):
    rubric_item = _load_rubric_item_or_404(session, item_id)
    if payload.description is not None:
        rubric_item.description = payload.description
    if payload.max_score is not None:
        rubric_item.max_score = Decimal(str(payload.max_score))
    if payload.keywords is not None:
        rubric_item.keywords = payload.keywords
    if payload.order_index is not None:
        rubric_item.order_index = payload.order_index
    recalculate_question_and_exam_totals(session, rubric_item.question_id)
    session.commit()
    return serialize_question(load_question_detail(session, rubric_item.question_id))


@router.delete("/rubric-items/{item_id}")
def delete_rubric_item(item_id: int, session: Session = Depends(get_db)):
    rubric_item = _load_rubric_item_or_404(session, item_id)
    question_id = rubric_item.question_id
    session.delete(rubric_item)
    recalculate_question_and_exam_totals(session, question_id)
    session.commit()
    return {"message": "Rubric item deleted"}


@router.post("/{exam_id}/submissions/upload", response_model=SubmissionUploadResponse)
async def upload_submissions(
    exam_id: int,
    files: list[UploadFile] = File(...),
    student_name: str | None = Form(default=None),
    student_id: str | None = Form(default=None),
    session: Session = Depends(get_db),
):
    exam = _load_exam_or_404(session, exam_id)
    storage = get_storage_service()
    created_submissions: list[SubmissionSummary] = []
    for file in files:
        await validate_pdf_upload(file)
        data = await file.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Uploaded submission PDF is too large")
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
def get_exam_results(exam_id: int, session: Session = Depends(get_db)):
    from app.schemas.exam import ExamDetail, ExamResultRow, QuestionRead

    data = build_exam_results_data(session, exam_id)
    exam = data["exam"]
    questions = [QuestionRead.model_validate(question) for question in data["questions"]]
    rows = [ExamResultRow.model_validate(row) for row in data["rows"]]
    return ExamResultsResponse(
        exam=ExamDetail.model_validate(exam),
        questions=questions,
        rows=rows,
    )


@router.get("/{exam_id}/export.csv")
def export_exam_results_csv(exam_id: int, session: Session = Depends(get_db)):
    csv_content = build_exam_results_csv(session, exam_id)
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="exam-{exam_id}-results.csv"'},
    )


@router.get("/{exam_id}/export.xlsx")
def export_exam_results_xlsx(exam_id: int, session: Session = Depends(get_db)):
    xlsx_bytes = build_exam_results_xlsx(session, exam_id)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="exam-{exam_id}-results.xlsx"'},
    )


def _load_exam_or_404(session: Session, exam_id: int) -> Exam:
    try:
        return load_exam_detail(session, exam_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _load_rubric_item_or_404(session: Session, item_id: int) -> RubricItem:
    rubric_item = session.get(RubricItem, item_id)
    if rubric_item is None:
        raise HTTPException(status_code=404, detail=f"Rubric item {item_id} not found")
    return rubric_item


def _exam_file_to_read(exam_file: ExamFile):
    from app.schemas.exam import ExamFileRead

    return ExamFileRead.model_validate(exam_file)
