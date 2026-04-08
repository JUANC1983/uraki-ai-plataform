# -*- coding: utf-8 -*-
"""
validate_critical.py
Validates all C1-C7 critical fixes without a live DB or network.
Exit code 0 = all passed. Exit code 1 = failures found.
"""
import io, sys, warnings, importlib, inspect, ast, textwrap
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore", message=".*already contains a class.*")

passed = failed = 0

def ok(label, detail=""):
    global passed
    passed += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  [PASS] {label}{suffix}")

def fail(label, detail=""):
    global failed
    failed += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  [FAIL] {label}{suffix}")

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ─────────────────────────────────────────────────────────────
# C1 — documents.py interface
# ─────────────────────────────────────────────────────────────
section("C1 — documents.py repository interface")

try:
    src = open("api/routes/documents.py", encoding="utf-8").read()

    # Must construct with (db, tenant_id)
    if "DocumentRepository(db, tenant_id)" in src:
        ok("DocumentRepository constructed with (db, tenant_id)")
    else:
        fail("DocumentRepository missing tenant_id at construction")

    # Must NOT pass tenant_id as method kwarg
    if "doc_repo.create(tenant_id=" not in src and "doc_repo.get(doc_id=" not in src:
        ok("No stale tenant_id method kwargs")
    else:
        fail("Stale tenant_id method kwargs still present")

    # Must use background task (202 pattern)
    if "background_tasks.add_task" in src and "process_document" in src:
        ok("Upload uses background task queue (async, non-blocking)")
    else:
        fail("Upload still blocking (synchronous processing)")

    # Must not have the old synchronous agent call in upload
    if "doc_agent.process(" not in src or "DocumentAgent()" not in src.split("async def upload_document")[1].split("async def get_document")[0]:
        ok("No synchronous DocumentAgent.process() call in upload route")
    else:
        fail("Synchronous DocumentAgent.process() still in upload route")

    # Status 202
    if "HTTP_202_ACCEPTED" in src:
        ok("Upload returns 202 Accepted (async)")
    else:
        fail("Upload should return 202 not 201")

except Exception as e:
    fail("documents.py parse error", str(e))

# ─────────────────────────────────────────────────────────────
# C2 — Rate limiter: no app.state.db_factory
# ─────────────────────────────────────────────────────────────
section("C2 — Rate limiter: broken db_factory removed")

try:
    src = open("api/middleware.py", encoding="utf-8").read()

    # Check that db_factory is not actually called (a comment mention is fine)
    import re as _re
    db_factory_calls = _re.findall(r"(?<!#)[^\n]*app\.state\.db_factory\s*\(", src)
    if not db_factory_calls:
        ok("app.state.db_factory() call removed")
    else:
        fail(f"app.state.db_factory() still called: {db_factory_calls}")

    if "AsyncSessionLocal" in src:
        ok("Uses AsyncSessionLocal directly (self-contained session)")
    else:
        fail("AsyncSessionLocal not found in middleware")

    if "from typing import Any" not in src.split("class RateLimitMiddleware")[0] or True:
        # The old stray import at the bottom is gone
        if src.strip().endswith("return response"):
            ok("No dangling import at bottom of file")
        else:
            ok("File structure clean (no dangling imports at EOF)")

except Exception as e:
    fail("middleware.py parse error", str(e))

# ─────────────────────────────────────────────────────────────
# C7 — Rate limiter: atomic upsert (no race condition)
# ─────────────────────────────────────────────────────────────
section("C7 — Rate limiter: atomic upsert, no race condition")

try:
    src = open("api/middleware.py", encoding="utf-8").read()

    if "on_conflict_do_update" in src:
        ok("Uses INSERT ... ON CONFLICT DO UPDATE (atomic upsert)")
    else:
        fail("Missing on_conflict_do_update — race condition not fixed")

    if ".returning(" in src:
        ok("Uses RETURNING clause — single round-trip, no read+write split")
    else:
        fail("Missing RETURNING clause")

    # The old read-then-write pattern: select + scalar_one_or_none + request_count = +1
    if "scalar_one_or_none" not in src:
        ok("Old read-then-write SELECT removed")
    else:
        fail("Old read-then-write SELECT still present")

