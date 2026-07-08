# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /app

ARG REQUIREMENTS_FILE=requirements-docker.txt

ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_PROGRESS_BAR=off

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# `faster-whisper` uses PyAV for decoding, and real mobile `.mp4` files may use
# container/codec combinations that are easier to diagnose or convert when the
# FFmpeg CLI is present in the runtime image.
COPY requirements.txt .
COPY requirements-docker.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip setuptools wheel && \
    pip install -r ${REQUIREMENTS_FILE}

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
