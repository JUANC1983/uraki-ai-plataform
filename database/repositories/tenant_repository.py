# database/repositories/tenant_repository.py
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Tenant, TenantConfiguration


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, tenant_id: str) -> Optional[Tenant]:
        result = await self.session.execute(
            select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Optional[Tenant]:
        result = await self.session.execute(
            select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Tenant]:
        result = await self.session.execute(
            select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.name)
        )
        return list(result.scalars().all())

    async def create(
        self, *, name: str, slug: str, plan: str = "starter"
    ) -> Tenant:
        tenant = Tenant(name=name, slug=slug, plan=plan)
        self.session.add(tenant)
        await self.session.flush()
        return tenant

    async def get_config(self, tenant_id: str) -> dict[str, Any]:
        """Load all tenant configurations into a flat dict."""
        result = await self.session.execute(
            select(TenantConfiguration).where(
                TenantConfiguration.tenant_id == tenant_id
            )
        )
        rows = result.scalars().all()
        return {row.config_key: row.config_value for row in rows}

    async def set_config(
        self, *, tenant_id: str, config_key: str, config_value: Any, description: str = ""
    ) -> TenantConfiguration:
        # Upsert
        result = await self.session.execute(
            select(TenantConfiguration).where(
                TenantConfiguration.tenant_id == tenant_id,
                TenantConfiguration.config_key == config_key,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.config_value = config_value
            existing.description = description
            return existing
        config = TenantConfiguration(
            tenant_id=tenant_id,
            config_key=config_key,
            config_value=config_value,
            description=description,
        )
        self.session.add(config)
        await self.session.flush()
        return config
