import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
from fastapi import HTTPException
from api import dependencies


class JWTBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def claims(self):
        return {"sub": "00000000-0000-0000-0000-000000000001", "tenant_id": "00000000-0000-0000-0000-000000000002", "iat": int(time.time()), "exp": int(time.time()) + 60}

    async def test_valid_token_uses_database_role_and_active_tenant(self):
        user = SimpleNamespace(role="operador")
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: user)))
        with patch.object(dependencies.settings, "SECRET_KEY", "x" * 32):
            token = jwt.encode({**self.claims(), "role": "admin"}, "x" * 32, algorithm="HS256")
            self.assertIs(await dependencies._user_from_jwt(token, db), user)
        query = str(db.execute.call_args.args[0])
        self.assertIn("JOIN tenants", query)
        self.assertIn("tenants.is_active IS true", query)
        self.assertEqual(user.role, "operador")

    async def test_invalid_claims_fail_before_database(self):
        claims = self.claims()
        cases = [{k: v for k, v in claims.items() if k != field} for field in claims]
        cases.extend([{**claims, "tenant_id": "../../private"}, {**claims, "tenant_id": []}, {**claims, "sub": "invalid"}])
        with patch.object(dependencies.settings, "SECRET_KEY", "x" * 32):
            for payload in cases:
                db = SimpleNamespace(execute=AsyncMock())
                with self.subTest(payload=payload):
                    token = jwt.encode(payload, "x" * 32, algorithm="HS256")
                    self.assertIsNone(await dependencies._user_from_jwt(token, db))
                    db.execute.assert_not_awaited()

    async def test_wrong_signature_and_expired_token(self):
        db = SimpleNamespace(execute=AsyncMock())
        with patch.object(dependencies.settings, "SECRET_KEY", "x" * 32):
            token = jwt.encode(self.claims(), "y" * 32, algorithm="HS256")
            self.assertIsNone(await dependencies._user_from_jwt(token, db))
            token = jwt.encode({**self.claims(), "exp": int(time.time()) - 60}, "x" * 32, algorithm="HS256")
            with self.assertRaises(HTTPException) as error:
                await dependencies._user_from_jwt(token, db)
            self.assertEqual(error.exception.status_code, 401)
            db.execute.assert_not_awaited()
