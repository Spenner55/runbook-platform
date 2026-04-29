FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/api/requirements/ /tmp/requirements/
RUN pip install --no-cache-dir -r /tmp/requirements/dev.txt

COPY apps/api /app
COPY packages/workflow-schema /packages/workflow-schema

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
