import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from api.dependencies import _hash_api_key, _user_from_api_key
from api.routes import auth
from core.security import hash_password
from database.models import APIKey, User


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return _ScalarResult(self.results.pop(0))

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        if value.id is None:
            value.id = "00000000-0000-0000-0000-000000000099"


class TenantAwareLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_filters_by_tenant_slug_and_normalized_email(self):
        user = User(
            id="00000000-0000-0000-0000-000000000001",
            tenant_id="00000000-0000-0000-0000-000000000002",
            email="admin@example.com",
            hashed_password=hash_password("correct horse battery staple"),
            full_name="Admin",
            role="admin",
            is_active=True,
        )
        db = _FakeSession([user])
        form = SimpleNamespace(
            username="  ADMIN@EXAMPLE.COM ",
            password="correct horse battery staple",
        )
        original_key = auth.settings.SECRET_KEY
        auth.settings.SECRET_KEY = "a" * 32
        try:
            token = await auth.login(form, "  tenant-a ", db)
        finally:
            auth.settings.SECRET_KEY = original_key

        statement = str(db.statements[0])
        self.assertIn("JOIN tenants", statement)
        self.assertIn("tenants.slug", statement)
        self.assertEqual(token.tenant_id, str(user.tenant_id))

    async def test_registration_requires_admin(self):
        payload = auth.UserCreate(
            email="user@example.com",
            password="long-enough-password",
            full_name="User",
            role="operador",
        )
        current_user = SimpleNamespace(role="operador", tenant_id="tenant-a")

        with self.assertRaises(HTTPException) as raised:
            await auth.register(payload, current_user, _FakeSession([]))
        self.assertEqual(raised.exception.status_code, 403)

    async def test_admin_registration_cannot_choose_another_tenant(self):
        tenant_id = "00000000-0000-0000-0000-000000000010"
        payload = auth.UserCreate(
            email=" NEW@EXAMPLE.COM ",
            password="long-enough-password",
            full_name="New User",
            role="legal",
        )
        current_user = SimpleNamespace(role="admin", tenant_id=tenant_id)
        db = _FakeSession([None])

        response = await auth.register(payload, current_user, db)

        created = db.added[0]
        self.assertEqual(str(created.tenant_id), tenant_id)
        self.assertEqual(created.email, "new@example.com")
        self.assertEqual(response["role"], "legal")
        self.assertEqual(db.commits, 1)


class APIKeyOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_key_resolves_only_its_owning_user(self):
        raw_key = "uraki_example"
        tenant_id = "00000000-0000-0000-0000-000000000020"
        user_id = "00000000-0000-0000-0000-000000000021"
        key = APIKey(
            tenant_id=tenant_id,
            user_id=user_id,
            name="automation",
            key_prefix="uraki_ex",
            key_hash=_hash_api_key(raw_key),
            is_active=True,
        )
        user = User(
            id=user_id,
            tenant_id=tenant_id,
            email="operator@example.com",
            hashed_password="unused",
            full_name="Operator",
            role="operador",
            is_active=True,
        )
        db = _FakeSession([key, user])

        resolved = await _user_from_api_key(raw_key, db)

        self.assertIs(resolved, user)
        self.assertIsNotNone(key.last_used_at)
        self.assertEqual(db.commits, 1)
        user_statement = str(db.statements[1])
        self.assertIn("users.id", user_statement)
        self.assertIn("users.tenant_id", user_statement)

    async def test_legacy_unowned_api_key_is_rejected(self):
        raw_key = "uraki_legacy"
        key = APIKey(
            tenant_id="00000000-0000-0000-0000-000000000030",
            user_id=None,
            name="legacy",
            key_prefix="uraki_le",
            key_hash=_hash_api_key(raw_key),
            is_active=True,
        )
        db = _FakeSession([key])

        self.assertIsNone(await _user_from_api_key(raw_key, db))
        self.assertEqual(len(db.statements), 1)
        self.assertEqual(db.commits, 0)


if __name__ == "__main__":
    unittest.main()
