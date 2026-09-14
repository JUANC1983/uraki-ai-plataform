# database/repositories/case_repository.py
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Case, Override
from database.repositories.base import BaseRepository, _require_tenant


class CaseRepository(BaseRepository[Case]):
    model = Case

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(self, data: dict[str, Any]) -> Case:
        """tenant_id is taken from self — callers must NOT pass it in data."""
        case = Case(tenant_id=self.tenant_id, **data)
        self.session.add(case)
        await self.session.flush()
        return case

    async def update_status(self, *, case_id: str, status: str) -> None:
        case = await self._get_by_id(case_id)
        if case:
            case.status = status  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get(self, case_id: str) -> Optional[Case]:
        return await self._get_by_id(case_id)

    async def get_for_update(self, case_id: str) -> Optional[Case]:
        """Lock one tenant-scoped case for serialized state-changing jobs."""
        result = await self.session.execute(
            self._q().where(Case.id == case_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Case], int]:
        query = self._q()
        count_query = self._count_q()

        if status:
            query = query.where(Case.status == status)
            count_query = count_query.where(Case.status == status)

        total = (await self.session.execute(count_query)).scalar() or 0
        rows = await self.session.execute(
            query.order_by(Case.created_at.desc()).limit(limit).offset(offset)
        )
        return list(rows.scalars().all()), total

    async def get_kpis(self) -> dict[str, Any]:
        total = (await self.session.execute(self._count_q())).scalar() or 0

        open_q = self._count_q().where(Case.status.notin_(["CLOSED"]))
        open_cases = (await self.session.execute(open_q)).scalar() or 0

        sum_q = self._scope(
            select(func.sum(Case.overdue_amount)).select_from(Case)
        )
        overdue_sum = (await self.session.execute(sum_q)).scalar() or 0

        avg_q = self._scope(
            select(func.avg(Case.overdue_days)).select_from(Case)
        )
        avg_days = (await self.session.execute(avg_q)).scalar() or 0

        return {
            "total_cases": total,
            "open_cases": open_cases,
            "total_overdue_amount": float(overdue_sum),
            "avg_overdue_days": float(avg_days),
        }

    async def get_aging_buckets(self) -> dict[str, int]:
        b0 = self._count_q().where(Case.overdue_days.between(0, 30))
        b1 = self._count_q().where(Case.overdue_days.between(31, 60))
        b2 = self._count_q().where(Case.overdue_days.between(61, 90))
        b3 = self._count_q().where(Case.overdue_days > 90)
        return {
            "0_30_days": (await self.session.execute(b0)).scalar() or 0,
            "31_60_days": (await self.session.execute(b1)).scalar() or 0,
            "61_90_days": (await self.session.execute(b2)).scalar() or 0,
            "90_plus_days": (await self.session.execute(b3)).scalar() or 0,
        }


class OverrideRepository(BaseRepository[Override]):
    model = Override

    async def create(self, data: dict[str, Any]) -> Override:
        # Force tenant_id from self — ignore any tenant_id in data
        clean = {k: v for k, v in data.items() if k != "tenant_id"}
        override = Override(tenant_id=self.tenant_id, **clean)
        self.session.add(override)
        await self.session.flush()
        return override

    async def get_override_rate(self, *, rule_id: Optional[str] = None) -> float:
        from database.models import Decision

        total_decisions = (
            await self.session.execute(
                select(func.count())
                .select_from(Decision)
                .where(Decision.tenant_id == self.tenant_id)
            )
        ).scalar() or 1

        override_q = self._count_q()
        if rule_id:
            # Filter overrides that came from decisions linked to this rule
            linked_decision_ids = select(Decision.id).where(
                Decision.rule_id_applied == rule_id,
                Decision.tenant_id == self.tenant_id,
            )
            override_q = override_q.where(Override.decision_id.in_(linked_decision_ids))

        total_overrides = (await self.session.execute(override_q)).scalar() or 0
        return round(total_overrides / total_decisions * 100, 2)
