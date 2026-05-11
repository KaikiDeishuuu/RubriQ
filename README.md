# RubriQ

AI-assisted quiz and exam grading platform for rubric-based review.

RubriQ helps teachers turn rubric PDFs and student submissions into auditable grading results. It extracts rubric items, reads student answers, stores evidence for every score, supports manual overrides, and exports batch results for review.

## What it does

| Area | Capability |
| --- | --- |
| Rubric setup | Upload a rubric PDF, parse questions and rubric items, then edit the extracted structure before grading. |
| Student submissions | Upload individual PDFs or batch archives, split submissions, extract answers, and bind pages to roster entries when available. |
| AI-assisted scoring | Score answers against rubric items through OpenAI-compatible model providers, with fallback chains for vision and grading tasks. |
| Teacher review | Review extracted answers, evidence, confidence flags, score deltas, and manual overrides before final export. |
| Export | Download CSV, Excel, deduction reports, or submission ZIP bundles from the batch results page. |

## Tech stack

| Layer | Tools |
| --- | --- |
| Frontend | React, Vite, TypeScript, Tailwind CSS |
| Backend | FastAPI, SQLAlchemy, Alembic |
| Workers | Celery with Redis |
| Database | PostgreSQL |
| PDF rendering | PyMuPDF |
| Storage | Filesystem-backed storage abstraction |
| AI gateway | OpenAI-compatible HTTP API |

## Quick start

1. Copy the example environment file and fill in AI provider credentials:

```bash
cp .env.example .env
```

2. Start the full stack:

```bash
docker compose up --build
```

3. Open the frontend:

```text
http://localhost:5173
```

The default local setup uses PostgreSQL, Redis, the backend API, Celery workers, and the Vite frontend from `docker-compose.yml`.

## Grading workflow

1. Create an exam.
2. Upload the rubric PDF.
3. Parse the rubric into questions and rubric items.
4. Review and edit the parsed rubric.
5. Optionally upload and confirm an exam roster.
6. Upload student PDFs or a batch archive.
7. Split and bind submissions to students.
8. Queue processing for answer extraction and grading.
9. Review extracted answers, rubric evidence, confidence flags, and overrides.
10. Export CSV, Excel, deduction reports, or submission bundles.

## Configuration

RubriQ reads runtime configuration from `.env`. Start from `.env.example`; the example file contains bilingual inline guidance and safe placeholder values only.

### Minimum AI setup

| Variable | Purpose |
| --- | --- |
| `AI_BASE_URL` | Default OpenAI-compatible gateway URL, such as a provider `/v1` endpoint or relay. |
| `AI_API_KEY` | Default API key for the AI gateway. Keep real keys in `.env` or deployment secrets only. |
| `AI_VISION_MODEL` | Vision-capable model for rubric parsing, answer extraction, split-header detection, roster extraction, and image-grounded review. |
| `AI_GRADING_MODEL` | Text model for rubric-based scoring. |

If vision and grading use different providers, set `AI_VISION_BASE_URL` / `AI_VISION_API_KEY` and `AI_GRADING_BASE_URL` / `AI_GRADING_API_KEY` to override the default gateway per route.

### Model fallback chains

Fallback chain variables are single-line JSON arrays. Earlier candidates are tried first; later candidates are used only when earlier ones fail.

| Variable | Route |
| --- | --- |
| `AI_VISION_CHAIN` | Default vision fallback chain. |
| `AI_VISION_RUBRIC_CHAIN` | Rubric parsing. |
| `AI_VISION_STUDENT_EXTRACTION_CHAIN` | Student answer extraction. |
| `AI_VISION_SPLIT_HEADER_CHAIN` | Batch split header detection. |
| `AI_VISION_GRADING_REVIEW_CHAIN` | Image-grounded grading review. |
| `AI_VISION_ROSTER_CHAIN` | PDF roster extraction. |
| `AI_GRADING_CHAIN` | Fast text grading. |
| `AI_GRADING_REVIEW_CHAIN` | Optional text-only quality review. |

Example:

```text
AI_GRADING_CHAIN=[{"model":"gpt-4.1"},{"model":"deepseek-chat","base_url":"https://api.deepseek.com/v1","api_key":"sk-your-deepseek-key"}]
```

Candidates may include `base_url`, `api_key`, and `supports_vision`. Image routes skip candidates with `supports_vision:false`. Task-specific chains override `AI_VISION_CHAIN`; if no chain is configured, RubriQ uses the single-model variables.

### Quality review and scoring strictness

| Variable | Purpose |
| --- | --- |
| `AI_GRADING_REVIEW_ENABLED` | Enables an optional second review pass for low-confidence, model-flagged, weak-evidence, high-delta, or high-variance answers. |
| `AI_GRADING_REVIEW_MODEL` | Text-only review model when a full review chain is not configured. |
| `AI_GRADING_STRICTNESS` | `strict`, `moderate`, or `lenient` evidence-based scoring. |

Use text-only models such as DeepSeek in `AI_GRADING_REVIEW_MODEL` or `AI_GRADING_REVIEW_CHAIN`. Use image-capable models in `AI_VISION_GRADING_REVIEW_CHAIN`.

### OCR preprocessing

`OCR_PREPROCESS_*` controls the optional PaddleOCR preprocessing layer. It is disabled by default. When enabled, OCR text is used only as reference text for vision prompts; it does not replace image-grounded model judgment.

