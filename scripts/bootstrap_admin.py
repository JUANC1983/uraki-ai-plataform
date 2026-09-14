"""Create a tenant and its first administrator through an explicit local CLI.

Run migrations first, then execute:

    python -m scripts.bootstrap_admin \
        --tenant-name "Demo Tenant" \
        --tenant-slug demo \
        --email admin@example.com \
        --full-name "Demo Admin"

The password is read from ``URAKI_BOOTSTRAP_PASSWORD`` or prompted without echo.
It is never accepted as a command-line argument to avoid shell-history exposure.
"""

import argparse
import asyncio
import getpass
import os
import re
from dataclasses import dataclass

from sqlalchemy import select

from core.security import hash_password, validate_password
from database.base import AsyncSessionLocal
from database.models import Tenant, User


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class BootstrapResult:
    tenant_id: str
    user_id: str
    tenant_created: bool


async def bootstrap_admin(
    *,
    tenant_name: str,
    tenant_slug: str,
    email: str,
    full_name: str,
    password: str,
) -> BootstrapResult:
    slug = tenant_slug.strip().lower()
    normalized_email = email.strip().lower()
    if not _SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Tenant slug must contain lowercase letters, digits, and hyphens only")
    if "@" not in normalized_email:
        raise ValueError("A valid administrator email is required")
    validate_password(password)
    if not tenant_name.strip() or not full_name.strip():
        raise ValueError("Tenant name and administrator full name are required")

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await db.execute(select(Tenant).where(Tenant.slug == slug))
            tenant = result.scalar_one_or_none()
            tenant_created = tenant is None
            if tenant is None:
                tenant = Tenant(name=tenant_name.strip(), slug=slug, plan="starter")
                db.add(tenant)
                await db.flush()
            elif not tenant.is_active:
                raise RuntimeError("Cannot bootstrap an administrator for an inactive tenant")

            result = await db.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.email == normalized_email,
                )
            )
            if result.scalar_one_or_none():
                raise RuntimeError("Administrator already exists for this tenant and email")

            user = User(
                tenant_id=tenant.id,
                email=normalized_email,
                hashed_password=hash_password(password),
                full_name=full_name.strip(),
                role="admin",
                is_active=True,
            )
            db.add(user)
            await db.flush()

        return BootstrapResult(
            tenant_id=str(tenant.id),
            user_id=str(user.id),
            tenant_created=tenant_created,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a URAKI tenant administrator")
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    password = os.getenv("URAKI_BOOTSTRAP_PASSWORD") or getpass.getpass(
        "Administrator password (12-128 characters): "
    )
    result = asyncio.run(
        bootstrap_admin(
            tenant_name=args.tenant_name,
            tenant_slug=args.tenant_slug,
            email=args.email,
            full_name=args.full_name,
            password=password,
        )
    )
    action = "created" if result.tenant_created else "reused"
    print(f"Tenant {action}: {result.tenant_id}")
    print(f"Administrator created: {result.user_id}")


if __name__ == "__main__":
    main()
