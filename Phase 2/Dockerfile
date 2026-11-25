FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scripts ./scripts
COPY scripts/ingest.py scripts/profile_raw.py scripts/clean_transform.py ./
COPY sql ./sql
COPY tests ./tests

CMD ["python", "ingest.py"]
