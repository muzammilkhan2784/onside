# syntax=docker/dockerfile:1.7
# Onside backend: API, ingest workers, reclaimer, replay service and the
# one-shot bootstrap all run from this image with different commands.

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# libgomp is LightGBM's OpenMP runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

FROM base AS deps
COPY backend/pyproject.toml backend/pyproject.toml
RUN mkdir -p backend/onside && touch backend/onside/__init__.py \
 && pip install --prefix=/install ./backend

FROM base AS runtime
COPY --from=deps /install /usr/local
COPY backend/onside /app/onside
COPY models /app/models
RUN useradd --create-home --uid 10001 onside && mkdir -p /app/data && chown -R onside /app
USER onside
ENV ONSIDE_DATA_DIR=/app/data ONSIDE_MODEL_DIR=/app/models
EXPOSE 8080
# No HEALTHCHECK here: the same image runs the API, the workers, the reclaimer
# and the replay service, and only the API serves HTTP. Compose and the ECS
# task definitions set the check that fits each role.
CMD ["uvicorn", "onside.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]

FROM runtime AS dev
USER root
COPY backend/tests /app/tests
RUN pip install "pytest>=8" "hypothesis>=6" "moto[dynamodb]>=5" "fakeredis>=2.26" ruff mypy
USER onside