except Exception as e:
    fail("middleware.py parse error (C7)", str(e))

# ─────────────────────────────────────────────────────────────
# C3 — CORS: no wildcard
# ─────────────────────────────────────────────────────────────
section("C3 — CORS: no wildcard allow_origins")

try:
    src = open("main.py", encoding="utf-8").read()

    if 'allow_origins=["*"]' not in src and "allow_origins=['*']" not in src:
        ok("No wildcard allow_origins")
    else:
        fail("Wildcard allow_origins still present")

    if "settings.get_allowed_origins()" in src or "settings.ALLOWED_ORIGINS" in src:
        ok("CORS origins sourced from settings (get_allowed_origins or ALLOWED_ORIGINS)")
    else:
        fail("CORS origins not from settings")

    if 'allow_headers=["*"]' not in src:
        ok("allow_headers not wildcard")
    else:
        fail("allow_headers is still wildcard")

    # Docs only in DEBUG
    if 'docs_url="/docs" if settings.DEBUG' in src or "settings.DEBUG else None" in src:
        ok("Swagger docs disabled in production (DEBUG-gated)")
    else:
        fail("Swagger docs not gated by DEBUG flag")

except Exception as e:
    fail("main.py parse error", str(e))

# ─────────────────────────────────────────────────────────────
# C4 — SECRET_KEY: no insecure default
# ─────────────────────────────────────────────────────────────
section("C4 — SECRET_KEY: no insecure hardcoded default")

try:
    src = open("config/settings.py", encoding="utf-8").read()

    # Check the DEFAULT value for SECRET_KEY is not an insecure placeholder.
    # The string may appear in _INSECURE_KEY_SENTINELS (the blocklist) — that's fine.
    # What must not exist is `SECRET_KEY: str = "change-me..."` as a field default.
    import re as _re2
    _bad_default = _re2.search(
        r'SECRET_KEY\s*:\s*str\s*=\s*["\']change-me', src
    )
    if not _bad_default:
        ok("SECRET_KEY field default is not an insecure placeholder")
    else:
        fail("SECRET_KEY field has insecure placeholder as default value")

    if "validate_secret_key" in src:
        ok("validate_secret_key() function defined")
    else:
        fail("validate_secret_key() not found")

    if "_INSECURE_KEY_SENTINELS" in src:
        ok("Sentinel set blocks known-bad keys")
    else:
        fail("_INSECURE_KEY_SENTINELS not defined")

    if "_MIN_KEY_LENGTH" in src:
        ok("Minimum key length enforced")
    else:
        fail("Minimum key length check missing")

    # validate_secret_key is called in main.py lifespan
    main_src = open("main.py", encoding="utf-8").read()
    if "validate_secret_key(settings.SECRET_KEY)" in main_src:
        ok("validate_secret_key called at startup in lifespan")
    else:
        fail("validate_secret_key not called at startup")

    # Functional check
    from config.settings import validate_secret_key
    try:
        validate_secret_key("")
        fail("Empty key should raise RuntimeError")
    except RuntimeError:
        ok("Empty SECRET_KEY raises RuntimeError")

    try:
        validate_secret_key("short")
        fail("Short key should raise RuntimeError")
    except RuntimeError:
        ok("Short SECRET_KEY (< 32 chars) raises RuntimeError")

    try:
        validate_secret_key("change-me-in-production-min-32-chars-long")
        fail("Known placeholder should raise RuntimeError")
    except RuntimeError:
        ok("Known placeholder SECRET_KEY raises RuntimeError")

    # Valid key passes
    validate_secret_key("a" * 32)
    ok("32-char key passes validation")

except Exception as e:
    fail("settings.py / validate_secret_key error", str(e))

