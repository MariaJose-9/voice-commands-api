# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /app

ARG REQUIREMENTS_FILE=requirements-docker.txt

ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_PROGRESS_BAR=off

# `faster-whisper` depends on PyAV wheels, which already bundle the FFmpeg
# libraries needed for `.ogg` / `.mp3` decoding in this setup. For that reason
# we keep the image slim and avoid extra system packages unless a future build
# or target environment proves they are necessary.
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
