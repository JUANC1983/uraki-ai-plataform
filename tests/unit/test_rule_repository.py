import unittest
from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from database.models import Rule
from database.repositories import RuleRepository


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Result:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar_value = scalar
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalars(self):
        return _Scalars(self.rows)


class _Session:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


class RuleHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_child_version_id_resolves_complete_logical_history(self):
        tenant_id = "00000000-0000-0000-0000-000000000301"
        root_id = "00000000-0000-0000-0000-000000000302"
        child_id = "00000000-0000-0000-0000-000000000303"
        now = datetime.now(timezone.utc)
        root = Rule(
            id=root_id,
            tenant_id=tenant_id,
            parent_rule_id=None,
            name="Root",
            category="arrears",
            conditions={},
            actions={},
            version=1,
            effective_from=now,
            is_active=False,
        )
        child = Rule(
            id=child_id,
            tenant_id=tenant_id,
            parent_rule_id=root_id,
            name="Child",
            category="arrears",
            conditions={},
            actions={},
            version=2,
            effective_from=now,
            is_active=True,
        )
        session = _Session(
            [
                _Result(scalar=child),
                _Result(rows=[root, child]),
            ]
        )

        history = await RuleRepository(session, tenant_id).get_version_history(child_id)

        self.assertEqual([rule.version for rule in history], [1, 2])
        sql = str(
            session.statements[1].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("rules.tenant_id =", sql)
        self.assertIn(root_id.replace("-", ""), sql)


if __name__ == "__main__":
    unittest.main()
