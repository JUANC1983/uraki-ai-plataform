"""Safe integrated portfolio walkthrough using real HTTP and dashboard clients.

External network and database access are deliberately replaced with an
in-memory store. This proves component integration, not PostgreSQL behavior.
"""

import importlib.util
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, BindParameter

import main
from api.dependencies import get_tenant_config
from config.settings import get_settings
from core.config_engine import TenantConfig
from core.security import hash_password
from database.base import get_db
from database.models import Case, Decision, Document, Tenant, User


TENANT_ID = "00000000-0000-0000-0000-000000000501"
USER_ID = "00000000-0000-0000-0000-000000000502"
CASE_ID = "00000000-0000-0000-0000-000000000503"
DOCUMENT_ID = "00000000-0000-0000-0000-000000000504"
DECISION_ID = "00000000-0000-0000-0000-000000000505"
OVERRIDE_ID = "00000000-0000-0000-0000-000000000506"
SECRET = "synthetic-golden-path-key-32-characters"
PASSWORD = "synthetic-password"


async def _rate_limit_ok(*args, **kwargs):
    return False, ""


def _load_dashboard_client_module():
    module_path = (
        Path(__file__).resolve().parents[2] / "dashboard" / "services" / "api_client.py"
    )
    spec = importlib.util.spec_from_file_location("golden_path_api_client", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class Store:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.tenant = Tenant(
            id=TENANT_ID, name="Synthetic Portfolio Tenant",
            slug="synthetic-portfolio", plan="starter", is_active=True,
        )
        self.user = User(
            id=USER_ID, tenant_id=TENANT_ID, email="operator@example.invalid",
            hashed_password=hash_password(PASSWORD), full_name="Synthetic Operator",
            role="admin", is_active=True,
        )
        self.now = now
        self.cases = {}
        self.documents = {}
        self.decisions = {}
        self.overrides = {}
        self.events = []
        self.saved_files = {}


class Session:
    def __init__(self, store):
        self.store = store
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, query):
        model = query.column_descriptions[0]["entity"]
        equalities = {}
        for clause in query._where_criteria:
            for node in visitors.iterate(clause):
                if (
                    isinstance(node, BinaryExpression)
                    and node.operator is operators.eq
                    and isinstance(node.right, BindParameter)
                ):
                    equalities[node.left.key] = node.right.value
        if model is User:
            row = self.store.user
        elif model is Tenant:
            row = self.store.tenant
        elif model is Decision:
            row = self.store.decisions.get(str(equalities.get("id")))
        else:
            raise AssertionError(f"Unconfigured golden-path SQL model: {model}")
        return SimpleNamespace(
            scalar_one_or_none=lambda: row,
            scalars=lambda: SimpleNamespace(all=lambda: [row] if row else []),
        )

    def add(self, row):
        return None

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, row):
        return None


class CaseRepo:
    store = None

    def __init__(self, session, tenant_id):
        assert tenant_id == TENANT_ID

    async def create(self, data):
        case = Case(
            id=CASE_ID, tenant_id=TENANT_ID, status="NEW", priority="MEDIUM",
            raw_data=data.pop("raw_data", {}) or {}, created_at=self.store.now, **data,
        )
        self.store.cases[CASE_ID] = case
        return case

    async def get(self, case_id):
        return self.store.cases.get(str(case_id))

    async def get_for_update(self, case_id):
        return await self.get(case_id)

    async def update_status(self, *, case_id, status):
        self.store.cases[str(case_id)].status = status

    async def list(self, *, status=None, limit=50, offset=0):
        rows = list(self.store.cases.values())
        if status:
            rows = [row for row in rows if row.status == status]
        return rows[offset:offset + limit], len(rows)

    async def get_kpis(self):
        rows = list(self.store.cases.values())
        return {
            "total_cases": len(rows),
            "open_cases": sum(row.status != "CLOSED" for row in rows),
            "total_overdue_amount": sum(row.overdue_amount for row in rows),
            "avg_overdue_days": (
                sum(row.overdue_days for row in rows) / len(rows) if rows else 0.0
            ),
        }

    async def get_aging_buckets(self):
        return {"0_30_days": 0, "31_60_days": 0, "61_90_days": 0, "90_plus_days": 1}


