from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin_token
from app.models import Answer
from app.schemas.submission import AnswerDetail, SubmissionOverride
from app.services.pipeline import PipelineConflictError, PipelineError, apply_teacher_override
from app.utils.errors import public_error_message

router = APIRouter(prefix="/answers", tags=["answers"])


@router.put("/{answer_id}/override", response_model=AnswerDetail)
def override_answer_score(
    answer_id: int,
    payload: SubmissionOverride,
    _: None = Depends(require_admin_token),
    session: Session = Depends(get_db),
):
    fields_set = payload.model_fields_set
    try:
        answer = apply_teacher_override(
            session=session,
            answer_id=answer_id,
            teacher_override_score=payload.teacher_override_score,
            teacher_comment=payload.teacher_comment,
            reviewed=payload.reviewed,
            update_teacher_override_score="teacher_override_score" in fields_set,
            update_teacher_comment="teacher_comment" in fields_set,
        )
    except PipelineConflictError as exc:
        raise HTTPException(status_code=409, detail=public_error_message(exc, "Answer update failed")) from exc
    except PipelineError as exc:
        raise HTTPException(status_code=404, detail=public_error_message(exc, "Answer update failed")) from exc
    return _serialize_answer(answer)


def _serialize_answer(answer: Answer) -> AnswerDetail:
    from app.schemas.exam import QuestionRead
    from app.schemas.submission import AnswerRubricResultRead

    payload = AnswerDetail.model_validate(
        {
            **answer.__dict__,
            "question": QuestionRead.model_validate(answer.question).model_dump(),
            "rubric_results": [
                AnswerRubricResultRead.model_validate(rubric_result).model_dump()
                for rubric_result in answer.rubric_results
            ],
            "effective_score": float(
                answer.teacher_override_score if answer.teacher_override_score is not None else answer.score
            ),
        }
    )
    return payload
