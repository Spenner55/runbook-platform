FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/runner/requirements/ /tmp/requirements/
RUN pip install --no-cache-dir -r /tmp/requirements/dev.txt

COPY apps/runner /app

CMD ["python", "-m", "runner.main"]
