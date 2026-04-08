"""Initial schema — all 14 tables

Revision ID: 0001
Revises:
Create Date: 2026-04-07

NOTE: If the database already exists (created via create_tables() before
Alembic was set up), stamp it at this revision without running the upgrade:

    alembic stamp 0001
    alembic upgrade head    # applies only 0002 and later

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ tenants
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("plan", sa.String(50), nullable=False, server_default="starter"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # -------------------------------------------------------- tenant_configurations
    op.create_table(
        "tenant_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("config_key", sa.String(200), nullable=False),
        sa.Column("config_value", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "config_key", name="uq_tenant_configurations_tenant_key"),
    )

    # ---------------------------------------------------------------------- users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )

    # --------------------------------------------------------------------- api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("key_hash", sa.String(256), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_api_keys_tenant", "api_keys", ["tenant_id"])

    # ----------------------------------------------------------------- tenant_quotas
    op.create_table(
        "tenant_quotas",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("window_key", sa.String(50), nullable=False),
        sa.Column("window_type", sa.String(20), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "window_key", name="uq_tenant_quotas_tenant_window"),
    )

    # ----------------------------------------------------------------------- rules
    op.create_table(
        "rules",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        # Self-referential FK — added as separate constraint below
        sa.Column("parent_rule_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("constraints", postgresql.JSONB(), nullable=True),
        sa.Column("explanation_template", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("effective_from", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rules_tenant_active", "rules", ["tenant_id", "is_active"])
    op.create_index("ix_rules_tenant_category", "rules", ["tenant_id", "category"])
    # Self-referential FK added after table exists
    op.create_foreign_key(
        "fk_rules_parent_rule_id",
        "rules", "rules",
        ["parent_rule_id"], ["id"],
        ondelete="SET NULL",
    )

    # ----------------------------------------------------------------------- cases
    op.create_table(
        "cases",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_ref", sa.String(200), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="NEW"),
        sa.Column("priority", sa.String(20), nullable=True),
        sa.Column("case_type", sa.String(100), nullable=False),
        sa.Column("client_name", sa.String(300), nullable=False),
        sa.Column("client_id_number", sa.String(100), nullable=True),
        sa.Column("property_address", sa.String(500), nullable=True),
        sa.Column("contract_id", sa.String(200), nullable=True),
        sa.Column("overdue_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overdue_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("monthly_rent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="COP"),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cases_tenant_status", "cases", ["tenant_id", "status"])
    op.create_index("ix_cases_tenant_created", "cases", ["tenant_id", "created_at"])

    # ------------------------------------------------------------------- decisions
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("classification", sa.String(100), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(50), nullable=False),
        sa.Column("priority", sa.String(20), nullable=True),
        sa.Column("action", sa.String(200), nullable=False),
        sa.Column("firmness", sa.String(50), nullable=False),
        sa.Column("escalation_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("escalation_target", sa.String(100), nullable=True),
        sa.Column("legal_flag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("policy_flag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("validations_missing", postgresql.JSONB(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("rule_id_applied", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("rule_version_used", sa.Integer(), nullable=True),
        sa.Column("document_references", postgresql.JSONB(), nullable=True),
        sa.Column("context_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("suggested_message", sa.Text(), nullable=True),
        sa.Column("full_output", postgresql.JSONB(), nullable=False),
        sa.Column("is_overridden", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_decisions_tenant_case", "decisions", ["tenant_id", "case_id"])
    op.create_index("ix_decisions_created", "decisions", ["tenant_id", "created_at"])

    # ------------------------------------------------------------------- overrides
    op.create_table(
        "overrides",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("original_action", sa.String(200), nullable=False),
        sa.Column("overridden_action", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------- documents
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("cases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("contract_id", sa.String(200), nullable=True),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mime_type", sa.String(200), nullable=False),
        sa.Column("parsed_text", sa.Text(), nullable=True),
        sa.Column("doc_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("is_embedded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --------------------------------------------------------------- document_chunks
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("clause_label", sa.String(200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.JSONB(), nullable=True),
        sa.Column("doc_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chunks_tenant_doc", "document_chunks", ["tenant_id", "document_id"])

    # ------------------------------------------------------------------ event_store
    op.create_table(
        "event_store",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_events_tenant_type", "event_store", ["tenant_id", "event_type"])
    op.create_index("ix_events_aggregate", "event_store", ["tenant_id", "aggregate_id"])
    op.create_index("ix_events_created", "event_store", ["created_at"])

    # ------------------------------------------------------------------ audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_tenant_event", "audit_logs", ["tenant_id", "event_type"])
    op.create_index("ix_audit_created", "audit_logs", ["created_at"])

    # --------------------------------------------------------------- feedback_registry
    op.create_table(
        "feedback_registry",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("feedback_type", sa.String(50), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("feedback_registry")
    op.drop_index("ix_audit_created", table_name="audit_logs")
    op.drop_index("ix_audit_tenant_event", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_events_created", table_name="event_store")
    op.drop_index("ix_events_aggregate", table_name="event_store")
    op.drop_index("ix_events_tenant_type", table_name="event_store")
    op.drop_table("event_store")
    op.drop_index("ix_chunks_tenant_doc", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.drop_table("overrides")
    op.drop_index("ix_decisions_created", table_name="decisions")
    op.drop_index("ix_decisions_tenant_case", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("ix_cases_tenant_created", table_name="cases")
    op.drop_index("ix_cases_tenant_status", table_name="cases")
    op.drop_table("cases")
    op.drop_constraint("fk_rules_parent_rule_id", "rules", type_="foreignkey")
    op.drop_index("ix_rules_tenant_category", table_name="rules")
    op.drop_index("ix_rules_tenant_active", table_name="rules")
    op.drop_table("rules")
    op.drop_table("tenant_quotas")
    op.drop_index("ix_api_keys_tenant", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("users")
    op.drop_table("tenant_configurations")
    op.drop_table("tenants")
