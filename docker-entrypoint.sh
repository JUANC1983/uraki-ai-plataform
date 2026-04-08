#!/usr/bin/env bash
# docker-entrypoint.sh
# Runs Alembic migrations then starts the API server.
# Used as the Docker CMD / ENTRYPOINT for production containers.
#
# Required environment variables (set in docker-compose or ECS task definition):
#   SECRET_KEY      — random hex string, min 32 chars
#   DATABASE_URL    — postgresql+asyncpg://user:pass@host:5432/db
#   ALLOWED_ORIGINS — comma-separated list of allowed CORS origins
#
# Optional:
#   WORKERS         — number of uvicorn workers (default: 2)
#   PORT            — port to listen on (default: 8000)

set -euo pipefail

WORKERS="${WORKERS:-2}"
PORT="${PORT:-8000}"

echo "==> Running Alembic migrations..."
alembic upgrade head
echo "==> Migrations complete."

echo "==> Starting URAKI API (workers=${WORKERS}, port=${PORT})..."
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers "${WORKERS}" \
    --log-level info \
    --no-access-log
