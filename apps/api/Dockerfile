# Backend image (api + workers share this). Immutable, non-root.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Workspace packages first (better layer caching).
COPY packages /packages
COPY apps/api/pyproject.toml /app/pyproject.toml

RUN pip install --upgrade pip \
    && pip install -e /packages/shared-types \
    && pip install -e /packages/clinical-models \
    && pip install -e "/app[dev]"

COPY apps/api /app

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
