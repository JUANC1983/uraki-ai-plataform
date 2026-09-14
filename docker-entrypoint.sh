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
#   WORKERS         — number of uvicorn workers (default: 1)
#   PORT            — port to listen on (default: 8000)
#   RUN_MIGRATIONS  — run Alembic before the supplied command (default: true)
#   RUN_SCHEDULER   — start in-process scheduler jobs (default: true)

set -euo pipefail

WORKERS="${WORKERS:-1}"
PORT="${PORT:-8000}"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"
RUN_SCHEDULER="${RUN_SCHEDULER:-true}"

if [[ "${RUN_SCHEDULER,,}" == "true" && "${WORKERS}" != "1" ]]; then
    echo "ERROR: RUN_SCHEDULER=true requires WORKERS=1 to prevent duplicate jobs." >&2
    exit 1
fi

if [[ "${RUN_MIGRATIONS,,}" == "true" ]]; then
    echo "==> Running Alembic migrations..."
    alembic upgrade head
    echo "==> Migrations complete."
else
    echo "==> Alembic migrations disabled for this process."
fi

if [[ "$#" -gt 0 ]]; then
    exec "$@"
fi

echo "==> Starting URAKI API (workers=${WORKERS}, port=${PORT})..."
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers "${WORKERS}" \
    --log-level info \
    --no-access-log
