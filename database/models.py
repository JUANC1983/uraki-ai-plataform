# database/models.py
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# TENANTS
# ---------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    plan: Mapped[str] = mapped_column(String(50), default="starter")  # starter|pro|enterprise
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    configurations: Mapped[list["TenantConfiguration"]] = relationship(back_populates="tenant")
    users: Mapped[list["User"]] = relationship(back_populates="tenant")
    rules: Mapped[list["Rule"]] = relationship(back_populates="tenant")
    cases: Mapped[list["Case"]] = relationship(back_populates="tenant")
    documents: Mapped[list["Document"]] = relationship(back_populates="tenant")
    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="tenant")


# ---------------------------------------------------------------------------
# TENANT CONFIGURATION
# ---------------------------------------------------------------------------
class TenantConfiguration(Base):
    __tablename__ = "tenant_configurations"
    __table_args__ = (UniqueConstraint("tenant_id", "config_key"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    config_key: Mapped[str] = mapped_column(String(200), nullable=False)
    config_value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="configurations")


# ---------------------------------------------------------------------------
# USERS & RBAC
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # admin|operador|legal|ejecutivo
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
    overrides: Mapped[list["Override"]] = relationship(
        back_populates="user", foreign_keys="Override.user_id"
    )


# ---------------------------------------------------------------------------
# API KEYS (alternative auth — per tenant)
# ---------------------------------------------------------------------------
class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)   # first 8 chars (display)
    key_hash: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)  # SHA-256 digest
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="api_keys")

    __table_args__ = (
        Index("ix_api_keys_tenant", "tenant_id"),
        Index("ix_api_keys_user", "user_id"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
            name="fk_api_keys_tenant_user", ondelete="CASCADE",
        ),
    )


# ---------------------------------------------------------------------------
# TENANT QUOTA (rate limiting without Redis — DB-backed sliding window)
# ---------------------------------------------------------------------------
class TenantQuota(Base):
    __tablename__ = "tenant_quotas"
    __table_args__ = (UniqueConstraint("tenant_id", "window_key"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    window_key: Mapped[str] = mapped_column(String(50), nullable=False)  # "2024-01" or "2024-01-15T14:30"
    window_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "monthly" | "minute"
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# RULES (Decision Engine) — with versioning
# ---------------------------------------------------------------------------
class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        Index("ix_rules_tenant_active", "tenant_id", "is_active"),
        Index("ix_rules_tenant_category", "tenant_id", "category"),
        UniqueConstraint("tenant_id", "id", name="uq_rules_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_rule_id"], ["rules.tenant_id", "rules.id"],
            name="fk_rules_tenant_parent",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # Rule identity (parent_rule_id links versions to the same logical rule)
    parent_rule_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("rules.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)

    # Rule logic
    conditions: Mapped[Any] = mapped_column(JSONB, nullable=False)
    actions: Mapped[Any] = mapped_column(JSONB, nullable=False)
    constraints: Mapped[Optional[Any]] = mapped_column(JSONB)
    explanation_template: Mapped[Optional[str]] = mapped_column(Text)

    # Versioning
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="rules")


# ---------------------------------------------------------------------------
# CASES
# ---------------------------------------------------------------------------
class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        Index("ix_cases_tenant_status", "tenant_id", "status"),
        Index("ix_cases_tenant_created", "tenant_id", "created_at"),
        UniqueConstraint("tenant_id", "id", name="uq_cases_tenant_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    external_ref: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(50), default="NEW")
    priority: Mapped[Optional[str]] = mapped_column(String(20))  # LOW|MEDIUM|HIGH|CRITICAL
    case_type: Mapped[str] = mapped_column(String(100), nullable=False)

    client_name: Mapped[str] = mapped_column(String(300), nullable=False)
    client_id_number: Mapped[Optional[str]] = mapped_column(String(100))
    property_address: Mapped[Optional[str]] = mapped_column(String(500))
    contract_id: Mapped[Optional[str]] = mapped_column(String(200))

    overdue_days: Mapped[int] = mapped_column(Integer, default=0)
    overdue_amount: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_rent: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="COP")

    raw_data: Mapped[Optional[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="cases")
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="case", foreign_keys="Decision.case_id"
    )
    overrides: Mapped[list["Override"]] = relationship(
        back_populates="case", foreign_keys="Override.case_id"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="case", foreign_keys="Document.case_id"
    )


# ---------------------------------------------------------------------------
# DECISIONS
# ---------------------------------------------------------------------------
class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        Index("ix_decisions_tenant_case", "tenant_id", "case_id"),
        Index("ix_decisions_created", "tenant_id", "created_at"),
        UniqueConstraint("tenant_id", "id", name="uq_decisions_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"],
            name="fk_decisions_tenant_case", ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    case_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    classification: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[Optional[str]] = mapped_column(String(20))  # LOW|MEDIUM|HIGH|CRITICAL
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    firmness: Mapped[str] = mapped_column(String(50), nullable=False)
    escalation_required: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_target: Mapped[Optional[str]] = mapped_column(String(100))
    legal_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    validations_missing: Mapped[Optional[Any]] = mapped_column(JSONB)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # Versioned rule traceability
    rule_id_applied: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False))
    rule_version_used: Mapped[Optional[int]] = mapped_column(Integer)  # rule.version at time of decision

    # Document references
    document_references: Mapped[Optional[Any]] = mapped_column(JSONB)  # list[DocumentReference]

    # Full input context at evaluation time — required for accurate historical replay.
    # Stored as the exact case_data dict that was passed to the rule engine.
    context_snapshot: Mapped[Optional[Any]] = mapped_column(JSONB)

    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    suggested_message: Mapped[Optional[str]] = mapped_column(Text)
    full_output: Mapped[Any] = mapped_column(JSONB, nullable=False)
    is_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped["Case"] = relationship(back_populates="decisions", foreign_keys=[case_id])
    overrides: Mapped[list["Override"]] = relationship(
        back_populates="decision", foreign_keys="Override.decision_id"
    )


