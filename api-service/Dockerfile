# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY recon/ ./recon/

# non-root: Azure Container Apps and App Service both honour this
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

# App Service and Container Apps inject PORT; default to 8000 elsewhere
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",8000)}/healthz')"

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
