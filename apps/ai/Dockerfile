FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/ai/requirements/ /tmp/requirements/
RUN pip install --no-cache-dir -r /tmp/requirements/dev.txt

COPY apps/ai /app

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
