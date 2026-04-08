# database/repositories/base.py
"""
BaseRepository — enforces tenant isolation at the database query level.

RULES:
  1. Every repository MUST extend BaseRepository.
  2. tenant_id is required at instantiation — TenantIsolationError is raised otherwise.
  3. All query helpers (_q, _count_q, _get_by_id) automatically inject
     the tenant_id WHERE clause. No raw select() should bypass this.
  4. TenantRepository is the only exception: it operates at platform level
     and manages tenants themselves, so it does NOT extend BaseRepository.
"""
from typing import Any, ClassVar, Generic, Optional, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

ModelT = TypeVar("ModelT")


class TenantIsolationError(Exception):
    """Raised when a repository operation is attempted without a valid tenant_id."""

    def __init__(self, detail: str = "tenant_id is required and must not be empty") -> None:
        super().__init__(f"[TENANT ISOLATION] {detail}")


def _require_tenant(tenant_id: Optional[str]) -> str:
    """Validate and return tenant_id or raise TenantIsolationError."""
    if not tenant_id or not str(tenant_id).strip():
        raise TenantIsolationError()
    return str(tenant_id).strip()


class BaseRepository(Generic[ModelT]):
    """
    Abstract base for all data repositories.

    Subclass contract:
        class CaseRepository(BaseRepository[Case]):
            model = Case

    Construction:
        repo = CaseRepository(session, tenant_id="...")

    All _q() / _count_q() helpers automatically scope to self.tenant_id.
    No method in a subclass should call select(Model) directly — always
    start from _q() or _count_q() to guarantee tenant isolation.
    """

    model: ClassVar[Any]  # SQLAlchemy model — must be set by subclass

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self.session = session
        self.tenant_id = _require_tenant(tenant_id)

    # ------------------------------------------------------------------
    # Core scoped query builders — ALWAYS use these
    # ------------------------------------------------------------------

    def _q(self) -> Select:
        """
        Scoped SELECT — already filtered by tenant_id.
        Use as the starting point for every SELECT in a subclass.

        Example:
            result = await self.session.execute(
                self._q().where(Case.status == "NEW").limit(50)
            )
        """
        return select(self.model).where(
            self.model.tenant_id == self.tenant_id
        )

    def _count_q(self) -> Select:
        """Scoped COUNT — already filtered by tenant_id."""
        return (
            select(func.count())
            .select_from(self.model)
            .where(self.model.tenant_id == self.tenant_id)
        )

    def _scope(self, query: Select) -> Select:
        """
        Inject tenant_id filter into an arbitrary query.
        Use when building more complex queries that can't start from _q().

        Example:
            q = select(func.sum(Case.overdue_amount))
            q = self._scope(q)
        """
        return query.where(self.model.tenant_id == self.tenant_id)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    async def _get_by_id(self, entity_id: str) -> Optional[ModelT]:
        """Fetch a single record by primary key, scoped to tenant."""
        result = await self.session.execute(
            self._q().where(self.model.id == entity_id)
        )
        return result.scalar_one_or_none()

    async def _count(self) -> int:
        """Total count scoped to tenant."""
        result = await self.session.execute(self._count_q())
        return result.scalar() or 0

    async def _exists(self, entity_id: str) -> bool:
        result = await self.session.execute(
            self._count_q().where(self.model.id == entity_id)
        )
        return (result.scalar() or 0) > 0

    def _assert_tenant_match(self, entity_tenant_id: str) -> None:
        """
        Verify that a loaded entity belongs to the current tenant.
        Call after loading from a join or raw query to double-check isolation.
        """
        if str(entity_tenant_id) != self.tenant_id:
            raise TenantIsolationError(
                f"Entity tenant_id '{entity_tenant_id}' does not match "
                f"repository tenant_id '{self.tenant_id}'"
            )
