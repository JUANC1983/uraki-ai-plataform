# Dockerfile — URAKI AI Platform API
FROM python:3.12-slim

# Security: non-root user
RUN groupadd -r uraki && useradd -r -g uraki uraki

WORKDIR /app

# System dependencies for pdfplumber and asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for storage and logs
RUN mkdir -p ./storage ./logs && chown -R uraki:uraki /app

USER uraki

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
