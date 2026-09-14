"""Exercise critical tenant constraints against a migrated PostgreSQL database.

All synthetic rows live inside one transaction which is rolled back. The script
is intended for CI or an explicitly configured local disposable database.
"""

import asyncio
import json

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database.base import engine


TENANT_A = "00000000-0000-0000-0000-000000000701"
TENANT_B = "00000000-0000-0000-0000-000000000702"
USER_A = "00000000-0000-0000-0000-000000000703"
CASE_A = "00000000-0000-0000-0000-000000000704"
CASE_B = "00000000-0000-0000-0000-000000000705"
DECISION_A = "00000000-0000-0000-0000-000000000706"
OVERRIDE_A = "00000000-0000-0000-0000-000000000707"
OVERRIDE_B = "00000000-0000-0000-0000-000000000708"


async def _must_reject(connection, statement: str, values: dict) -> None:
    savepoint = await connection.begin_nested()
    try:
        await connection.execute(text(statement), values)
    except IntegrityError:
        await savepoint.rollback()
        return
    await savepoint.rollback()
    raise AssertionError("PostgreSQL accepted a forbidden tenant relationship")


async def verify() -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            for tenant_id, slug in ((TENANT_A, "synthetic-a"), (TENANT_B, "synthetic-b")):
                await connection.execute(
                    text(
                        "INSERT INTO tenants (id, name, slug) "
                        "VALUES (:id, :name, :slug)"
                    ),
                    {"id": tenant_id, "name": f"Synthetic {slug}", "slug": slug},
                )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, tenant_id, email, hashed_password, full_name, role) "
                    "VALUES (:id, :tenant, :email, :password, :name, 'admin')"
                ),
                {
                    "id": USER_A,
                    "tenant": TENANT_A,
                    "email": "synthetic@example.invalid",
                    "password": "synthetic-noncredential-hash",
                    "name": "Synthetic User",
                },
            )
            for case_id, tenant_id in ((CASE_A, TENANT_A), (CASE_B, TENANT_B)):
                await connection.execute(
                    text(
                        "INSERT INTO cases "
                        "(id, tenant_id, case_type, client_name) "
                        "VALUES (:id, :tenant, 'synthetic', 'Synthetic Client')"
                    ),
                    {"id": case_id, "tenant": tenant_id},
                )

            decision_sql = (
                "INSERT INTO decisions "
                "(id, tenant_id, case_id, classification, risk_score, risk_level, "
                "action, firmness, rationale, full_output) VALUES "
                "(:id, :tenant, :case_id, 'OTRO', 10, 'BAJO', 'REVIEW', "
                "'FIRME', 'Synthetic', CAST(:output AS jsonb))"
            )
            await _must_reject(
                connection,
                decision_sql,
                {
                    "id": DECISION_A,
                    "tenant": TENANT_A,
                    "case_id": CASE_B,
                    "output": json.dumps({"synthetic": True}),
                },
            )
            await connection.execute(
                text(decision_sql),
                {
                    "id": DECISION_A,
                    "tenant": TENANT_A,
                    "case_id": CASE_A,
                    "output": json.dumps({"synthetic": True}),
                },
            )

            override_sql = (
                "INSERT INTO overrides "
                "(id, tenant_id, case_id, decision_id, user_id, original_action, "
                "overridden_action, reason) VALUES "
                "(:id, :tenant, :case_id, :decision_id, :user_id, "
                "'REVIEW', 'MANUAL_REVIEW', 'Synthetic')"
            )
            common = {
                "tenant": TENANT_A,
                "case_id": CASE_A,
                "decision_id": DECISION_A,
                "user_id": USER_A,
            }
            await connection.execute(text(override_sql), {"id": OVERRIDE_A, **common})
            await _must_reject(
                connection, override_sql, {"id": OVERRIDE_B, **common}
            )
        finally:
            await transaction.rollback()
    await engine.dispose()
    print("POSTGRES_CONSTRAINTS_OK cross_tenant=blocked duplicate_override=blocked")


if __name__ == "__main__":
    asyncio.run(verify())
