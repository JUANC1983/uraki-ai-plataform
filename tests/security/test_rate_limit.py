import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from api.middleware import PUBLIC_PATHS, RateLimitMiddleware


class _CountResult:
    def __init__(self, count):
        self.count = count

    def scalar(self):
        return self.count


class _RateSession:
    def __init__(self, count):
        self.count = count
        self.statements = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement):
        self.statements.append(statement)
        return _CountResult(self.count)

    async def commit(self):
        self.commits += 1


class _ConfigEngine:
    def __init__(self, *, enabled=True, rpm=100):
        self.config = SimpleNamespace(
            rate_limits=SimpleNamespace(
                enabled=enabled,
                requests_per_minute=rpm,
            )
        )

    async def load(self, tenant_id, db):
        return self.config


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_tenant_configured_limit_is_enforced(self):
        session = _RateSession(count=3)
        middleware = RateLimitMiddleware(app=lambda scope, receive, send: None)
        with patch("database.base.AsyncSessionLocal", return_value=session), patch(
            "core.config_engine.get_config_engine",
            return_value=_ConfigEngine(enabled=True, rpm=2),
        ):
            exceeded, detail = await middleware._check_rate_limit("tenant-a")

        self.assertTrue(exceeded)
        self.assertIn("3/2", detail)
        self.assertEqual(session.commits, 1)

    async def test_tenant_can_disable_rate_limit(self):
        session = _RateSession(count=999)
        middleware = RateLimitMiddleware(app=lambda scope, receive, send: None)
        with patch("database.base.AsyncSessionLocal", return_value=session), patch(
            "core.config_engine.get_config_engine",
            return_value=_ConfigEngine(enabled=False, rpm=1),
        ):
            exceeded, detail = await middleware._check_rate_limit("tenant-a")

        self.assertFalse(exceeded)
        self.assertEqual(detail, "")
        self.assertEqual(session.statements, [])


class RateLimitWiringTests(unittest.TestCase):
    def test_rate_limit_runs_after_tenant_resolution(self):
        middleware_names = [item.cls.__name__ for item in main.app.user_middleware]
        self.assertLess(
            middleware_names.index("TenantMiddleware"),
            middleware_names.index("RateLimitMiddleware"),
        )
        self.assertNotIn("/api/v1/auth/register", PUBLIC_PATHS)
        self.assertIn("/ready", PUBLIC_PATHS)


if __name__ == "__main__":
    unittest.main()
