"""question number unique per exam

Revision ID: 0008_question_no_unique
Revises: 0007_teacher_finalized
Create Date: 2026-05-10 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0008_question_no_unique"
down_revision = "0007_teacher_finalized"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            """
            SELECT exam_id, lower(question_no) AS normalized_question_no, count(*) AS duplicate_count
            FROM questions
            GROUP BY exam_id, lower(question_no)
            HAVING count(*) > 1
            """
        )
    ).fetchall()
    if duplicates:
        examples = ", ".join(
            f"exam_id={row.exam_id} question_no={row.normalized_question_no} count={row.duplicate_count}"
            for row in duplicates[:5]
        )
        raise RuntimeError(f"Cannot add question uniqueness constraint while duplicates exist: {examples}")
    op.create_index(
        "uq_questions_exam_question_no",
        "questions",
        ["exam_id", sa.text("lower(question_no)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_questions_exam_question_no", table_name="questions")
