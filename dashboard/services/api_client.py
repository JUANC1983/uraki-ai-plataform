# dashboard/services/api_client.py
"""
Core HTTP client for the URAKI API.

Contract:
  - Every call returns APIResponse(ok, data, error, status_code, from_cache)
  - Caller never sees raw requests exceptions — all wrapped
  - Auth token + Tenant ID injected on every request
  - GET responses cached in session_state with configurable TTL
  - Retries: 3 attempts with 0s / 0.4s / 1.2s delays on 429/502/503/504
  - 401 raises AuthError so app.py can clear the session and show login
  - When URAKI_API_URL is not configured, every call returns a 503 error response.
    The system NEVER fabricates data — it blocks usage and shows a clear error.
"""
import os
import time
import logging
from dataclasses import dataclass
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — resolved via environment layer
# ---------------------------------------------------------------------------

# Import environment config early so URL + timeouts are environment-aware.
# We do this at module level so BACKEND_CONFIGURED is computed once.
try:
    from core.environment import env as _env
    _ENV = _env()
    API_BASE = _ENV.api_url
    _TIMEOUT        = _ENV.request_timeout_s
    _MAX_RETRIES    = _ENV.max_retry_attempts
except Exception:
    # Fallback if environment module not yet importable (e.g. first import)
    API_BASE        = os.getenv("URAKI_API_URL", "").rstrip("/")
    _TIMEOUT        = 15
    _MAX_RETRIES    = 3

API_PREFIX = "/api/v1"

# True when the backend URL has been configured. The system requires a real backend.
BACKEND_CONFIGURED = bool(API_BASE)

# Kept for import compatibility with any remaining callers — always False now.
# The system no longer has a demo mode.
DEMO_MODE = False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class APIError(Exception):
    def __init__(self, status_code: int, detail: str, endpoint: str = "") -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail      = detail
        self.endpoint    = endpoint


class AuthError(APIError):
    """401 — token expired or invalid."""


class PermissionError(APIError):
    """403 — insufficient permissions."""


class NetworkError(Exception):
    """Backend unreachable or timed out."""


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