Keep `PADDLE_OCR_API_KEY` only in `.env` or deployment secrets. Do not commit real OCR or model provider tokens.

### Authentication and frontend access

| Variable | Purpose |
| --- | --- |
| `ADMIN_API_TOKEN` | Shared administrator token for protected endpoints. |
| `ADMIN_API_TOKEN_REQUIRED` | Set to `true` to require bearer-token authentication. |
| `CORS_ORIGINS` | Allowed frontend origins, for example `http://localhost:5173,http://127.0.0.1:5173`. |
| `VITE_API_BASE_URL` | Frontend API base URL, usually `http://localhost:8000/api`. |

When token auth is enabled, the frontend `/login` page stores the token in `localStorage` and attaches `Authorization: Bearer <token>` to protected requests. Image fetches use blob URLs because browsers cannot send custom headers on plain `<img src>` requests.

### Storage, database, and queue

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Backend database URL for local non-Docker runs. |
| `REDIS_URL` | Backend Redis URL for local non-Docker runs. |
| `DOCKER_DATABASE_URL` | Database URL used inside Docker Compose services. |
| `DOCKER_REDIS_URL` | Redis URL used inside Docker Compose services. |
| `STORAGE_DIR` | Filesystem storage directory. |
| `MAX_UPLOAD_MB` | Maximum upload size in MiB. |
| `RENDER_DPI` | PDF render DPI for image processing. |

### Operational limits

| Variable | Default | Purpose |
| --- | --- | --- |
| `SUBMISSIONS_UPLOAD_MAX_FILES` | `20` | Caps files in a single submission upload request. |
| `BATCH_ZIP_MAX_ENTRIES` | `300` | Caps entries in a batch ZIP archive. |
| `BATCH_ZIP_MAX_UNCOMPRESSED_BYTES` | `2147483648` | Caps total uncompressed ZIP size. |
| `EXPORT_GLOBAL_CONCURRENCY` | `2` | Bounds expensive export work. |
| `EXPORT_SUBMISSIONS_ZIP_MAX_SUBMISSIONS` | `200` | Caps submissions included in exported ZIP bundles. |
| `AI_GRADING_BATCH_SIZE` | `5` | Controls how many submissions a batch grading run dispatches per chunk. |
| `GRADING_STALE_SUBMISSION_SECONDS` | `1200` | Marks stale active submission jobs failed after worker shutdown or hard kill. |
| `GRADING_STALE_BATCH_REVIEW_SECONDS` | `3000` | Marks stale batch review jobs failed after worker shutdown or hard kill. |

Clients receive `429` or `413` when concurrency, upload, or archive limits are exceeded.

## API reference

All endpoints are served under the configured API prefix, usually `/api`.

### Exams

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/exams` | Create an exam. |
| `GET` | `/api/exams/{exam_id}/results` | Read grading results. |

### Rubrics

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/exams/{exam_id}/rubric/upload` | Upload a rubric PDF. |
| `POST` | `/api/exams/{exam_id}/rubric/parse` | Parse rubric questions and criteria. |

### Rosters

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/exams/{exam_id}/roster/upload` | Upload a roster PDF, CSV, or Excel file. |
| `POST` | `/api/exams/{exam_id}/roster/parse` | Parse uploaded roster data. |
| `PUT` | `/api/exams/{exam_id}/roster` | Update roster entries. |
| `POST` | `/api/exams/{exam_id}/roster/confirm` | Confirm roster entries for matching. |
| `GET` | `/api/exams/{exam_id}/roster` | Read roster entries. |

### Submissions and answers

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/exams/{exam_id}/submissions/upload` | Upload student submissions. |
| `POST` | `/api/submissions/{submission_id}/process` | Queue processing for a submission. |
| `PUT` | `/api/answers/{answer_id}/override` | Apply a manual score override. |

### Exports

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/exams/{exam_id}/export.csv` | Export results as CSV. |
| `GET` | `/api/exams/{exam_id}/export.xlsx` | Export results as Excel. |
| `GET` | `/api/exams/{exam_id}/export-deductions.csv` | Export deduction details as CSV. |
| `GET` | `/api/exams/{exam_id}/export-deductions.xlsx` | Export deduction details as Excel. |
| `GET` | `/api/exams/{exam_id}/export-submissions.zip` | Export submission files as a ZIP bundle. |

### Authentication

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/auth/check` | Check whether the current token is valid. |
| `GET` | `/api/auth/status` | Check whether token authentication is required. |

## Operations and safety

- AI scoring is evidence-based: rubric-item evidence is stored with each score.
- Low-confidence extraction, empty extraction, weak evidence, and review-triggered answers are flagged for teacher review.
- Raw AI responses are stored for debugging and auditability.
- Optional exam rosters can be uploaded before splitting. Confirmed rosters let the fixed-page splitter bind candidates by order, while auto-splitting cross-validates extracted identities against roster entries.
- PDF rosters use the vision pipeline. CSV and Excel rosters skip model extraction.
- Upload, ZIP ingestion, export, and grading concurrency limits are configurable to protect shared deployments.
- Keep real API keys, administrator tokens, and OCR provider tokens out of git.

## License

RubriQ is licensed under the Apache-2.0 License. See [`LICENSE`](LICENSE) for details.
