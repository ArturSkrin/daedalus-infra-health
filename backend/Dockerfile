FROM python:3.12-slim

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt

RUN pip install --no-cache-dir --root-user-action=ignore -r /app/backend/requirements.txt \
    && useradd --system --uid 10001 --no-create-home tracker \
    && mkdir /data && chown tracker /data

COPY backend /app/backend
COPY adapter /app/adapter
COPY mock_data /app/mock_data

# The service only reads its own files and answers GETs: no reason to be root.
USER tracker

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
