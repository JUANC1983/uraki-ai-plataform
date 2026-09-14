import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from scripts.bootstrap_admin import bootstrap_admin


REPO_ROOT = Path(__file__).resolve().parents[2]


class _ReadySession:
    def __init__(self, revisions=None):
        self.statements = []
        self.revisions = ["0003"] if revisions is None else revisions

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement):
        self.statements.append(str(statement))
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.revisions))


class _UnavailableSession(_ReadySession):
    async def execute(self, statement):
        raise OSError("database unavailable")


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_is_cancelled_on_abnormal_shutdown(self):
        async def worker():
            await asyncio.Event().wait()
        task = asyncio.create_task(worker())
        with patch.object(main.settings, "SECRET_KEY", "s" * 32), patch.object(main.settings, "RUN_SCHEDULER", True), patch.object(main, "register_all_handlers"), patch.object(main, "start_scheduler", return_value=[task]):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                async with main.lifespan(main.app):
                    raise RuntimeError("synthetic failure")
        self.assertTrue(task.cancelled())
        self.assertEqual(main._scheduler_tasks, [])

    async def test_invalid_secret_blocks_all_startup_side_effects(self):
        with patch.object(main.settings, "SECRET_KEY", ""), patch.object(main, "register_all_handlers") as handlers, patch.object(main, "start_scheduler") as scheduler:
            with self.assertRaises(RuntimeError):
                async with main.lifespan(main.app):
                    self.fail("Insecure startup was accepted")
            handlers.assert_not_called()
            scheduler.assert_not_called()

    async def test_scheduler_can_be_disabled_for_non_owner_processes(self):
        original = (
            main.settings.DEBUG,
            main.settings.RUN_SCHEDULER,
            main.settings.SECRET_KEY,
        )
        main.settings.DEBUG = False
        main.settings.RUN_SCHEDULER = False
        main.settings.SECRET_KEY = "s" * 32
        try:
            with patch.object(main, "register_all_handlers"), patch.object(
                main, "start_scheduler"
            ) as start_scheduler:
                async with main.lifespan(main.app):
                    start_scheduler.assert_not_called()
        finally:
            (
                main.settings.DEBUG,
                main.settings.RUN_SCHEDULER,
                main.settings.SECRET_KEY,
            ) = original

    async def test_bootstrap_validates_before_database_access(self):
        with self.assertRaises(ValueError):
            await bootstrap_admin(
                tenant_name="Demo",
                tenant_slug="INVALID SLUG",
                email="admin@example.com",
                full_name="Admin",
                password="long-enough-password",
            )


class HealthEndpointTests(unittest.TestCase):
    def test_every_successful_json_operation_has_a_response_schema(self):
        schema = main.create_app().openapi()
        missing = []
        for path, path_item in schema["paths"].items():
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                for status_code, response in operation.get("responses", {}).items():
                    if not status_code.startswith("2") or status_code == "204":
                        continue
                    body = response.get("content", {}).get("application/json", {})
                    if not body.get("schema"):
                        missing.append(f"{method.upper()} {path} {status_code}")
        self.assertEqual(missing, [])

    def test_old_empty_or_divergent_schema_is_not_ready(self):
        for revisions in (["0001"], ["0002"], [], ["0003", "unknown"]):
            with self.subTest(revisions=revisions), patch("database.base.AsyncSessionLocal", return_value=_ReadySession(revisions)):
                response = TestClient(main.app).get("/ready")
                self.assertEqual(response.status_code, 503)
                self.assertFalse(response.json()["ready"])
                self.assertNotIn("Schema revision mismatch", response.text)

    def test_expected_schema_matches_migration_head(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        config = Config()
        config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        self.assertEqual(ScriptDirectory.from_config(config).get_heads(), [main.EXPECTED_SCHEMA_REVISION])

    def test_liveness_does_not_claim_database_readiness(self):
        response = TestClient(main.app).get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertNotIn("database", response.json())

    def test_readiness_checks_database_and_schema(self):
        ready = _ReadySession()
        with patch("database.base.AsyncSessionLocal", return_value=ready):
            response = TestClient(main.app).get("/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ready",
                "ready": True,
                "database": "ok",
                "checks": {"database": {"ok": True}},
            },
        )
        self.assertTrue(any("alembic_version" in sql for sql in ready.statements))
        self.assertTrue(any("tenants" in sql for sql in ready.statements))

    def test_readiness_returns_503_without_exposing_exception(self):
        with patch("database.base.AsyncSessionLocal", return_value=_UnavailableSession()):
            response = TestClient(main.app).get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "status": "not_ready",
                "ready": False,
                "database": "unavailable",
                "checks": {"database": {"ok": False}},
            },
        )
        self.assertNotIn("database unavailable", response.text)


class ContainerContractTests(unittest.TestCase):
    def test_container_uses_migration_entrypoint_and_single_worker_default(self):
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (REPO_ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn('ENTRYPOINT ["./docker-entrypoint.sh"]', dockerfile)
        self.assertIn('WORKERS="${WORKERS:-1}"', entrypoint)
        self.assertIn("alembic upgrade head", entrypoint)
        self.assertIn('WORKERS: "1"', compose)
        self.assertIn("/ready", compose)


if __name__ == "__main__":
    unittest.main()