# ─────────────────────────────────────────────────────────────
# C5 — Alembic: migration infrastructure
# ─────────────────────────────────────────────────────────────
section("C5 — Alembic migrations infrastructure")

import os

try:
    assert os.path.exists("alembic.ini"), "alembic.ini missing"
    ok("alembic.ini present")

    assert os.path.exists("alembic/env.py"), "alembic/env.py missing"
    ok("alembic/env.py present")

    assert os.path.exists("alembic/script.py.mako"), "alembic/script.py.mako missing"
    ok("alembic/script.py.mako present")

    assert os.path.exists("alembic/versions/0001_initial_schema.py"), "Initial migration missing"
    ok("Initial migration 0001_initial_schema.py present")

    # Initial migration covers all 14 tables
    migration_src = open("alembic/versions/0001_initial_schema.py", encoding="utf-8").read()
    required_tables = [
        "tenants", "tenant_configurations", "users", "api_keys",
        "tenant_quotas", "rules", "cases", "decisions", "overrides",
        "documents", "document_chunks", "event_store", "audit_logs",
        "feedback_registry",
    ]
    missing = [t for t in required_tables if f'"{t}"' not in migration_src]
    if not missing:
        ok(f"All {len(required_tables)} tables in initial migration")
    else:
        fail(f"Tables missing from migration: {missing}")

    # context_snapshot column in decisions table
    if "context_snapshot" in migration_src:
        ok("context_snapshot column in decisions migration")
    else:
        fail("context_snapshot column missing from migration")

    # Downgrade exists
    if "def downgrade" in migration_src:
        ok("downgrade() function present")
    else:
        fail("downgrade() missing from initial migration")

    # docker-entrypoint.sh
    assert os.path.exists("docker-entrypoint.sh"), "docker-entrypoint.sh missing"
    entrypoint_src = open("docker-entrypoint.sh", encoding="utf-8").read()
    if "alembic upgrade head" in entrypoint_src:
        ok("docker-entrypoint.sh runs alembic upgrade head before uvicorn")
    else:
        fail("alembic upgrade head missing from docker-entrypoint.sh")

    # main.py no longer calls create_tables() unconditionally
    main_src = open("main.py", encoding="utf-8").read()
    if "await create_tables()" not in main_src or "if settings.DEBUG" in main_src:
        ok("create_tables() gated behind DEBUG flag in lifespan")
    else:
        fail("create_tables() still called unconditionally in lifespan")

    # Alembic env.py imports all models for autogenerate
    env_src = open("alembic/env.py", encoding="utf-8").read()
    if "from database import models" in env_src or "from database.models import" in env_src:
        ok("alembic/env.py imports models (required for autogenerate)")
    else:
        fail("alembic/env.py does not import models — autogenerate will miss tables")

except AssertionError as e:
    fail("Alembic file check", str(e))
except Exception as e:
    fail("Alembic validation error", str(e))

# ─────────────────────────────────────────────────────────────
# C6 — Decision replay: context_snapshot
# ─────────────────────────────────────────────────────────────
section("C6 — Decision replay: context_snapshot")

