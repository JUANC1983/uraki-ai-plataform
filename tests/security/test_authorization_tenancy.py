import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from api.dependencies import require_permission
from api.routes import decisions, tenants
from database.models import Case, Document
from database.repositories import CaseRepository, DocumentRepository


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _CapturingSession:
    def __init__(self, result=None):
        self.result = result
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _ScalarResult(self.result)


def _compiled(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class AuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_role_permissions_are_enforced_by_dependency(self):
        write_check = require_permission("write")
        override_check = require_permission("override")
        executive_check = require_permission("view_executive")

        operator = SimpleNamespace(role="operador")
        executive = SimpleNamespace(role="ejecutivo")

        self.assertIs(await write_check(operator), operator)
        self.assertIs(await override_check(operator), operator)
        self.assertIs(await executive_check(executive), executive)
        with self.assertRaises(HTTPException) as denied:
            await write_check(executive)
        self.assertEqual(denied.exception.status_code, 403)

    async def test_tenant_creation_is_not_available_to_tenant_admins(self):
        payload = tenants.TenantCreate(name="Other", slug="other")
        admin = SimpleNamespace(role="admin", tenant_id="tenant-a")

        with self.assertRaises(HTTPException) as denied:
            await tenants.create_tenant(payload, admin, None)
        self.assertEqual(denied.exception.status_code, 403)
        self.assertIn("bootstrap", denied.exception.detail.lower())


class TenantIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_base_repository_queries_include_tenant_predicate(self):
        tenant_id = "00000000-0000-0000-0000-000000000101"
        session = _CapturingSession()

        case_query = CaseRepository(session, tenant_id)._q().where(Case.id == tenant_id)
        document_query = DocumentRepository(session, tenant_id)._q().where(
            Document.id == tenant_id
        )

        case_sql = _compiled(case_query)
        document_sql = _compiled(document_query)
        self.assertIn("cases.tenant_id =", case_sql)
        self.assertIn(tenant_id.replace("-", ""), case_sql)
        self.assertIn("documents.tenant_id =", document_sql)
        self.assertIn(tenant_id.replace("-", ""), document_sql)

    async def test_cross_tenant_decision_lookup_returns_not_found(self):
        session = _CapturingSession(result=None)
        user = SimpleNamespace(tenant_id="00000000-0000-0000-0000-000000000201")

        with self.assertRaises(HTTPException) as missing:
            await decisions.get_decision(
                "00000000-0000-0000-0000-000000000202",
                user,
                session,
            )

        self.assertEqual(missing.exception.status_code, 404)
        sql = _compiled(session.statements[0])
        self.assertIn("decisions.tenant_id =", sql)
        self.assertIn("00000000000000000000000000000201", sql)


if __name__ == "__main__":
    unittest.main()
