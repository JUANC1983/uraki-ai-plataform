# Validation evidence

Snapshot: 2026-09-14, local Python 3.11. Local evidence is identified below; hosted evidence applies to the separate clean public release at commit `d9128919d6445b9d80e1fbe5d20e71ff05637512`.

| Surface | Evidence | Status / limit |
| --- | --- | --- |
| Auth and storage | JWT, password, API-key, path and S3 namespace tests | L2; mocked DB/provider, real temporary local files |
| API workflow/startup | TestClient and mocked sessions | L3 in-process; no real PostgreSQL |
| Latest broad suite | 134 tests PASS after dashboard and CI portability fixes | Local only; final engineering-checkout run |
| Syntax | AST parse of all Python sources | PASS at last recorded run; writes no bytecode |
| Demo | `python -B demo.py` | Offline engine walkthrough; valid and invalid configuration paths |
| Credential/artifact scan | 164 current tracked/nonignored files plus reachable Git history scanned | No selected credential signatures or current generated/runtime artifacts detected; manual privacy review remains open |
| Persistence | 0001-0003 upgrade/full downgrade compile offline; ORM constraints, transaction rollback and entity/event atomicity tested | Local/mocked PASS; clean-release CI passed migration, downgrade/upgrade and selected constraint rejection against ephemeral PostgreSQL 16 |
| API contracts | Every successful JSON operation has an explicit OpenAPI schema; strict inputs, generic 500s, read side effects and tenant-scoped row locks tested | L3 in-process; no live PostgreSQL |
| Docker | Container contracts tested statically | BLOCKED_BY_ENVIRONMENT: docker executable unavailable |
| PostgreSQL | No local psql executable | BLOCKED_BY_ENVIRONMENT for live validation |
| AI quality | Structured-output tests plus 8 deterministic boundary evals | PASS locally for authority/fallback/factual-draft cases; no live model benchmark |
| Dashboard | HTTP client contracts, Streamlit login render and a 1440x900 browser capture | Local PASS against the in-memory synthetic golden-path backend; no live PostgreSQL/provider claim |
| Synthetic golden path | Dashboard client -> JWT login -> case -> document -> decision -> override -> audit/events -> dashboard | PASS in-process with explicit memory fakes; no PostgreSQL/provider claims |
| Dependency spec | 24 direct runtime dependencies use exact pins; CI and Docker target Python 3.12 | Contract PASS; clean-release hosted CI installed the pins and passed `pip check` |
| CI | Two jobs: offline quality and PostgreSQL 16 migration/constraint contract | Clean public release PASS; hardening PR #1 is published and remains unmerged; current hosted status is visible in GitHub Actions |
| Public release | Deterministic allowlist, SHA-256 manifest and validation from copied tree | PASS; 165 files at `JUANC1983/uraki-ai-platform`, no old Git history or private audit records |

## Reproduce available checks

```sh
python -B -m unittest discover -s tests -q
python -B demo.py
python -B scripts/scan_public_safety.py
python -B scripts/scan_public_safety.py --history
git diff --check
```

When PostgreSQL is available on a disposable migrated database, run
`python -B -m scripts.verify_postgres_constraints`. It rolls back all synthetic
rows and must report cross-tenant and duplicate-override rejection.

Set `PYTHONDONTWRITEBYTECODE=1` and `DEBUG=false` for local checks. Test names under `tests/integration` do not imply a live database: inspect their injected sessions. No credentials or paid provider access are required by the available suite.

The clean release is a published functional prototype with hosted CI PASS. This engineering checkout retains old history, so it must not be represented as the same history-free public tree. Docker execution, live providers, production operation and licensing retain their stated limits.
