# Security boundaries

URAKI is a prototype. These are implemented controls with local tests, not certification or a completed penetration test.

- Startup rejects missing, placeholder or short signing keys before registering handlers or starting jobs.
- JWT authentication requires subject, tenant, issue time and expiry; identifiers must be UUIDs. Database user role and active user/tenant state govern authorization.
- API keys are hashed and owned by a user. Unowned legacy keys fail closed. Registration requires an authenticated administrator and derives the tenant from that principal; initial administrators use the local bootstrap CLI.
- Passwords use bcrypt. Creation requires 12 or more characters and at most 72 UTF-8 bytes; null characters are rejected. Verification rejects overlength input rather than accepting a truncated prefix. Existing overlength hashes need an authorized password reset, not automatic mutation.
- Repositories scope reads to tenant IDs; route dependencies enforce roles. Storage reads additionally require tenant context and enforce local/S3 namespaces. These tests do not establish PostgreSQL row-level security or immunity to a hostile local filesystem actor.
- Document uploads have size, type, extension and signature checks. Parsing failure and missing embeddings have explicit states. Malware scanning and OCR are absent.
- Provider failure messages are redacted in tested connector paths. Public-safety scanning reports locations/categories instead of credential values.

## Limitations

No MFA, lockout, external security assessment, dependency vulnerability audit, encryption-at-rest assurance or durable distributed job delivery is claimed. Rate-limit storage failure is fail-open. Hosted CI validates current migrations and selected ownership/duplicate-override constraints on ephemeral PostgreSQL; production tenant isolation is not assured. Real document/message data must be treated as confidential; audit/context snapshots can retain such data in actual use.

`scripts/scan_public_safety.py` detects selected credential signatures and generated/private-config artifacts; it is not a complete PII detector. Ignored runtime files and the contents of arbitrary nested archives are outside its automated guarantee. Git history includes old artifacts and requires a publication-specific review.

Do not post credentials, private documents or customer data in public issues. Arrange a private reporting channel with the repository owner before sharing sensitive evidence.
