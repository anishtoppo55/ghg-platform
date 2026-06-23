FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY frontend ./frontend

EXPOSE 8000

# Seed the database on container start, then launch the API (which also serves /frontend)
CMD ["sh", "-c", "python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
