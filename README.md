# URAKI AI Platform

A multi-tenant decision-support prototype for real-estate operations: versioned rules, deterministic risk and priority, optional AI assistance, human override, and auditable decision records through FastAPI and Streamlit.

**Maturity: FUNCTIONAL PROTOTYPE.** The reviewed, history-free release is public at [JUANC1983/uraki-ai-platform](https://github.com/JUANC1983/uraki-ai-platform), where GitHub Actions runs the offline quality suite and a PostgreSQL 16 migration/constraint contract. No production deployment, users, business outcomes or production security assurance is claimed.

## Product view

![URAKI operational dashboard with a synthetic high-risk case and a human-review recommendation](docs/assets/uraki-dashboard-overview.png)

*Actual Streamlit UI captured at 1440x900 against the in-memory synthetic golden-path backend. Names, identifiers and amounts are synthetic; no live database or provider was used. See [visual evidence and provenance](docs/portfolio/VISUAL_ASSETS.md).*

## Inspect the engineering

- Rules and scoring produce an explainable, frozen `DecisionOutput` with rule/version references and context snapshots.
- Authentication resolves the database user and active tenant; API keys inherit their owner's permissions. Tenant-scoped repositories and role dependencies protect canonical routes.
- AI can assist fallback classification and wording. An LLM classification is advisory metadata and cannot satisfy a decision-rule condition; invalid factual drafts are suppressed. It cannot execute an action.
- Documents use PDF/DOCX/text extraction and JSONB embeddings with Python cosine similarity. This is not a pgvector implementation or an evidenced retrieval-augmented generation system.
- In-process events and jobs have explicit failure limitations. Notification delivery and OCR are not implemented.

[Architecture and decision sequence](docs/ARCHITECTURE.md) | [Security](SECURITY.md) | [Validation](docs/VALIDATION.md) | [Safe walkthrough](docs/GOLDEN_PATH.md)

## Run the offline walkthrough

The reproducible runtime contract targets Python 3.12; the completed local validation used Python 3.11. From a virtual environment:

```sh
python -m pip install -r requirements.txt
python -B demo.py
python -B -m unittest discover -s tests -q
python -B scripts/scan_public_safety.py
```

`demo.py` uses synthetic identities and real internal engines, with simulated communication output. It requires no database or provider credentials and prints `external_writes=false`. It demonstrates valid scoring and rejection of invalid scoring weights. The separate synthetic golden-path test exercises real HTTP routing, JWT authentication and dashboard clients with explicit in-memory database, storage, queue and event fakes.

The local unittest suite covers security boundaries, deterministic workflow, document parsing, mocked provider failures, event handlers, dashboard HTTP retries and startup/readiness. Passing it alone is not evidence of PostgreSQL or Docker execution; consult the public release's GitHub Actions run for the hosted PostgreSQL contract. See the validation matrix for exact limits.

## Run the application locally

```sh
cp .env.example .env
```

Set a randomly generated `SECRET_KEY` (at least 32 characters), your local `DATABASE_URL`, and `RUN_SCHEDULER=false` unless this process owns scheduled work. Review all configuration before running. Provider credentials are optional and must never be committed.

```sh
alembic upgrade head
python -m scripts.bootstrap_admin --tenant-name "Synthetic Demo" --tenant-slug synthetic-demo --email admin@example.com --full-name "Synthetic Admin"
uvicorn main:app --host 127.0.0.1 --port 8000
streamlit run dashboard/app.py
```

Bootstrap prompts for a password without echo. Registration requires an authenticated tenant administrator; login requires a tenant slug. `/health` reports liveness. `/ready` checks database access, expected migration revision and required ownership schema. `DEBUG=true` enables API documentation for development.

Docker definitions exist, default to a single scheduler-owning API worker and run migrations through the entrypoint. Compose requires `POSTGRES_PASSWORD`. Docker and PostgreSQL executables were unavailable during the local run; container execution remains unverified, while the public release's CI exercises migrations and constraints against PostgreSQL 16.

## Repository map

| Classification | Paths | Responsibility |
| --- | --- | --- |
| CORE | `main.py`, `api/`, `agents/`, `core/` | API, identity and decision workflow |
| CORE | `database/`, `alembic/`, `config/` | Tenant persistence, migrations and policy configuration |
| SUPPORTING | `connectors/`, `memory/`, `automation/` | Provider/storage adapters, similarity and process-local work |
| SUPPORTING | `dashboard/`, `executive.py` | Operational UI and executive surface; Streamlit smoke and synthetic browser capture PASS |
| SUPPORTING | `tests/`, `scripts/`, `docs/`, `demo.py` | Verification, bootstrap and synthetic walkthrough |

No legacy implementation is included in the working tree. Generated bytecode and the inherited ZIP are removed; historical copies remain in Git history. The deterministic allowlist export excludes local audit records, archives and bytecode and includes a SHA-256 manifest.

## Trade-offs and production path

Application-level tenant predicates are inspectable but do not replace database row-level security. In-process jobs simplify a prototype but lack a durable queue/outbox and distributed scheduler ownership. JSONB/Python similarity avoids another service but has no measured scalability evidence. Human overrides preserve actor/reason context; AI wording still requires review.

The clean public release passed hosted quality and PostgreSQL contract jobs. Remaining evidence includes full container execution, live provider integration and production operation. Licensing remains a human decision. Existing password hashes created from values over bcrypt's 72-byte limit need an authorized reset before use; this hardening does not rotate credentials.

This engineering checkout retains the identifier `uraki-ai-plataform` and old history. The clean release is published separately as `uraki-ai-platform`; this hardening branch has not been pushed.