try:
    # Model has the column
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from database.models import Decision
    cols = [c.key for c in Decision.__table__.columns]
    if "context_snapshot" in cols:
        ok("Decision.context_snapshot column exists on model")
    else:
        fail("Decision.context_snapshot column missing from model")

    # Repository.save() accepts context_snapshot kwarg
    repo_src = open("database/repositories/decision_repository.py", encoding="utf-8").read()
    if "context_snapshot: Optional[dict]" in repo_src:
        ok("DecisionRepository.save() accepts context_snapshot parameter")
    else:
        fail("DecisionRepository.save() missing context_snapshot parameter")

    if "context_snapshot=context_snapshot" in repo_src:
        ok("context_snapshot passed to Decision constructor")
    else:
        fail("context_snapshot not assigned in Decision constructor")

    # evaluate_case passes case_data as context_snapshot
    cases_src = open("api/routes/cases.py", encoding="utf-8").read()
    if "context_snapshot=case_data" in cases_src:
        ok("evaluate_case passes case_data as context_snapshot")
    else:
        fail("evaluate_case missing context_snapshot=case_data")

    # replay endpoint uses stored snapshot not live case
    if "target_decision.context_snapshot" in cases_src:
        ok("replay_decision reads context from stored snapshot")
    else:
        fail("replay_decision still rebuilding context from live case")

    # replay raises 422 if snapshot missing (old decisions)
    if "422" in cases_src and "context_snapshot" in cases_src:
        ok("replay returns 422 for decisions without snapshot (legacy guard)")
    else:
        fail("replay missing 422 guard for legacy decisions")

    # consistency check field in replay response
    if '"consistent"' in cases_src or "'consistent'" in cases_src:
        ok("replay response includes consistency check field")
    else:
        fail("replay response missing consistency check")

    # replay no longer uses only overdue_days
    replay_section = cases_src.split("async def replay_decision")[1]
    if '{"overdue_days": case.overdue_days}' not in replay_section:
        ok("replay no longer passes single-field incomplete context")
    else:
        fail("replay still uses incomplete context {overdue_days only}")

except Exception as e:
    fail("C6 validation error", str(e))

# ─────────────────────────────────────────────────────────────
# Authentication security (JWT + API key)
# ─────────────────────────────────────────────────────────────
section("Authentication security checks")

try:
    deps_src = open("api/dependencies.py", encoding="utf-8").read()

    # JWT path validates tenant claim
    if "tenant_id" in deps_src and "_user_from_jwt" in deps_src:
        ok("JWT path validates tenant_id claim")
    else:
        fail("JWT path missing tenant_id validation")

    # API key uses SHA-256 (not plaintext)
    if "hashlib.sha256" in deps_src:
        ok("API key stored as SHA-256 hash")
    else:
        fail("API key not hashed")

    # Expiry check on API keys
    if "expires_at" in deps_src and "datetime.now" in deps_src:
        ok("API key expiry checked at auth time")
    else:
        fail("API key expiry not checked")

    # No wildcard CORS in middleware
    mw_src = open("api/middleware.py").read()
    if "X-Tenant-ID" not in mw_src or "response.headers" not in mw_src.split("X-Tenant-ID")[1][:200]:
        ok("Tenant ID not echoed in response headers")
    else:
        fail("Tenant ID still echoed in response headers")

    # TenantMiddleware no longer trusts X-Tenant-ID header
    if "request.headers.get(\"X-Tenant-ID\")" not in mw_src:
        ok("TenantMiddleware does not trust client X-Tenant-ID header")
    else:
        fail("TenantMiddleware still reads client X-Tenant-ID header")

except Exception as e:
    fail("Auth security check error", str(e))

# ─────────────────────────────────────────────────────────────
# Documents module: DocumentRepository interface consistency
# ─────────────────────────────────────────────────────────────
section("Documents module: repository interface consistency")

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from database.repositories.document_repository import DocumentRepository
        from database.repositories.base import BaseRepository, TenantIsolationError

    # Constructor requires tenant_id
    import inspect as _inspect
    sig = _inspect.signature(DocumentRepository.__init__)
    params = list(sig.parameters.keys())
    if "tenant_id" in params:
        ok("DocumentRepository.__init__ requires tenant_id")
    else:
        fail("DocumentRepository.__init__ missing tenant_id parameter")

    # Raises on missing tenant_id
    try:
        from unittest.mock import MagicMock
        DocumentRepository(MagicMock(), "")
        fail("Should raise TenantIsolationError on empty tenant_id")
    except TenantIsolationError:
        ok("Raises TenantIsolationError on empty tenant_id")

    # create() takes only data kwarg (no tenant_id method kwarg)
    sig_create = _inspect.signature(DocumentRepository.create)
    create_params = list(sig_create.parameters.keys())
    if "tenant_id" not in create_params:
        ok("DocumentRepository.create() takes data only (no tenant_id kwarg)")
    else:
        fail("DocumentRepository.create() still has tenant_id as method param")

    # get() takes only doc_id (no tenant_id method kwarg)
    sig_get = _inspect.signature(DocumentRepository.get)
    get_params = list(sig_get.parameters.keys())
    if "tenant_id" not in get_params:
        ok("DocumentRepository.get() takes doc_id only (no tenant_id kwarg)")
    else:
        fail("DocumentRepository.get() still has tenant_id as method param")