class DecisionRepo:
    store = None

    def __init__(self, session, tenant_id):
        assert tenant_id == TENANT_ID

    async def save(self, *, decision, context_snapshot=None):
        row = Decision(
            id=DECISION_ID,
            tenant_id=TENANT_ID,
            case_id=CASE_ID,
            classification=decision.classification.value,
            risk_score=decision.risk_score,
            risk_level=decision.risk_level.value,
            priority=decision.priority.value,
            action=decision.action,
            firmness=decision.firmness.value,
            escalation_required=decision.escalation_required,
            escalation_target=decision.escalation_target,
            legal_flag=decision.legal_flag,
            policy_flag=decision.policy_flag,
            validations_missing=decision.validations_missing,
            rationale=decision.rationale,
            rule_id_applied=decision.rule_id_applied,
            rule_version_used=decision.rule_version_used,
            document_references=[item.model_dump() for item in decision.document_references],
            context_snapshot=context_snapshot,
            confidence=decision.confidence,
            suggested_message=decision.suggested_message,
            full_output=decision.to_audit_dict(),
            is_overridden=False,
            created_at=self.store.now,
        )
        self.store.decisions[DECISION_ID] = row
        return row

    async def get(self, decision_id):
        return self.store.decisions.get(str(decision_id))

    async def get_for_update(self, decision_id):
        return await self.get(decision_id)

    async def get_latest_for_case(self, case_id):
        return next(
            (row for row in self.store.decisions.values() if str(row.case_id) == str(case_id)),
            None,
        )

    async def get_stats(self):
        rows = list(self.store.decisions.values())
        overridden = sum(row.is_overridden for row in rows)
        return {
            "total_decisions": len(rows),
            "escalated": sum(row.escalation_required for row in rows),
            "legal_flags": sum(row.legal_flag for row in rows),
            "overridden": overridden,
            "override_rate": round(overridden / max(len(rows), 1) * 100, 2),
            "priority_distribution": {
                row.priority: sum(item.priority == row.priority for item in rows)
                for row in rows
            },
        }


class RuleRepo:
    def __init__(self, session, tenant_id):
        assert tenant_id == TENANT_ID

    async def get_active_rules(self):
        return []


class DocumentRepo:
    store = None

    def __init__(self, session, tenant_id):
        assert tenant_id == TENANT_ID

    async def create(self, data):
        row = Document(
            id=DOCUMENT_ID, tenant_id=TENANT_ID, created_at=self.store.now, **data
        )
        self.store.documents[DOCUMENT_ID] = row
        return row

    async def get(self, document_id):
        return self.store.documents.get(str(document_id))

    async def list_by_case(self, case_id):
        return [
            row for row in self.store.documents.values()
            if str(row.case_id) == str(case_id)
        ]


class OverrideRepo:
    store = None

    def __init__(self, session, tenant_id):
        assert tenant_id == TENANT_ID

    async def create(self, data):
        row = SimpleNamespace(id=OVERRIDE_ID, **data)
        self.store.overrides[OVERRIDE_ID] = row
        return row

    async def get_override_rate(self, *, rule_id=None):
        return round(len(self.store.overrides) / max(len(self.store.decisions), 1) * 100, 2)


class Bus:
    def __init__(self, store):
        self.store = store

    async def publish(self, event, **kwargs):
        self.store.events.append({
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "aggregate_id": str(event.aggregate_id),
            "payload": event.payload,
            "created_at": event.occurred_at.isoformat(),
        })

    async def replay(self, *, tenant_id, **kwargs):
        assert tenant_id == TENANT_ID
        return list(self.store.events)


class Storage:
    def __init__(self, store):
        self.store = store

    async def save_file(self, *, tenant_id, file_obj, original_filename, content_type):
        assert tenant_id == TENANT_ID
        path = f"memory://{tenant_id}/{original_filename}"
        payload = file_obj.read()
        self.store.saved_files[path] = payload
        return {"file_path": path, "file_size": len(payload)}

    async def delete_file(self, file_path, *, tenant_id):
        self.store.saved_files.pop(file_path, None)


class Queue:
    def __init__(self, store):
        self.store = store

    async def run(self, task_name, **kwargs):
        assert task_name == "process_document"
        row = self.store.documents[kwargs["document_id"]]
        row.is_embedded = True
        row.doc_metadata = {"processing_status": "completed", "synthetic": True}
        self.store.events.append({
            "event_id": DOCUMENT_ID,
            "event_type": "DOCUMENT_PROCESSED",
            "aggregate_id": DOCUMENT_ID,
            "payload": {"case_id": kwargs["case_id"], "document_id": DOCUMENT_ID},
            "created_at": self.store.now.isoformat(),
        })


class SyntheticGoldenPathTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.session = Session(self.store)
        for repository in (CaseRepo, DecisionRepo, DocumentRepo, OverrideRepo):
            repository.store = self.store
        self.bus = Bus(self.store)
        self.app = main.create_app()

        async def db_override():
            yield self.session

        async def config_override():
            return TenantConfig(
                tenant_id=TENANT_ID,
                modules={
                    "llm_classification": False,
                    "auto_messaging": False,
                    "auto_escalation": False,
                },
            )

        self.app.dependency_overrides[get_db] = db_override
        self.app.dependency_overrides[get_tenant_config] = config_override
        from core.event_bus import get_event_bus
        self.app.dependency_overrides[get_event_bus] = lambda: self.bus
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, value in (
            ("api.routes.cases.CaseRepository", CaseRepo),
            ("api.routes.cases.DecisionRepository", DecisionRepo),
            ("api.routes.cases.RuleRepository", RuleRepo),
            ("api.routes.decisions.CaseRepository", CaseRepo),
            ("api.routes.decisions.DecisionRepository", DecisionRepo),
            ("api.routes.decisions.OverrideRepository", OverrideRepo),
            ("api.routes.documents.CaseRepository", CaseRepo),
            ("api.routes.documents.DocumentRepository", DocumentRepo),
            ("api.routes.dashboard.CaseRepository", CaseRepo),
            ("api.routes.dashboard.DecisionRepository", DecisionRepo),
            ("api.routes.dashboard.OverrideRepository", OverrideRepo),
            ("api.routes.documents.get_storage_connector", lambda: Storage(self.store)),
            ("automation.task_queue.get_task_queue", lambda: Queue(self.store)),
            ("api.middleware.RateLimitMiddleware._check_rate_limit", _rate_limit_ok),
        ):
            self.stack.enter_context(patch(target, value))
        self.stack.enter_context(patch.object(get_settings(), "SECRET_KEY", SECRET))

        self.dashboard_module = _load_dashboard_client_module()
        self.dashboard_module.API_BASE = "http://testserver"
        self.dashboard_module._MAX_RETRIES = 1

        def in_process_request(method, url, **kwargs):
            path = urlsplit(url).path
            return self.client.request(
                method,
                path,
                headers=kwargs.get("headers"),
                params=kwargs.get("params"),
                json=kwargs.get("json"),
                data=kwargs.get("data"),
                files=kwargs.get("files"),
            )

        self.stack.enter_context(
            patch.object(self.dashboard_module.requests, "request", in_process_request)
        )

    def test_identity_case_document_decision_override_audit_and_dashboard(self):
        public_client = self.dashboard_module.APIClient(session_cache={})
        self.assertTrue(public_client.get("/health", ttl=0).ok)
        login = public_client.post_form(
            "/auth/login",
            data={
                "username": self.store.user.email,
                "password": PASSWORD,
                "tenant_slug": self.store.tenant.slug,
            },
        )
        self.assertTrue(login.ok, login.error)
        token = login.data["access_token"]
        dashboard_client = self.dashboard_module.APIClient(
            token=token, session_cache={}
        )

        created = dashboard_client.post(
            "/cases/",
            json={
                "case_type": "synthetic_arrears",
                "client_name": "Synthetic Resident",
                "property_address": "Synthetic Property",
                "overdue_days": 95,
                "overdue_amount": 2500000,
                "monthly_rent": 1000000,
                "currency": "COP",
                "raw_data": {"has_legal_action": True},
            },
        )
        self.assertTrue(created.ok, created.error)
        self.assertEqual(created.data["id"], CASE_ID)

        uploaded = dashboard_client.upload(
            "/documents/upload",
            files={"file": ("synthetic.txt", b"Synthetic contract clause", "text/plain")},
            data={"document_type": "contract", "case_id": CASE_ID},
        )
        self.assertTrue(uploaded.ok, uploaded.error)
        self.assertEqual(uploaded.status_code, 202)
        self.assertTrue(self.store.documents[DOCUMENT_ID].is_embedded)

        evaluated = dashboard_client.post(f"/cases/{CASE_ID}/evaluate")
        self.assertTrue(evaluated.ok, evaluated.error)
        self.assertEqual(evaluated.data["decision_id"], DECISION_ID)
        self.assertEqual(self.store.cases[CASE_ID].status, "DECISION_GENERATED")

        overridden = dashboard_client.post(
            f"/decisions/{DECISION_ID}/override",
            json={
                "overridden_action": "MANUAL_REVIEW",
                "reason": "Synthetic human review boundary",
            },
        )
        self.assertTrue(overridden.ok, overridden.error)
        self.assertEqual(self.store.cases[CASE_ID].status, "HUMAN_OVERRIDE")
        self.assertTrue(self.store.decisions[DECISION_ID].is_overridden)

        audit = dashboard_client.get(f"/cases/{CASE_ID}/audit", ttl=0)
        self.assertTrue(audit.ok, audit.error)
        self.assertEqual(
            {event["type"] for event in audit.data["events"]},
            {"created", "document_added", "evaluated", "overridden"},
        )

        operational = dashboard_client.get("/dashboard/operational", ttl=0)
        executive = dashboard_client.get("/dashboard/executive", ttl=0)
        kpis = dashboard_client.get("/dashboard/kpis", ttl=0)
        self.assertTrue(operational.ok, operational.error)
        self.assertTrue(executive.ok, executive.error)
        self.assertTrue(kpis.ok, kpis.error)
        self.assertEqual(operational.data["items"][0]["id"], CASE_ID)
        self.assertEqual(kpis.data["cases"]["total_cases"], 1)
        self.assertEqual(executive.data["overrides"]["override_rate_pct"], 100.0)

        self.assertEqual(len(self.store.cases), 1)
        self.assertEqual(len(self.store.documents), 1)
        self.assertEqual(len(self.store.decisions), 1)
        self.assertEqual(len(self.store.overrides), 1)
        self.assertGreaterEqual(self.session.commits, 4)
        self.assertEqual(self.session.rollbacks, 0)


if __name__ == "__main__":
    unittest.main()
