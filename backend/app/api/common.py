from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Answer, BatchSplitCandidate, Exam, Question, RubricItem, Submission, SubmissionBatch
from app.schemas.exam import ExamDetail, ExamListItem, QuestionRead, RubricItemRead
from app.schemas.submission import (
    AnswerDetail,
    AnswerRubricResultRead,
    SubmissionDetail,
    SubmissionPageRead,
    SubmissionSummary,
)
from app.utils.score import clamp_score


def load_exam_detail(session: Session, exam_id: int) -> Exam:
    stmt = (
        select(Exam)
        .where(Exam.id == exam_id)
        .options(
            selectinload(Exam.files),
            selectinload(Exam.questions).selectinload(Question.rubric_items),
            selectinload(Exam.submissions),
            selectinload(Exam.batches).selectinload(SubmissionBatch.candidates).selectinload(BatchSplitCandidate.submission),
            selectinload(Exam.roster_entries),
        )
    )
    exam = session.execute(stmt).scalar_one_or_none()
    if exam is None:
        raise LookupError(f"Exam {exam_id} not found")
    return exam


def load_submission_detail(session: Session, submission_id: int) -> Submission:
    stmt = (
        select(Submission)
        .where(Submission.id == submission_id)
        .options(
            selectinload(Submission.exam)
            .selectinload(Exam.questions)
            .selectinload(Question.rubric_items),
            selectinload(Submission.pages),
            selectinload(Submission.answers)
            .selectinload(Answer.question)
            .selectinload(Question.rubric_items),
            selectinload(Submission.answers).selectinload(Answer.rubric_results),
        )
    )
    submission = session.execute(stmt).scalar_one_or_none()
    if submission is None:
        raise LookupError(f"Submission {submission_id} not found")
    return submission


def load_question_detail(session: Session, question_id: int) -> Question:
    stmt = (
        select(Question)
        .where(Question.id == question_id)
        .options(selectinload(Question.rubric_items), selectinload(Question.exam))
    )
    question = session.execute(stmt).scalar_one_or_none()
    if question is None:
        raise LookupError(f"Question {question_id} not found")
    return question


def load_rubric_item_detail(session: Session, item_id: int) -> RubricItem:
    stmt = select(RubricItem).where(RubricItem.id == item_id).options(selectinload(RubricItem.question))
    item = session.execute(stmt).scalar_one_or_none()
    if item is None:
        raise LookupError(f"Rubric item {item_id} not found")
    return item


def recalculate_exam_total(session: Session, exam_id: int) -> Decimal:
    total = session.execute(
        select(func.coalesce(func.sum(Question.max_score), 0)).where(Question.exam_id == exam_id)
    ).scalar_one()
    exam = session.get(Exam, exam_id)
    if exam is not None:
        exam.total_score = Decimal(str(total))
        session.flush()
    return Decimal(str(total))


def recalculate_question_and_exam_totals(session: Session, question_id: int) -> Decimal:
    question = load_question_detail(session, question_id)
    total = sum((Decimal(str(rubric_item.max_score)) for rubric_item in question.rubric_items), Decimal("0"))
    question.max_score = total
    session.flush()
    recalculate_exam_total(session, question.exam_id)
    return total


def effective_answer_score(answer: Answer) -> Decimal:
    if answer.teacher_override_score is not None:
        return answer.teacher_override_score
    return answer.score


def serialize_exam_detail(exam: Exam) -> ExamDetail:
    return ExamDetail.model_validate(exam)


def serialize_exam_list_item(exam: Exam, question_count: int, submission_count: int) -> ExamListItem:
    payload = ExamListItem.model_validate(exam).model_dump()
    payload["question_count"] = question_count
    payload["submission_count"] = submission_count
    return ExamListItem.model_validate(payload)


def serialize_question(question: Question) -> QuestionRead:
    return QuestionRead.model_validate(question)


def serialize_rubric_item(rubric_item: RubricItem) -> RubricItemRead:
    return RubricItemRead.model_validate(rubric_item)


def serialize_submission_summary(submission: Submission) -> SubmissionSummary:
    return SubmissionSummary.model_validate(submission)


def serialize_submission_detail(submission: Submission) -> SubmissionDetail:
    base_payload = SubmissionSummary.model_validate(submission).model_dump()
    base_payload["exam"] = ExamDetail.model_validate(submission.exam).model_dump()
    base_payload["pages"] = [SubmissionPageRead.model_validate(page).model_dump() for page in submission.pages]
    answer_payloads: list[dict] = []
    for answer in submission.answers:
        answer_payload = AnswerDetail.model_validate(
            {
                **answer.__dict__,
                "question": QuestionRead.model_validate(answer.question).model_dump(),
                "rubric_results": [
                    AnswerRubricResultRead.model_validate(rubric_result).model_dump()
                    for rubric_result in answer.rubric_results
                ],
                "effective_score": float(effective_answer_score(answer)),
            }
        ).model_dump()
        answer_payloads.append(answer_payload)
    base_payload["answers"] = answer_payloads
    return SubmissionDetail.model_validate(base_payload)


def submission_needs_review(submission: Submission) -> bool:
    return any(answer.needs_human_review or answer.confidence == "low" for answer in submission.answers)


def submission_effective_total(submission: Submission) -> Decimal:
    total = Decimal("0")
    for answer in submission.answers:
        total += effective_answer_score(answer)
    return total


def clamp_question_score(score: float, max_score: float) -> float:
    return clamp_score(score, 0.0, max_score)
