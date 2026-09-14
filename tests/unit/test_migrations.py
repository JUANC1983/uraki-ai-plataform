import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.orm import configure_mappers

import main
from database.base import get_db
from database.models import Base


ROOT = Path(__file__).resolve().parents[2]


def _alembic_sql(*args: str) -> str:
    environment = dict(os.environ)
    environment["DEBUG"] = "false"
    result = subprocess.run(
        [sys.executable, "-B", "-m", "alembic", *args],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout + result.stderr


class MigrationContractTests(unittest.TestCase):
    def test_single_head_matches_readiness_and_mappers_configure(self):
        config = Config()
        config.set_main_option("script_location", str(ROOT / "alembic"))
        self.assertEqual(
            ScriptDirectory.from_config(config).get_heads(),
            [main.EXPECTED_SCHEMA_REVISION],
        )
        configure_mappers()
        self.assertEqual(len(Base.metadata.tables), 14)

    def test_upgrade_and_full_downgrade_compile_offline(self):
        upgrade = _alembic_sql("upgrade", "head", "--sql")
        downgrade = _alembic_sql("downgrade", "head:base", "--sql")

        self.assertIn("UPDATE alembic_version SET version_num='0003'", upgrade)
        self.assertIn("DROP TABLE alembic_version", downgrade)
        self.assertIn("ADD CONSTRAINT uq_overrides_tenant_decision UNIQUE", upgrade)
        self.assertIn("DROP CONSTRAINT uq_overrides_tenant_decision", downgrade)
        for constraint in (
            "fk_api_keys_tenant_user",
            "fk_rules_tenant_parent",
            "fk_decisions_tenant_case",
            "fk_overrides_tenant_case",
            "fk_overrides_tenant_decision",
            "fk_overrides_tenant_user",
            "fk_documents_tenant_case",
            "fk_document_chunks_tenant_document",
            "fk_feedback_tenant_case",
            "fk_feedback_tenant_decision",
            "fk_feedback_tenant_rule",
            "fk_feedback_tenant_user",
        ):
            self.assertIn(f"ADD CONSTRAINT {constraint}", upgrade)
            self.assertIn(f"DROP CONSTRAINT {constraint}", downgrade)

    def test_models_declare_expected_composite_tenant_foreign_keys(self):
        expected = {
            "api_keys": {("tenant_id", "user_id")},
            "rules": {("tenant_id", "parent_rule_id")},
            "decisions": {("tenant_id", "case_id")},
            "overrides": {
                ("tenant_id", "case_id"),
                ("tenant_id", "decision_id"),
                ("tenant_id", "user_id"),
            },
            "documents": {("tenant_id", "case_id")},
            "document_chunks": {("tenant_id", "document_id")},
            "feedback_registry": {
                ("tenant_id", "case_id"),
                ("tenant_id", "decision_id"),
                ("tenant_id", "rule_id"),
                ("tenant_id", "user_id"),
            },
        }
        for table_name, column_sets in expected.items():
            actual = {
                tuple(element.parent.name for element in constraint.elements)
                for constraint in Base.metadata.tables[table_name].foreign_key_constraints
                if len(constraint.elements) == 2
            }
            self.assertEqual(actual, column_sets, table_name)

        override_uniques = {
            tuple(column.name for column in constraint.columns)
            for constraint in Base.metadata.tables["overrides"].constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        self.assertIn(("tenant_id", "decision_id"), override_uniques)


class _Session:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class TransactionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_dependency_commits_success_and_rolls_back_failure(self):
        success = _Session()
        with patch("database.base.AsyncSessionLocal", return_value=success):
            generator = get_db()
            self.assertIs(await anext(generator), success)
            with self.assertRaises(StopAsyncIteration):
                await anext(generator)
        success.commit.assert_awaited_once()
        success.rollback.assert_not_awaited()
        success.close.assert_awaited_once()

        failure = _Session()
        with patch("database.base.AsyncSessionLocal", return_value=failure):
            generator = get_db()
            self.assertIs(await anext(generator), failure)
            with self.assertRaisesRegex(RuntimeError, "synthetic transaction failure"):
                await generator.athrow(RuntimeError("synthetic transaction failure"))
        failure.commit.assert_not_awaited()
        failure.rollback.assert_awaited_once()
        failure.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
