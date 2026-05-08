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
- `AI_VISION_BASE_URL`, `AI_VISION_API_KEY`
- `AI_GRADING_BASE_URL`, `AI_GRADING_API_KEY`
- `AI_VISION_MODEL`
- `AI_GRADING_MODEL`
- `AI_VISION_CHAIN`
- `AI_VISION_RUBRIC_CHAIN`
- `AI_VISION_STUDENT_EXTRACTION_CHAIN`
- `AI_VISION_SPLIT_HEADER_CHAIN`
- `AI_VISION_GRADING_REVIEW_CHAIN`
- `AI_GRADING_CHAIN`
- `AI_GRADING_REVIEW_ENABLED`
- `AI_GRADING_REVIEW_MODEL`
- `AI_GRADING_REVIEW_CHAIN`
- `AI_GRADING_REVIEW_SCORE_DELTA_RATIO`
- `AI_GRADING_REVIEW_VARIANCE_MIN_ANSWERS`
- `AI_GRADING_REVIEW_VARIANCE_RANGE_RATIO`
- `AI_GRADING_CONCURRENCY`
- `AI_GRADING_GLOBAL_CONCURRENCY`
- `AI_GRADING_STRICTNESS`
- `AI_REQUEST_TIMEOUT_SECONDS`
- `AI_MAX_RETRIES`
- `AI_RETRY_BACKOFF_SECONDS`
- `OCR_PREPROCESS_ENABLED`
- `OCR_PREPROCESS_RUBRIC_ENABLED`
- `OCR_PREPROCESS_STUDENT_ENABLED`
- `OCR_PREPROCESS_SPLIT_HEADER_ENABLED`
- `PADDLE_OCR_BASE_URL`
- `PADDLE_OCR_API_KEY`
- `PADDLE_OCR_MODEL`
- `PADDLE_OCR_TIMEOUT_SECONDS`
- `PADDLE_OCR_POLL_INTERVAL_SECONDS`
- `PADDLE_OCR_MAX_POLL_SECONDS`
- `OCR_MIN_TEXT_CHARS_FOR_REFERENCE`
- `OCR_SPLIT_HEADER_MIN_CONFIDENCE`
- `OCR_SPLIT_HEADER_CONCURRENCY`
- `DATABASE_URL`
- `REDIS_URL`
- `DOCKER_DATABASE_URL`
- `DOCKER_REDIS_URL`
- `STORAGE_DIR`
- `MAX_UPLOAD_MB`
- `RENDER_DPI`
- `CORS_ORIGINS`
- `VITE_API_BASE_URL`

`AI_VISION_*` is used for rubric parsing, student answer OCR, batch split header detection, and image-grounded grading review; `AI_GRADING_*` is used for text scoring. Chain variables are JSON arrays of ordered candidates, for example `[{"model":"gemini-2.5-pro","base_url":"https://generativelanguage.googleapis.com/v1beta/openai","api_key":"..."},{"model":"gpt-4o"}]`. Candidates may include `supports_vision`; image routes skip candidates with `supports_vision:false`. Task-specific chains override `AI_VISION_CHAIN`; if no chain is configured, the legacy single-model variables are used. Model-chain fallback happens before the existing business fallback that marks answers for human review.

`AI_GRADING_CHAIN` is technical fallback for the fast grading pass: later candidates are used only if earlier candidates fail. `AI_GRADING_REVIEW_*` controls the optional text-only quality review pass: when enabled, low-confidence, model-flagged, weak-evidence, high score delta, or high batch-variance answers can be regraded with a stronger text model before teacher review. Put text-only models such as DeepSeek in `AI_GRADING_REVIEW_MODEL` / `AI_GRADING_REVIEW_CHAIN`; put image-capable review models in `AI_VISION_GRADING_REVIEW_CHAIN`.

`AI_GRADING_STRICTNESS` controls evidence-based scoring strictness for both fast grading and review grading. `strict` gives credit only for explicit rubric evidence, `moderate` gives fair evidence-based partial credit, and `lenient` gives generous partial credit for relevant attempts only; unrelated or unsupported non-empty answers are not automatically lifted above 0.

`OCR_PREPROCESS_*` controls the optional PaddleOCR pre-processing layer. It is disabled by default; when enabled, OCR text is used only as reference text for vision prompts, and batch split header OCR falls back to the existing vision model when text is missing or low confidence. `OCR_SPLIT_HEADER_CONCURRENCY` limits concurrent header OCR/fallback calls during batch splitting to avoid overloading the provider. Keep `PADDLE_OCR_API_KEY` only in `.env` or deployment secrets, never in committed files or logs.

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
