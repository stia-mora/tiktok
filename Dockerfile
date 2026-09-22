FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements-local.lock.txt ./
RUN pip install --no-cache-dir -r requirements-local.lock.txt

COPY --chown=app:app . ./
RUN mkdir -p /app/output && chown app:app /app/output

FROM base AS dashboard
USER app

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]

FROM mcr.microsoft.com/playwright/python:v1.63.0-noble AS analyzer

# This image already contains a Playwright-compatible Chromium and its OS
# libraries. Installing a browser while building exhausted the 2 GB server.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-local.lock.txt requirements-analysis.lock.txt ./
RUN pip install --no-cache-dir -r requirements-analysis.lock.txt

COPY . ./
RUN mkdir -p /app/output

CMD ["python", "analysis_pipeline.py", "--work", "1"]
