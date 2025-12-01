# Production Dockerfile for FastAPI + Uvicorn on Cloud Run
FROM python:3.11-slim as base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install system dependencies required for building Python packages and PDF/DOCX helpers
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libxml2 \
        libxslt1.1 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-test.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
