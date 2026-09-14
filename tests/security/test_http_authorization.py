"""Real ASGI routing/auth/RBAC with a deliberately small SQL session double.

Only persistence and rate-limit storage are substituted; JWT/user dependencies
are not overridden. This is not evidence of PostgreSQL constraint behavior.
"""
import time
import io
import zipfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.sql import visitors, operators
from sqlalchemy.sql.elements import BinaryExpression, BindParameter

import main
from api.dependencies import get_current_user, get_tenant_config
from core.config_engine import TenantConfig
from database.base import get_db
from database.models import User, Tenant, Case, Decision, Document

A = "00000000-0000-0000-0000-000000000001"
B = "00000000-0000-0000-0000-000000000002"
USER = "00000000-0000-0000-0000-000000000003"
RESOURCE = "00000000-0000-0000-0000-000000000004"
KEY = "synthetic-http-signing-key-32-characters"


class Session:
    def __init__(self):
        self.user = User(id=USER, tenant_id=A, role="operador", is_active=True)
        self.resource_tenant = A
        self.added = []
        self.queries = []
        self.now = datetime.now(timezone.utc)
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, query):
        self.queries.append(query)
        model = query.column_descriptions[0]["entity"]
        equalities = {}
        for clause in query._where_criteria:
            for node in visitors.iterate(clause):
                if isinstance(node, BinaryExpression) and node.operator is operators.eq and isinstance(node.right, BindParameter):
                    equalities[node.left.key] = node.right.value
        if model is User:
            row = self.user if equalities.get("id") == USER and equalities.get("tenant_id") == A else None
        elif model is Tenant:
            row = Tenant(id=A, name="Synthetic A", slug="synthetic-a", plan="starter") if equalities.get("id") == A else None
        elif model in (Case, Decision, Document):
            if equalities.get("tenant_id") != A:
                raise AssertionError("Resource query lost authenticated tenant predicate")
            row = None
            if model is Case and equalities.get("id") == RESOURCE and self.resource_tenant == A:
                row = Case(id=RESOURCE, tenant_id=A, status="NEW", priority="MEDIUM", case_type="arrears", client_name="Synthetic", overdue_days=0, overdue_amount=0, monthly_rent=1, currency="COP", raw_data={}, created_at=self.now)
            if model is Decision and equalities.get("id") == RESOURCE and self.resource_tenant == A:
                row = Decision(id=RESOURCE, tenant_id=A, case_id=RESOURCE, classification="OTRO", risk_score=0, risk_level="BAJO", action="REVIEW", firmness="FIRME", escalation_required=False, legal_flag=False, policy_flag=False, rationale="Synthetic", confidence=1, is_overridden=False, full_output={}, created_at=self.now)
            if model is Document and equalities.get("id") == RESOURCE and self.resource_tenant == A:
                row = Document(id=RESOURCE, tenant_id=A, document_type="note", file_name="synthetic.txt", file_size=1, mime_type="text/plain", is_embedded=False, doc_metadata={}, created_at=datetime.now(timezone.utc))
        else:
            raise AssertionError(f"Unconfigured SQL model: {model}")
        return SimpleNamespace(scalar_one_or_none=lambda: row, scalars=lambda: SimpleNamespace(all=lambda: []))

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, row):
        row.id = RESOURCE


class HTTPAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.db = Session()
        self.app = main.create_app()
        async def db_override():
            yield self.db
        async def config_override():
            return TenantConfig(tenant_id=A)
        self.app.dependency_overrides[get_db] = db_override
        self.app.dependency_overrides[get_tenant_config] = config_override
        self.assertNotIn(get_current_user, self.app.dependency_overrides)
        self.secret = patch.object(main.settings, "SECRET_KEY", KEY)
        self.secret.start()
        self.addCleanup(self.secret.stop)
        self.rate = patch("api.middleware.RateLimitMiddleware._check_rate_limit", new_callable=AsyncMock, return_value=(False, ""))
        self.rate.start()
        self.addCleanup(self.rate.stop)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def headers(self, **claims):
        payload = {"sub": USER, "tenant_id": A, "role": "admin", "iat": int(time.time()), "exp": int(time.time()) + 120, **claims}
        return {"Authorization": "Bearer " + jwt.encode(payload, KEY, algorithm="HS256")}

    def test_every_protected_route_rejects_missing_auth(self):
        checked = 0
        for route in self.app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1/") or route.path.endswith("/auth/login"):
                continue
            path = route.path
            for parameter in route.param_convertors:
                path = path.replace("{" + parameter + "}", RESOURCE)
            for method in route.methods:
                with self.subTest(method=method, path=path):
                    response = self.client.request(method, path, json={})
                    self.assertEqual(response.status_code, 401, response.text)
                    checked += 1
        self.assertGreater(checked, 20)
        self.assertEqual(self.db.queries, [])

    def test_invalid_expired_wrong_tenant_and_forged_tokens(self):
        headers = [self.headers(tenant_id=B), self.headers(exp=int(time.time())-1), {"Authorization": "Bearer invalid"}]
        forged = jwt.encode({"sub": USER, "tenant_id": A, "iat": int(time.time()), "exp": int(time.time())+60}, "different-synthetic-signing-key-32", algorithm="HS256")
        headers.append({"Authorization": "Bearer " + forged})
        for value in headers:
            with self.subTest(kind=value["Authorization"][:14]):
                response = self.client.get("/api/v1/documents/" + RESOURCE, headers=value)
                self.assertEqual(response.status_code, 401)

    def test_normal_user_reads_own_document_but_not_other_tenant(self):
        path = "/api/v1/documents/" + RESOURCE
        response = self.client.get(path, headers={**self.headers(), "X-Tenant-ID": B}, params={"tenant_id": B, "role": "admin"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["file_name"], "synthetic.txt")
        self.db.resource_tenant = B
        self.assertEqual(self.client.get(path, headers=self.headers()).status_code, 404)

    def test_cross_tenant_ids_reject_reads_and_mutations(self):
        self.db.resource_tenant = B
        routes = [("GET", "/cases/"+RESOURCE, None), ("GET", "/decisions/"+RESOURCE, None), ("GET", "/documents/"+RESOURCE, None), ("POST", "/cases/"+RESOURCE+"/evaluate", None), ("POST", "/cases/"+RESOURCE+"/transition", {"target_status":"IN_REVIEW"}), ("POST", "/decisions/"+RESOURCE+"/override", {"overridden_action":"REVIEW", "reason":"Synthetic reason"})]
        for method, path, body in routes:
            with self.subTest(path=path):
                response = self.client.request(method, "/api/v1"+path, headers=self.headers(), json=body)
                self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.db.added, [])

    def test_claimed_admin_cannot_elevate_database_operator(self):
        for method,path,body in [("GET","/dashboard/executive",None),("GET","/dashboard/events",None),("GET","/tenants/me/api-keys",None),("POST","/tenants/me/config",{}),("POST","/tenants/me/rules",{}),("POST","/auth/register",{"email":"synthetic@example.com","password":"synthetic-password","full_name":"Synthetic","role":"admin"})]:
            with self.subTest(path=path):
                response = self.client.request(method,"/api/v1"+path,headers=self.headers(),json=body)
                self.assertEqual(response.status_code,403,response.text)

    def test_admin_registration_and_tenant_payload_boundary(self):
        self.db.user.role = "admin"
        body = {"email":"synthetic@example.com","password":"synthetic-password","full_name":"Synthetic","role":"operador"}
        response = self.client.post("/api/v1/auth/register",headers=self.headers(),json=body)
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(self.db.added[-1].tenant_id,A)
        response = self.client.post("/api/v1/auth/register",headers=self.headers(),json={**body,"tenant_id":B})
        self.assertEqual(response.status_code,422,response.text)

    def test_case_payload_cannot_choose_tenant_or_role(self):
        for field,value in (("tenant_id",B),("role","admin")):
            response=self.client.post("/api/v1/cases/",headers=self.headers(),json={"case_type":"arrears","client_name":"Synthetic",field:value})
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.db.added,[])

    def test_read_only_role_cannot_call_mutating_routes(self):
        self.db.user.role="ejecutivo"
        for route in self.app.routes:
            if not isinstance(route,APIRoute) or not route.path.startswith("/api/v1/") or route.path.endswith(("/auth/login","/documents/search")):
                continue
            path=route.path
            for parameter in route.param_convertors:
                path=path.replace("{"+parameter+"}",RESOURCE)
            for method in route.methods & {"POST","PUT","PATCH","DELETE"}:
                body={"email":"synthetic@example.com","password":"synthetic-password","full_name":"Synthetic","role":"admin"} if path.endswith("/auth/register") else {}
                with self.subTest(method=method,path=path):
                    response=self.client.request(method,path,headers=self.headers(),json=body)
                    self.assertEqual(response.status_code,403,response.text)
        self.assertEqual(self.db.added,[])

    def test_upload_for_foreign_case_rejects_before_storage(self):
        self.db.resource_tenant=B
        with patch("api.routes.documents.get_storage_connector") as storage:
            response=self.client.post("/api/v1/documents/upload",headers=self.headers(),data={"document_type":"note","case_id":RESOURCE,"tenant_id":B},files={"file":("synthetic.txt",b"synthetic","text/plain")})
            self.assertEqual(response.status_code,404,response.text)
            storage.assert_not_called()

    def test_malformed_docx_rejects_before_storage(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,"w") as archive:
            archive.writestr("unrelated.txt","synthetic")
        with patch("api.routes.documents.get_storage_connector") as storage:
            response=self.client.post("/api/v1/documents/upload",headers=self.headers(),data={"document_type":"contract"},files={"file":("synthetic.docx",stream.getvalue(),"application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
            self.assertEqual(response.status_code,400,response.text)
            storage.assert_not_called()

    def test_upload_persistence_failure_removes_saved_file(self):
        storage=SimpleNamespace(
            save_file=AsyncMock(return_value={"file_path":"synthetic-path","file_size":"9"}),
            delete_file=AsyncMock(),
        )
        with patch("api.routes.documents.get_storage_connector",return_value=storage), patch("api.routes.documents.DocumentRepository.create",new_callable=AsyncMock,side_effect=RuntimeError("synthetic persistence failure")):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/v1/documents/upload",headers=self.headers(),data={"document_type":"note"},files={"file":("synthetic.txt",b"synthetic","text/plain")})
        storage.delete_file.assert_awaited_once_with("synthetic-path",tenant_id=A)

    def test_own_case_decision_and_tenant_are_readable(self):
        for path in ("/cases/"+RESOURCE,"/decisions/"+RESOURCE,"/tenants/me","/tenants/me/config"):
            with self.subTest(path=path):
                response=self.client.get("/api/v1"+path,headers=self.headers())
                self.assertEqual(response.status_code,200,response.text)

    def test_admin_dashboard_and_normal_operational_read_use_current_tenant(self):
        with patch("api.routes.dashboard.CaseRepository.get_kpis",new_callable=AsyncMock,return_value={}) as cases, patch("api.routes.dashboard.DecisionRepository.get_stats",new_callable=AsyncMock,return_value={}) as decisions:
            response=self.client.get("/api/v1/dashboard/kpis",headers=self.headers())
            self.assertEqual(response.status_code,200,response.text)
            cases.assert_awaited_once()
            decisions.assert_awaited_once()
        self.db.user.role="admin"
        response=self.client.get("/api/v1/tenants/me",headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["id"],A)

    def test_invalid_identifiers_and_query_bounds_fail_before_resource_access(self):
        self.db.user.role = "admin"
        requests = [
            ("GET", "/api/v1/cases/not-a-uuid", None),
            ("GET", "/api/v1/decisions/not-a-uuid", None),
            ("GET", "/api/v1/documents/not-a-uuid", None),
            ("GET", "/api/v1/tenants/me/rules/not-a-uuid/history", None),
            ("DELETE", "/api/v1/tenants/me/api-keys/not-a-uuid", None),
            ("GET", "/api/v1/cases/?limit=0", None),
            ("GET", "/api/v1/cases/?priority=urgent", None),
            ("GET", "/api/v1/dashboard/operational?offset=-1", None),
            ("GET", f"/api/v1/cases/{RESOURCE}/replay?at=not-a-date", None),
        ]
        for method, path, body in requests:
            with self.subTest(path=path):
                response = self.client.request(method, path, headers=self.headers(), json=body)
                self.assertEqual(response.status_code, 422, response.text)

        response = self.client.get(
            f"/api/v1/cases/{RESOURCE}/replay?at=2026-01-01T00:00:00",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_strict_mutation_payloads_and_api_key_expiration(self):
        self.db.user.role = "admin"
        response = self.client.post(
            f"/api/v1/decisions/{RESOURCE}/override",
            headers=self.headers(),
            json={"overridden_action":"REVIEW","reason":"Synthetic","tenant_id":B},
        )
        self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post(
            "/api/v1/tenants/",
            headers=self.headers(),
            json={"name":"Synthetic","slug":"synthetic","plan":"starter","role":"owner"},
        )
        self.assertEqual(response.status_code, 422, response.text)
        for expiration in ("2026-01-01T00:00:00", "2020-01-01T00:00:00+00:00"):
            response = self.client.post(
                "/api/v1/tenants/me/api-keys",
                headers=self.headers(),
                json={"name":"Synthetic","expires_at":expiration},
            )
            self.assertEqual(response.status_code, 422, response.text)

    def test_read_routes_do_not_commit_core_state(self):
        with patch("api.routes.dashboard.CaseRepository.get_kpis",new_callable=AsyncMock,return_value={}), patch("api.routes.dashboard.DecisionRepository.get_stats",new_callable=AsyncMock,return_value={}):
            for path in (
                f"/api/v1/cases/{RESOURCE}",
                f"/api/v1/decisions/{RESOURCE}",
                f"/api/v1/documents/{RESOURCE}",
                "/api/v1/tenants/me/config",
                "/api/v1/dashboard/kpis",
            ):
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path,headers=self.headers()).status_code,200)
        self.assertEqual(self.db.commits,0)

    def test_unexpected_server_failure_does_not_expose_private_detail(self):
        private = "private database host and record contents"
        with patch("api.routes.cases.CaseRepository.get",new_callable=AsyncMock,side_effect=RuntimeError(private)):
            client = TestClient(self.app, raise_server_exceptions=False)
            try:
                response = client.get(f"/api/v1/cases/{RESOURCE}",headers=self.headers())
            finally:
                client.close()
        self.assertEqual(response.status_code,500)
        self.assertNotIn(private,response.text)
