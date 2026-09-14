# main.py
"""
URAKI AI Platform — FastAPI application entry point.

Startup sequence:
  1. Validate SECRET_KEY (refuses to start if insecure)
  2. Require schema management through Alembic
  3. Register domain event handlers
  4. Launch background scheduler jobs
  5. Mount all API routers

Shutdown:
  1. Cancel scheduler tasks
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.middleware import RateLimitMiddleware, RequestLoggingMiddleware, TenantMiddleware
from api.routes import auth, cases, dashboard, decisions, documents, tenants
from api.response_models import HealthResponse, ReadinessResponse
from automation.event_handlers import register_all_handlers
from automation.scheduler import start_scheduler
from config.settings import get_settings, validate_secret_key
from core.event_bus import get_event_bus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()
EXPECTED_SCHEMA_REVISION = "0003"

# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

_scheduler_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ---- STARTUP ----

    # 1. Security gate — crash immediately if SECRET_KEY is insecure.
    #    This must be the very first check so a misconfigured deployment
    #    never serves traffic with a forgeable JWT key.
    validate_secret_key(settings.SECRET_KEY)
    logger.info("SECRET_KEY validated.")

    # 2. Database schema is managed only by Alembic. The container entrypoint
    # applies migrations; local runs must execute `alembic upgrade head` first.
    logger.info("Database schema is expected at the Alembic head revision.")

    # 3. Register event handlers
    bus = get_event_bus()
    register_all_handlers(bus)
    logger.info("Event handlers registered.")

    # 4. Start background scheduler only in the designated API process.
    if settings.RUN_SCHEDULER:
        tasks = start_scheduler()
        _scheduler_tasks.extend(tasks)
        logger.info("Scheduler started (%d jobs).", len(tasks))
    else:
        logger.info("Scheduler disabled for this process.")

    try:
        yield
    finally:
        # Release scheduler tasks even when application lifespan exits with error.
        logger.info("URAKI AI Platform shutting down...")
        for task in _scheduler_tasks:
            task.cancel()
        await asyncio.gather(*_scheduler_tasks, return_exceptions=True)
        _scheduler_tasks.clear()
        logger.info("Scheduler tasks cancelled. Goodbye.")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="URAKI AI Platform",
        description=(
            "Multi-tenant SaaS decision engine for real estate operations. "
            "Auditable, configurable, rule-based — with AI assistance."
        ),
        version=settings.APP_VERSION,
        # Disable Swagger UI and ReDoc in production to avoid exposing the
        # full API schema publicly. Set DEBUG=true to re-enable during development.
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # ---- Middleware (outermost → innermost) ----
    app.add_middleware(
        CORSMiddleware,
        # Explicit allowlist — never wildcard in production.
        # Configure via ALLOWED_ORIGINS env var (comma-separated string).
        allow_origins=settings.get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(TenantMiddleware)

    # ---- Routers ----
    prefix = settings.API_PREFIX
    app.include_router(auth.router, prefix=prefix)
    app.include_router(cases.router, prefix=prefix)
    app.include_router(decisions.router, prefix=prefix)
    app.include_router(documents.router, prefix=prefix)
    app.include_router(tenants.router, prefix=prefix)
    app.include_router(dashboard.router, prefix=prefix)

    # ---- Health check (always public) ----
    @app.get("/health", tags=["System"], response_model=HealthResponse)
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": settings.APP_VERSION})

    @app.get("/ready", tags=["System"], response_model=ReadinessResponse)
    async def readiness() -> JSONResponse:
        """Report whether PostgreSQL is reachable and the migrated schema exists."""
        from sqlalchemy import text

        from database.base import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as db:
                await db.execute(text("SELECT 1"))
                revision = await db.execute(text("SELECT version_num FROM alembic_version"))
                if revision.scalars().all() != [EXPECTED_SCHEMA_REVISION]:
                    raise RuntimeError("Schema revision mismatch")
                await db.execute(text("SELECT 1 FROM tenants LIMIT 1"))
                await db.execute(text("SELECT user_id FROM api_keys LIMIT 0"))
        except Exception as exc:
            logger.warning("Readiness check failed (%s)", type(exc).__name__)
            return JSONResponse(
                {
                    "status": "not_ready",
                    "ready": False,
                    "database": "unavailable",
                    "checks": {"database": {"ok": False}},
                },
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return JSONResponse(
            {
                "status": "ready",
                "ready": True,
                "database": "ok",
                "checks": {"database": {"ok": True}},
            }
        )

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse({
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            # Only advertise docs URL if enabled
            **({"docs": "/docs"} if settings.DEBUG else {}),
        })

    return app


app = create_app()


# ---------------------------------------------------------------------------
# Run (development only — use uvicorn directly in production)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info",
    )
