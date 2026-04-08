# database/repositories/rule_repository.py
"""
Rule Repository — versioning, rollback, historical replay.

Versioning model:
  - Each logical rule has a stable parent_rule_id.
  - Updating a rule creates a NEW row (new version) and closes the old one
    (sets effective_to = now).
  - Only ONE version per parent has effective_to = NULL (the current one).
  - Historical replay: query rules WHERE effective_from <= T AND
    (effective_to IS NULL OR effective_to > T).
  - Rollback: reactivate a previous version (set its effective_to = NULL,
    close the current one).
"""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.rule_engine import RuleRecord
from database.models import Rule
from database.repositories.base import BaseRepository, TenantIsolationError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RuleRepository(BaseRepository[Rule]):
    model = Rule

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_active_rules(self) -> list[RuleRecord]:
        """Current active rules for this tenant (effective_to IS NULL)."""
        rows = await self.session.execute(
            self._q()
            .where(Rule.is_active.is_(True), Rule.effective_to.is_(None))
            .order_by(Rule.priority.asc())
        )
        return [self._to_record(r) for r in rows.scalars().all()]

    async def get_rules_at(self, point_in_time: datetime) -> list[RuleRecord]:
        """
        Historical replay — return the rules that were active at the given timestamp.
        Used to reproduce past decisions exactly.
        """
        rows = await self.session.execute(
            self._q()
            .where(
                Rule.is_active.is_(True),
                Rule.effective_from <= point_in_time,
                (Rule.effective_to.is_(None)) | (Rule.effective_to > point_in_time),
            )
            .order_by(Rule.priority.asc())
        )
        return [self._to_record(r) for r in rows.scalars().all()]

    async def get(self, rule_id: str) -> Optional[Rule]:
        return await self._get_by_id(rule_id)

    async def list_rules(self, *, include_history: bool = False) -> list[Rule]:
        """
        List rules.
        include_history=False → only current versions (effective_to IS NULL)
        include_history=True  → all versions for audit
        """
        q = self._q()
        if not include_history:
            q = q.where(Rule.effective_to.is_(None))
        rows = await self.session.execute(q.order_by(Rule.priority.asc(), Rule.version.asc()))
        return list(rows.scalars().all())

    async def get_version_history(self, parent_rule_id: str) -> list[Rule]:
        """All versions of a logical rule, ordered oldest→newest."""
        rows = await self.session.execute(
            self._q()
            .where(
                (Rule.id == parent_rule_id)
                | (Rule.parent_rule_id == parent_rule_id)
            )
            .order_by(Rule.version.asc())
        )
        return list(rows.scalars().all())

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(self, data: dict[str, Any]) -> Rule:
        """
        Create the first version of a rule.
        Sets effective_from = now, effective_to = NULL (open-ended).
        """
        rule = Rule(
            tenant_id=self.tenant_id,
            effective_from=_utcnow(),
            effective_to=None,
            **{k: v for k, v in data.items() if k not in ("tenant_id", "effective_from", "effective_to")},
        )
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def update(self, rule_id: str, data: dict[str, Any]) -> Rule:
        """
        Versioned update — creates a new row, closes the old one.

        Old version: effective_to = now
        New version: version += 1, effective_from = now, parent_rule_id = original id
        """
        current = await self._get_by_id(rule_id)
        if not current:
            raise ValueError(f"Rule '{rule_id}' not found for tenant '{self.tenant_id}'")

        now = _utcnow()

        # Close current version
        current.effective_to = now  # type: ignore[attr-defined]
        current.is_active = False   # type: ignore[attr-defined]

        # Determine parent lineage
        parent_id = current.parent_rule_id or current.id

        # Create new version
        new_rule = Rule(
            tenant_id=self.tenant_id,
            parent_rule_id=parent_id,
            name=data.get("name", current.name),
            category=data.get("category", current.category),
            priority=data.get("priority", current.priority),
            conditions=data.get("conditions", current.conditions),
            actions=data.get("actions", current.actions),
            constraints=data.get("constraints", current.constraints),
            explanation_template=data.get("explanation_template", current.explanation_template),
            version=current.version + 1,
            effective_from=now,
            effective_to=None,
            is_active=True,
        )
        self.session.add(new_rule)
        await self.session.flush()
        return new_rule

    async def rollback(self, rule_id: str, target_version: int) -> Rule:
        """
        Rollback a rule to a specific historical version.

        Steps:
          1. Find the version row with the target version number
          2. Close the current active version
          3. Create a new row based on the old version (version = current + 1)
        """
        # Find the target version
        parent_id = rule_id
        history = await self.get_version_history(rule_id)
        if not history:
            raise ValueError(f"No version history found for rule '{rule_id}'")

        target = next((r for r in history if r.version == target_version), None)
        if not target:
            available = [r.version for r in history]
            raise ValueError(
                f"Version {target_version} not found for rule '{rule_id}'. "
                f"Available: {available}"
            )

        # Close current active version
        current = next((r for r in history if r.effective_to is None), None)
        if current:
            now = _utcnow()
            current.effective_to = now  # type: ignore[attr-defined]
            current.is_active = False   # type: ignore[attr-defined]
            next_version = current.version + 1
        else:
            next_version = target.version + 1
            now = _utcnow()

        # Create rollback version (based on target, new timestamp)
        rollback_rule = Rule(
            tenant_id=self.tenant_id,
            parent_rule_id=parent_id,
            name=target.name,
            category=target.category,
            priority=target.priority,
            conditions=target.conditions,
            actions=target.actions,
            constraints=target.constraints,
            explanation_template=target.explanation_template,
            version=next_version,
            effective_from=now,
            effective_to=None,
            is_active=True,
        )
        self.session.add(rollback_rule)
        await self.session.flush()
        return rollback_rule

    async def deactivate(self, rule_id: str) -> bool:
        """Soft-delete: set is_active=False and close effective_to."""
        rule = await self._get_by_id(rule_id)
        if not rule:
            return False
        rule.is_active = False          # type: ignore[attr-defined]
        rule.effective_to = _utcnow()   # type: ignore[attr-defined]
        return True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _to_record(self, rule: Rule) -> RuleRecord:
        return RuleRecord(
            id=str(rule.id),
            tenant_id=str(rule.tenant_id),
            name=rule.name,
            category=rule.category,
            priority=rule.priority,
            conditions=rule.conditions,
            actions=rule.actions,
            constraints=rule.constraints,
            explanation_template=rule.explanation_template,
            is_active=rule.is_active,
            version=rule.version,
            effective_from=rule.effective_from,
            effective_to=rule.effective_to,
            parent_rule_id=str(rule.parent_rule_id) if rule.parent_rule_id else None,
        )
