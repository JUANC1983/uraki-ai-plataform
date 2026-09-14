import unittest
from unittest.mock import patch

from pydantic import ValidationError
from api.routes.auth import UserCreate
from core.security import hash_password, verify_password
from scripts.bootstrap_admin import bootstrap_admin


class PasswordBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_roundtrip_and_wrong_password(self):
        hashed = hash_password("synthetic password")
        self.assertTrue(verify_password("synthetic password", hashed))
        self.assertFalse(verify_password("incorrect password", hashed))
        self.assertFalse(verify_password("synthetic password", "malformed-hash"))

    def test_bcrypt_byte_boundary_and_suffix_collision(self):
        hashed = hash_password("a" * 72)
        self.assertTrue(verify_password("a" * 72, hashed))
        self.assertFalse(verify_password("a" * 72 + "suffix", hashed))
        for value in ("a" * 73, "é" * 37, "short", "a" * 12 + "\x00"):
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                hash_password(value)
        self.assertTrue(verify_password("é" * 36, hash_password("é" * 36)))

    async def test_api_and_bootstrap_reject_before_database(self):
        with self.assertRaises(ValidationError):
            UserCreate(email="synthetic@example.com", password="é" * 37, full_name="Synthetic")
        with patch("scripts.bootstrap_admin.AsyncSessionLocal") as session:
            with self.assertRaises(ValueError):
                await bootstrap_admin(tenant_name="Synthetic", tenant_slug="synthetic", email="synthetic@example.com", full_name="Synthetic", password="é" * 37)
            session.assert_not_called()
