# QuizOCR Grader

AI-assisted grading platform for quiz and exam papers. Teachers upload a rubric PDF and one or more student PDFs, then review AI-extracted answers, rubric-item scoring, and manual overrides before exporting batch results.

## Stack

- Frontend: React, Vite, TypeScript, Tailwind CSS
- Backend: FastAPI, SQLAlchemy, Alembic, Celery
- Database: PostgreSQL
- Queue: Redis + Celery
- PDF rendering: PyMuPDF
- Local storage: filesystem-backed storage abstraction
- AI gateway: OpenAI-compatible HTTP API

## Local setup

1. Copy `.env.example` to `.env` and fill in your AI gateway credentials.
2. Start the stack:

```bash
docker compose up --build
```

3. Open the app at `http://localhost:5173`.

## Backend flow

1. Create an exam.
2. Upload the rubric PDF.
3. Parse the rubric into questions and rubric items.
4. Edit the rubric as needed.
5. Upload student PDFs.
6. Queue processing for each submission.
7. Review extracted answers, rubric evidence, and override scores.
8. Export CSV or Excel from the batch results page.

## Environment variables

- `AI_BASE_URL`
- `AI_API_KEY`
- `AI_VISION_MODEL`
- `AI_GRADING_MODEL`
- `AI_REQUEST_TIMEOUT_SECONDS`
- `AI_MAX_RETRIES`
- `AI_RETRY_BACKOFF_SECONDS`
- `DATABASE_URL`
- `REDIS_URL`
- `DOCKER_DATABASE_URL`
- `DOCKER_REDIS_URL`
- `STORAGE_DIR`
- `MAX_UPLOAD_MB`
- `RENDER_DPI`
- `CORS_ORIGINS`
- `VITE_API_BASE_URL`

## API highlights

- `POST /api/exams`
- `POST /api/exams/{exam_id}/rubric/upload`
- `POST /api/exams/{exam_id}/rubric/parse`
- `POST /api/exams/{exam_id}/submissions/upload`
- `POST /api/submissions/{submission_id}/process`
- `PUT /api/answers/{answer_id}/override`
- `GET /api/exams/{exam_id}/results`
- `GET /api/exams/{exam_id}/export.csv`
- `GET /api/exams/{exam_id}/export.xlsx`

## Notes

- The AI never grades autonomously without storing rubric-item evidence.
- Low confidence or empty extraction marks a submission for human review.
- Raw AI responses are stored for debugging and auditability.
