FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

COPY README.md ./README.md
COPY prompts ./prompts
COPY backend ./backend

RUN pip install --upgrade pip && pip install -e ./backend

WORKDIR /workspace/backend

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