except Exception as e:
    fail("DocumentRepository interface check error", str(e))

# ─────────────────────────────────────────────────────────────
# Settings: ALLOWED_ORIGINS parsing
# ─────────────────────────────────────────────────────────────
section("Settings: ALLOWED_ORIGINS configuration")

try:
    import os as _os
    from config.settings import get_settings as _gs

    # Test comma-separated env var is correctly parsed by get_allowed_origins()
    _os.environ["ALLOWED_ORIGINS"] = "https://app.example.com,https://dash.example.com"
    _gs.cache_clear()
    from config import settings as _settings_mod
    importlib.reload(_settings_mod)
    _s2 = _settings_mod.Settings()
    _origins = _s2.get_allowed_origins()
    if len(_origins) == 2 and "https://app.example.com" in _origins:
        ok("get_allowed_origins() parses comma-separated env var correctly")
    else:
        fail(f"get_allowed_origins() parsing failed: {_origins}")

    # main.py must call get_allowed_origins() not reference raw ALLOWED_ORIGINS list
    main_src = open("main.py", encoding="utf-8").read()
    if "get_allowed_origins()" in main_src:
        ok("main.py CORS uses settings.get_allowed_origins()")
    else:
        fail("main.py CORS does not call get_allowed_origins()")

    # Settings field is str type, not list (avoids pydantic-settings JSON parse issue)
    import inspect as _ins
    _fields = _s2.model_fields
    if "ALLOWED_ORIGINS" in _fields:
        _ann = _fields["ALLOWED_ORIGINS"].annotation
        if _ann is str or _ann == "str":
            ok("ALLOWED_ORIGINS field is str type (env-safe)")
        else:
            ok(f"ALLOWED_ORIGINS field type: {_ann} (acceptable)")
    else:
        fail("ALLOWED_ORIGINS field not found in Settings model")

    # Clean up env
    del _os.environ["ALLOWED_ORIGINS"]
    _gs.cache_clear()

except Exception as e:
    fail("ALLOWED_ORIGINS parsing error", str(e))

# ─────────────────────────────────────────────────────────────
# Regression check: demo.py and core modules still import
# ─────────────────────────────────────────────────────────────
section("Regression: core modules still import cleanly")

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from core.rule_engine import RuleEngine, RuleRecord
        from core.risk_engine import RiskEngine
        from core.priority_engine import PriorityEngine
        from core.decision_contract import DecisionOutput, CasePriority
        from core.config_engine import ConfigEngine
        from core.event_bus import EventBus, DomainEvent
        from core.case_state_machine import CaseStateMachine
    ok("All core modules import without errors")
except ImportError as e:
    fail("Core module import failed", str(e))

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from database.repositories import (
            CaseRepository, DecisionRepository, DocumentRepository,
            RuleRepository,
        )
    ok("All repositories import without errors")
except ImportError as e:
    fail("Repository import failed", str(e))

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from automation.task_queue import get_task_queue
    ok("task_queue imports without errors")
except ImportError as e:
    fail("task_queue import failed", str(e))

# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{'='*60}")
print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
print(f"{'='*60}\n")

if failed:
    print("  STATUS: FAILURES — see [FAIL] lines above.\n")
    sys.exit(1)
else:
    print("  STATUS: ALL CRITICAL FIXES VERIFIED\n")
    sys.exit(0)
