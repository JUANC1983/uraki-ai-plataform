# api/middleware.py
"""
Middleware stack:
  1. TenantMiddleware    — injects tenant hint from JWT (read-only, logging only)
  2. RateLimitMiddleware — per-tenant atomic sliding window (DB-backed)
  3. RequestLoggingMiddleware — structured request logs
"""
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/login",
})


# ---------------------------------------------------------------------------
# 1. Tenant Middleware
# ---------------------------------------------------------------------------

class TenantMiddleware(BaseHTTPMiddleware):
    """
    Reads tenant hint from the JWT sub-claim for logging purposes only.
    Actual tenant isolation is enforced downstream via BaseRepository.
    The X-Tenant-ID header from the CLIENT is intentionally ignored and
    never echoed back — reflecting client-supplied headers is an
    information-disclosure risk.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Derive hint from JWT without full validation (logging only)
        tenant_hint = "unknown"
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            try:
                import jwt as _jwt
                from config.settings import get_settings
                _s = get_settings()
                payload = _jwt.decode(
                    auth[7:], _s.SECRET_KEY,
                    algorithms=[_s.JWT_ALGORITHM],
                    options={"verify_exp": False},
                )
                tenant_hint = payload.get("tenant_id", "unknown")
            except Exception:
                pass
        elif request.headers.get("X-API-Key"):
            # Resolve only a tenant hint here. Full authentication and key
            # ownership checks remain in the route dependency.
            try:
                from sqlalchemy import select

                from database.base import AsyncSessionLocal
                from database.models import APIKey

                key_hash = hashlib.sha256(
                    request.headers["X-API-Key"].encode()
                ).hexdigest()
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(APIKey.tenant_id).where(
                            APIKey.key_hash == key_hash,
                            APIKey.is_active.is_(True),
                        )
                    )
                    resolved_tenant = result.scalar_one_or_none()
                    if resolved_tenant:
                        tenant_hint = str(resolved_tenant)
            except Exception:
                logger.warning("Could not resolve API key tenant for rate limiting")

        request.state.tenant_hint = tenant_hint
        response = await call_next(request)
        # Do NOT echo tenant_hint into response headers
        return response


# ---------------------------------------------------------------------------
# 2. Rate Limit Middleware — atomic, no race condition
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-tenant rate limiting using a PostgreSQL atomic upsert.

    Uses INSERT ... ON CONFLICT DO UPDATE ... RETURNING to increment
    the request counter in a single round-trip. This is race-condition-free
    even under high concurrency.

    Uses its own DB session (AsyncSessionLocal) — self-contained,
    no FastAPI dependency injection (unavailable in Starlette middleware).

    For high-traffic (>500 RPM per tenant): replace with Redis INCR + EXPIRE.
    """

    DEFAULT_RPM: int = 100

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        tenant_hint = getattr(request.state, "tenant_hint", None)
        if not tenant_hint or tenant_hint == "unknown":
            return await call_next(request)

        try:
            exceeded, detail = await self._check_rate_limit(tenant_hint)
            if exceeded:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": "rate_limit_exceeded",
                        "detail": detail,
                        "retry_after_seconds": 60,
                    },
                    headers={"Retry-After": "60"},
                )
        except Exception as exc:
            # Never block requests due to rate limit errors — fail open
            logger.warning("Rate limit check failed open (%s)", type(exc).__name__)

        return await call_next(request)

    async def _check_rate_limit(self, tenant_id: str) -> tuple[bool, str]:
        """
        Atomic single-statement upsert: insert count=1 or increment on conflict.
        Returns (exceeded, detail_message).
        """
        from database.base import AsyncSessionLocal
        from core.config_engine import get_config_engine
        from database.models import TenantQuota
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        window_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")

        async with AsyncSessionLocal() as db:
            config = await get_config_engine().load(tenant_id, db)
            if not config.rate_limits.enabled:
                return False, ""
            rpm_limit = config.rate_limits.requests_per_minute

            # Single atomic statement: insert or increment, then return count.
            stmt = (
                pg_insert(TenantQuota)
                .values(
                    tenant_id=tenant_id,
                    window_key=window_key,
                    window_type="minute",
                    request_count=1,
                )
                .on_conflict_do_update(
                    index_elements=["tenant_id", "window_key"],
                    set_={"request_count": TenantQuota.request_count + 1},
                )
                .returning(TenantQuota.request_count)
            )
            result = await db.execute(stmt)
            count = result.scalar()
            await db.commit()

        if count > rpm_limit:
            return True, f"Rate limit: {count}/{rpm_limit} requests this minute"
        return False, ""


# ---------------------------------------------------------------------------
# 3. Request Logging Middleware
# ---------------------------------------------------------------------------

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "%s %s %d %dms tenant=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            getattr(request.state, "tenant_hint", "—"),
        )
        response.headers["X-Response-Time-Ms"] = str(duration_ms)
        return response
