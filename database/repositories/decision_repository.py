# database/repositories/decision_repository.py
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.decision_contract import DecisionOutput
from database.models import Decision
from database.repositories.base import BaseRepository, TenantIsolationError


class DecisionRepository(BaseRepository[Decision]):
    model = Decision

    async def save(
        self,
        *,
        decision: DecisionOutput,
        context_snapshot: Optional[dict] = None,
    ) -> Decision:
        """
        Persist a DecisionOutput.

        context_snapshot: the full case_data dict that was passed to the rule
        engine at evaluation time. Required for accurate historical replay via
        GET /cases/{id}/replay. If None, replay will refuse to run for this
        decision (it cannot reconstruct the original context).
        """
        if decision.tenant_id != self.tenant_id:
            raise TenantIsolationError(
                f"DecisionOutput.tenant_id '{decision.tenant_id}' "
                f"does not match repository tenant_id '{self.tenant_id}'"
            )
        db_decision = Decision(
            case_id=decision.case_id,
            tenant_id=self.tenant_id,
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
            document_references=[r.model_dump() for r in decision.document_references],
            context_snapshot=context_snapshot,
            confidence=decision.confidence,
            suggested_message=decision.suggested_message,
            full_output=decision.to_audit_dict(),
        )
        self.session.add(db_decision)
        await self.session.flush()
        return db_decision

    async def get(self, decision_id: str) -> Optional[Decision]:
        return await self._get_by_id(decision_id)

    async def get_latest_for_case(self, case_id: str) -> Optional[Decision]:
        rows = await self.session.execute(
            self._q()
            .where(Decision.case_id == case_id)
            .order_by(Decision.created_at.desc())
            .limit(1)
        )
        return rows.scalar_one_or_none()

    async def list_for_case(self, case_id: str) -> list[Decision]:
        rows = await self.session.execute(
            self._q()
            .where(Decision.case_id == case_id)
            .order_by(Decision.created_at.desc())
        )
        return list(rows.scalars().all())

    async def mark_overridden(self, decision_id: str) -> None:
        decision = await self._get_by_id(decision_id)
        if decision:
            decision.is_overridden = True  # type: ignore[attr-defined]

    async def get_stats(self) -> dict[str, Any]:
        from sqlalchemy import func

        total = (await self.session.execute(self._count_q())).scalar() or 0
        escalated = (
            await self.session.execute(
                self._count_q().where(Decision.escalation_required.is_(True))
            )
        ).scalar() or 0
        legal = (
            await self.session.execute(
                self._count_q().where(Decision.legal_flag.is_(True))
            )
        ).scalar() or 0
        overridden = (
            await self.session.execute(
                self._count_q().where(Decision.is_overridden.is_(True))
            )
        ).scalar() or 0

        # Priority breakdown
        from sqlalchemy import case as sql_case, select
        priority_q = await self.session.execute(
            select(Decision.priority, func.count().label("n"))
            .where(Decision.tenant_id == self.tenant_id)
            .group_by(Decision.priority)
        )
        priority_dist = {row.priority: row.n for row in priority_q}

        return {
            "total_decisions": total,
            "escalated": escalated,
            "legal_flags": legal,
            "overridden": overridden,
            "override_rate": round(overridden / max(total, 1) * 100, 2),
            "priority_distribution": priority_dist,
        }