# ---------------------------------------------------------------------------
# OVERRIDES
# ---------------------------------------------------------------------------
class Override(Base):
    __tablename__ = "overrides"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "decision_id", name="uq_overrides_tenant_decision"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"],
            name="fk_overrides_tenant_case", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "decision_id"], ["decisions.tenant_id", "decisions.id"],
            name="fk_overrides_tenant_decision", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
            name="fk_overrides_tenant_user",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    decision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    original_action: Mapped[str] = mapped_column(String(200), nullable=False)
    overridden_action: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped["Case"] = relationship(back_populates="overrides", foreign_keys=[case_id])
    decision: Mapped["Decision"] = relationship(
        back_populates="overrides", foreign_keys=[decision_id]
    )
    user: Mapped["User"] = relationship(back_populates="overrides", foreign_keys=[user_id])


# ---------------------------------------------------------------------------
# DOCUMENTS
# ---------------------------------------------------------------------------
class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_documents_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"],
            name="fk_documents_tenant_case",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cases.id", ondelete="SET NULL")
    )
    contract_id: Mapped[Optional[str]] = mapped_column(String(200))
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    parsed_text: Mapped[Optional[str]] = mapped_column(Text)
    doc_metadata: Mapped[Optional[Any]] = mapped_column(JSONB)
    is_embedded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="documents")
    case: Mapped[Optional["Case"]] = relationship(
        back_populates="documents", foreign_keys=[case_id]
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", foreign_keys="DocumentChunk.document_id"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_chunks_tenant_doc", "tenant_id", "document_id"),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"], ["documents.tenant_id", "documents.id"],
            name="fk_document_chunks_tenant_document", ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    clause_label: Mapped[Optional[str]] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[Any]] = mapped_column(JSONB)
    doc_metadata: Mapped[Optional[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(
        back_populates="chunks", foreign_keys=[document_id]
    )


# ---------------------------------------------------------------------------
# EVENT STORE (event-driven architecture)
# ---------------------------------------------------------------------------
class EventStore(Base):
    __tablename__ = "event_store"
    __table_args__ = (
        Index("ix_events_tenant_type", "tenant_id", "event_type"),
        Index("ix_events_aggregate", "tenant_id", "aggregate_id"),
        Index("ix_events_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)  # "case"|"decision"
    aggregate_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# AUDIT LOGS
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_tenant_event", "tenant_id", "event_type"),
        Index("ix_audit_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(100))
    entity_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False))
    user_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False))
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# FEEDBACK REGISTRY
# ---------------------------------------------------------------------------
class FeedbackRegistry(Base):
    __tablename__ = "feedback_registry"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"],
            name="fk_feedback_tenant_case", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "decision_id"], ["decisions.tenant_id", "decisions.id"],
            name="fk_feedback_tenant_decision", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "rule_id"], ["rules.tenant_id", "rules.id"],
            name="fk_feedback_tenant_rule",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
            name="fk_feedback_tenant_user",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    decision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    rule_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("rules.id", ondelete="SET NULL")
    )
    feedback_type: Mapped[str] = mapped_column(String(50), nullable=False)  # positive|negative|neutral
    comment: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
