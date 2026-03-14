# Dockerfile — works on Windows (Docker Desktop), macOS, and Linux.
# Docker always runs Linux containers regardless of host OS,
# so apt-get here is correct and expected even on Windows.

FROM python:3.12-slim

WORKDIR /app

# System deps needed to compile psycopg2 (the sync Postgres driver used by Alembic)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first — this layer is cached unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