@dataclass
class APIResponse:
    ok:          bool
    data:        Any
    error:       Optional[str]
    status_code: int
    from_cache:  bool = False

    @property
    def items(self) -> list:
        if isinstance(self.data, list):
            return self.data
        if isinstance(self.data, dict):
            return self.data.get("items", [])
        return []

    @property
    def total(self) -> int:
        if isinstance(self.data, dict):
            return self.data.get("total", len(self.items))
        return len(self.items)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class APIClient:
    """
    Thin, stateless HTTP client. One instance per Streamlit request cycle.
    Pass `session_cache` (from st.session_state) for cross-rerun GET caching.
    """

    _RETRY_STATUSES = {429, 502, 503, 504}
    _RETRY_DELAYS   = [0, 0.4, 1.2]   # seconds before each attempt (trimmed by _MAX_RETRIES)

    def __init__(
        self,
        token:         Optional[str]  = None,
        session_cache: Optional[dict] = None,
    ) -> None:
        self._token  = token
        self._base   = f"{API_BASE}{API_PREFIX}" if API_BASE else ""
        # Namespace cache by environment to prevent cross-env contamination
        try:
            from core.environment import cache_namespace
            _ns = cache_namespace()
        except Exception:
            _ns = "_env_production"
        raw_cache: dict = session_cache if session_cache is not None else {}
        if _ns not in raw_cache:
            raw_cache[_ns] = {}
        self._cache: dict = raw_cache[_ns]

    # ── Public interface ───────────────────────────────────────────────

    def get(self, path: str, params: dict | None = None, ttl: int = 15) -> APIResponse:
        if not self._base:
            return self._not_configured_response()
        # Apply environment-aware TTL scaling
        try:
            from core.environment import effective_ttl
            effective = effective_ttl(ttl)
        except Exception:
            effective = ttl
        key    = self._cache_key("GET", path, params or {})
        cached = self._from_cache(key)
        if cached is not None:
            return APIResponse(ok=True, data=cached, error=None, status_code=200, from_cache=True)
        resp = self._safe_request("GET", path, params=params)
        if resp.ok and effective > 0:
            self._to_cache(key, resp.data, effective)
        return resp

    def post(self, path: str, json: dict | None = None) -> APIResponse:
        if not self._base:
            return self._not_configured_response()
        return self._safe_request("POST", path, json=json)

    def patch(self, path: str, json: dict | None = None) -> APIResponse:
        if not self._base:
            return self._not_configured_response()
        return self._safe_request("PATCH", path, json=json)

    def upload(self, path: str, files: dict, data: dict | None = None) -> APIResponse:
        if not self._base:
            return self._not_configured_response()
        return self._safe_request("POST", path, files=files, form_data=data or {})

    def post_form(self, path: str, data: dict) -> APIResponse:
        if not self._base:
            return self._not_configured_response()
        return self._safe_request("POST", path, form_data=data)

    def invalidate(self, path_prefix: str) -> None:
        keys = [k for k in self._cache if path_prefix in k]
        for k in keys:
            del self._cache[k]

    def invalidate_all(self) -> None:
        self._cache.clear()

    # ── Internal ───────────────────────────────────────────────────────

    def _not_configured_response(self) -> APIResponse:
        return APIResponse(
            ok=False, data=None,
            error=(
                "Backend no configurado. "
                "Configura la variable de entorno URAKI_API_URL "
                "y reinicia el servidor."
            ),
            status_code=503,
        )

    def _headers(self, include_content_type: bool = True) -> dict:
        h: dict = {}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        if include_content_type:
            h["Content-Type"] = "application/json"
        # Multi-tenant isolation — inject tenant ID on every request
        try:
            import streamlit as st
            tid = st.session_state.get("auth_user", {}).get("tenant_id")
            if tid:
                h["X-Tenant-ID"] = tid
        except Exception:
            pass
        return h

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def _safe_request(
        self,
        method:    str,
        path:      str,
        json:      dict | None = None,
        params:    dict | None = None,
        files:     dict | None = None,
        form_data: dict | None = None,
    ) -> APIResponse:
        url = self._url(path)
        try:
            raw = self._request_with_retry(method, url, json=json, params=params,
                                           files=files, form_data=form_data)
        except NetworkError as e:
            logger.error("Network error on %s %s: %s", method, path, e)
            return APIResponse(ok=False, data=None,
                               error=f"Sin conexión al backend: {e}", status_code=0)
        return self._parse_response(raw, path)

    def _request_with_retry(
        self, method: str, url: str,
        json=None, params=None, files=None, form_data=None,
    ) -> requests.Response:
        retry_delays = self._RETRY_DELAYS[:_MAX_RETRIES]
        for attempt, delay in enumerate(retry_delays):
            if delay > 0:
                time.sleep(delay)

            kwargs: dict = {"timeout": _TIMEOUT}
            if files:
                kwargs["headers"] = {k: v for k, v in self._headers(False).items()}
                kwargs["files"]   = files
                if form_data:
                    kwargs["data"] = form_data
            elif form_data and json is None:
                kwargs["headers"] = self._headers(False)
                kwargs["data"]    = form_data
            else:
                kwargs["headers"] = self._headers(True)
                if json is not None:
                    kwargs["json"] = json
            if params:
                kwargs["params"] = params

            try:
                resp = requests.request(method, url, **kwargs)
            except requests.exceptions.ConnectionError as exc:
                if attempt == len(retry_delays) - 1:
                    raise NetworkError(f"No se pudo conectar: {exc}")
                continue
            except requests.exceptions.Timeout as exc:
                if attempt == len(retry_delays) - 1:
                    raise NetworkError(f"Timeout ({_TIMEOUT}s): {exc}")
                continue

            if resp.status_code in self._RETRY_STATUSES and attempt < len(retry_delays) - 1:
                logger.warning("Retry %d for %s %s (status=%d)", attempt + 1, method, url, resp.status_code)
                continue

            return resp

        raise NetworkError("Max retries exceeded")

    def _parse_response(self, resp: requests.Response, path: str) -> APIResponse:
        if resp.status_code == 401:
            raise AuthError(401, "Sesión expirada. Inicia sesión nuevamente.", path)
        if resp.status_code == 403:
            raise PermissionError(403, "Sin permisos para esta acción.", path)

        ok = resp.status_code < 400
        try:
            data = resp.json() if resp.content else None
        except Exception:
            data = resp.text or None

        if not ok:
            if isinstance(data, dict):
                detail = data.get("detail", f"HTTP {resp.status_code}")
            else:
                detail = str(data) if data else f"HTTP {resp.status_code}"
            logger.warning("API error %d %s: %s", resp.status_code, path, detail)
            return APIResponse(ok=False, data=None, error=detail, status_code=resp.status_code)

        return APIResponse(ok=True, data=data, error=None, status_code=resp.status_code)

    # ── Cache helpers ──────────────────────────────────────────────────

    def _cache_key(self, method: str, path: str, params: dict) -> str:
        stable = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{method}:{path}?{stable}"

    def _from_cache(self, key: str) -> Any:
        entry = self._cache.get(key)
        if entry and entry["exp"] > time.monotonic():
            return entry["data"]
        if entry:
            del self._cache[key]
        return None

    def _to_cache(self, key: str, data: Any, ttl: int) -> None:
        self._cache[key] = {"data": data, "exp": time.monotonic() + ttl}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_client(token: Optional[str] = None, session_cache: Optional[dict] = None) -> APIClient:
    return APIClient(token=token, session_cache=session_cache)
