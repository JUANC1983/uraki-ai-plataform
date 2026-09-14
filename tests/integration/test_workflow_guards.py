import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks, HTTPException

from api.routes import cases, decisions


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, value=None):
        self.value = value
        self.commits = 0

    async def execute(self, statement):
        return _ScalarResult(self.value)

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        return None


class _CaseRepository:
    def __init__(self, case):
        self.case = case
        self.status_updates = []

    async def get(self, case_id):
        return self.case

    async def get_for_update(self, case_id):
        return self.case

    async def update_status(self, *, case_id, status):
        self.status_updates.append((case_id, status))
        self.case.status = status


class WorkflowGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_case_and_event_use_one_transaction(self):
        tenant = "00000000-0000-0000-0000-000000000001"
        case_id = "00000000-0000-0000-0000-000000000002"
        user = SimpleNamespace(tenant_id=tenant, id="00000000-0000-0000-0000-000000000003")
        case = SimpleNamespace(id=case_id, case_type="note", client_name="Synthetic", status="NEW", priority=None)
        repo = SimpleNamespace(create=AsyncMock(return_value=case))
        bus = SimpleNamespace(publish=AsyncMock(side_effect=OSError("synthetic event persistence failure")))
        session = _Session()

        with patch("api.routes.cases.CaseRepository", return_value=repo):
            with self.assertRaises(OSError):
                await cases.create_case(
                    cases.CaseCreateRequest(case_type="note", client_name="Synthetic"),
                    BackgroundTasks(), user, session, bus, SimpleNamespace(),
                )

        self.assertEqual(session.commits, 0)

    async def test_transition_and_event_use_one_transaction(self):
        tenant = "00000000-0000-0000-0000-000000000001"
        case_id = "00000000-0000-0000-0000-000000000002"
        user = SimpleNamespace(tenant_id=tenant, id="00000000-0000-0000-0000-000000000003")
        case = SimpleNamespace(id=case_id, status="NEW")
        repo = _CaseRepository(case)
        bus = SimpleNamespace(publish=AsyncMock(side_effect=OSError("synthetic event persistence failure")))
        session = _Session()

        with patch("api.routes.cases.CaseRepository", return_value=repo):
            with self.assertRaises(OSError):
                await cases.transition_case(
                    case_id,
                    cases.CaseTransitionRequest(target_status="IN_REVIEW"),
                    BackgroundTasks(), user, session, bus,
                )

        self.assertEqual(session.commits, 0)

    async def test_closed_case_cannot_be_evaluated(self):
        case = SimpleNamespace(id="case-1", status="CLOSED")
        repo = _CaseRepository(case)
        user = SimpleNamespace(tenant_id="tenant-a", id="user-a")

        with patch("api.routes.cases.CaseRepository", return_value=repo):
            with self.assertRaises(HTTPException) as conflict:
                await cases.evaluate_case(
                    "case-1",
                    BackgroundTasks(),
                    user,
                    _Session(),
                    SimpleNamespace(),
                    SimpleNamespace(),
                )

        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(repo.status_updates, [])

    async def test_decision_cannot_be_overridden_twice(self):
        decision = SimpleNamespace(
            id="decision-1",
            case_id="case-1",
            is_overridden=True,
        )
        session = _Session(decision)
        user = SimpleNamespace(tenant_id="tenant-a", id="user-a", role="operador")

        with self.assertRaises(HTTPException) as conflict:
            await decisions.override_decision(
                "decision-1",
                decisions.OverrideRequest(
                    overridden_action="REVIEW",
                    reason="Manual review required",
                ),
                BackgroundTasks(),
                user,
                session,
                SimpleNamespace(),
            )

        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(session.commits, 0)

    async def test_override_respects_case_state_machine(self):
        decision = SimpleNamespace(
            id="decision-1",
            case_id="case-1",
            is_overridden=False,
        )
        case = SimpleNamespace(id="case-1", status="CLOSED")
        repo = _CaseRepository(case)
        session = _Session(decision)
        user = SimpleNamespace(tenant_id="tenant-a", id="user-a", role="operador")

        with patch("api.routes.decisions.CaseRepository", return_value=repo):
            with self.assertRaises(HTTPException) as conflict:
                await decisions.override_decision(
                    "decision-1",
                    decisions.OverrideRequest(
                        overridden_action="REVIEW",
                        reason="Manual review required",
                    ),
                    BackgroundTasks(),
                    user,
                    session,
                    SimpleNamespace(),
                )

        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(repo.status_updates, [])
        self.assertEqual(session.commits, 0)


if __name__ == "__main__":
    unittest.main()
