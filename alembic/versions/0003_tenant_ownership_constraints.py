"""Enforce tenant ownership on parent-child database relationships.

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("users", "rules", "cases", "decisions", "documents"):
        op.create_unique_constraint(f"uq_{table}_tenant_id", table, ["tenant_id", "id"])
    op.create_unique_constraint(
        "uq_overrides_tenant_decision", "overrides", ["tenant_id", "decision_id"]
    )

    old_foreign_keys = (
        ("fk_api_keys_user_id", "api_keys"),
        ("decisions_case_id_fkey", "decisions"),
        ("overrides_case_id_fkey", "overrides"),
        ("overrides_decision_id_fkey", "overrides"),
        ("overrides_user_id_fkey", "overrides"),
        ("document_chunks_document_id_fkey", "document_chunks"),
        ("feedback_registry_case_id_fkey", "feedback_registry"),
        ("feedback_registry_decision_id_fkey", "feedback_registry"),
    )
    for constraint, table in old_foreign_keys:
        op.drop_constraint(constraint, table, type_="foreignkey")

    relationships = (
        ("fk_api_keys_tenant_user", "api_keys", "users", "user_id", "CASCADE"),
        ("fk_rules_tenant_parent", "rules", "rules", "parent_rule_id", None),
        ("fk_decisions_tenant_case", "decisions", "cases", "case_id", "CASCADE"),
        ("fk_overrides_tenant_case", "overrides", "cases", "case_id", "CASCADE"),
        ("fk_overrides_tenant_decision", "overrides", "decisions", "decision_id", "CASCADE"),
        ("fk_overrides_tenant_user", "overrides", "users", "user_id", None),
        ("fk_documents_tenant_case", "documents", "cases", "case_id", None),
        ("fk_document_chunks_tenant_document", "document_chunks", "documents", "document_id", "CASCADE"),
        ("fk_feedback_tenant_case", "feedback_registry", "cases", "case_id", "CASCADE"),
        ("fk_feedback_tenant_decision", "feedback_registry", "decisions", "decision_id", "CASCADE"),
        ("fk_feedback_tenant_rule", "feedback_registry", "rules", "rule_id", None),
        ("fk_feedback_tenant_user", "feedback_registry", "users", "user_id", None),
    )
    for name, source, target, parent_id, ondelete in relationships:
        op.create_foreign_key(
            name, source, target,
            ["tenant_id", parent_id], ["tenant_id", "id"],
            ondelete=ondelete,
        )
    op.create_foreign_key(
        "fk_feedback_rule_id", "feedback_registry", "rules",
        ["rule_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_feedback_user_id", "feedback_registry", "users",
        ["user_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_feedback_user_id", "feedback_registry", type_="foreignkey")
    op.drop_constraint("fk_feedback_rule_id", "feedback_registry", type_="foreignkey")
    relationships = (
        ("fk_feedback_tenant_user", "feedback_registry"),
        ("fk_feedback_tenant_rule", "feedback_registry"),
        ("fk_feedback_tenant_decision", "feedback_registry"),
        ("fk_feedback_tenant_case", "feedback_registry"),
        ("fk_document_chunks_tenant_document", "document_chunks"),
        ("fk_documents_tenant_case", "documents"),
        ("fk_overrides_tenant_user", "overrides"),
        ("fk_overrides_tenant_decision", "overrides"),
        ("fk_overrides_tenant_case", "overrides"),
        ("fk_decisions_tenant_case", "decisions"),
        ("fk_rules_tenant_parent", "rules"),
        ("fk_api_keys_tenant_user", "api_keys"),
    )
    for constraint, table in relationships:
        op.drop_constraint(constraint, table, type_="foreignkey")

    op.drop_constraint(
        "uq_overrides_tenant_decision", "overrides", type_="unique"
    )

    original_relationships = (
        ("fk_api_keys_user_id", "api_keys", "users", "user_id", "CASCADE"),
        ("decisions_case_id_fkey", "decisions", "cases", "case_id", "CASCADE"),
        ("overrides_case_id_fkey", "overrides", "cases", "case_id", "CASCADE"),
        ("overrides_decision_id_fkey", "overrides", "decisions", "decision_id", "CASCADE"),
        ("overrides_user_id_fkey", "overrides", "users", "user_id", None),
        ("document_chunks_document_id_fkey", "document_chunks", "documents", "document_id", "CASCADE"),
        ("feedback_registry_case_id_fkey", "feedback_registry", "cases", "case_id", "CASCADE"),
        ("feedback_registry_decision_id_fkey", "feedback_registry", "decisions", "decision_id", "CASCADE"),
    )
    for name, source, target, parent_id, ondelete in original_relationships:
        op.create_foreign_key(name, source, target, [parent_id], ["id"], ondelete=ondelete)

    for table in reversed(("users", "rules", "cases", "decisions", "documents")):
        op.drop_constraint(f"uq_{table}_tenant_id", table, type_="unique")
