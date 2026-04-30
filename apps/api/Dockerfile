FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/api/requirements/ /tmp/requirements/
RUN pip install --no-cache-dir -r /tmp/requirements/dev.txt

COPY apps/api /app
COPY packages/workflow-schema /packages/workflow-schema

EXPOSE 8000

# Phase 10.8: uvicorn replaces manage.py runserver to support ASGI async views (SSE streaming).
# --workers 1 is required: ExecutionEventBus is a process-local in-memory singleton.
# Multi-worker or horizontal scaling requires an external event bus (Phase 10.9/10.10).
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
