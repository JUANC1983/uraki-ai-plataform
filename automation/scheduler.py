# automation/scheduler.py
"""
Scheduler — periodic background jobs.

Currently uses asyncio periodic loops (no external dependency).
Celery Beat migration: replace run_periodically with @celery_app.on_after_configure.

Jobs:
  - sweep_overdue_cases    : daily, auto-escalate cases past threshold
  - cleanup_expired_quotas : hourly, purge old rate-limit window rows
  - metrics_snapshot       : daily, snapshot product metrics to audit log
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Coroutine, Any

logger = logging.getLogger(__name__)


async def run_periodically(
    fn: Callable[[], Coroutine[Any, Any, None]],
    interval_seconds: int,
    name: str,
) -> None:
    """Run an async function every `interval_seconds`. Logs failures, never crashes."""
    logger.info("Scheduler: starting job '%s' every %ds", name, interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            logger.debug("Scheduler: running '%s'", name)
            await fn()
        except Exception as exc:
            logger.error("Scheduler: job '%s' failed (%s)", name, type(exc).__name__)


# ---------------------------------------------------------------------------
# Job: sweep overdue cases
# ---------------------------------------------------------------------------

async def sweep_overdue_cases() -> None:
    """
    Find cases that exceed the tenant's auto_escalate_days threshold
    and haven't been escalated yet. Trigger auto-escalation.
    """
    from database.base import AsyncSessionLocal
    from sqlalchemy import select
    from database.models import Case, Tenant, TenantConfiguration

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Case).where(
                Case.status.notin_(["CLOSED", "ESCALATED"]),
                Case.overdue_days > 0,
            )
        )
        cases = result.scalars().all()

        escalated = 0
        for case in cases:
            # Load tenant's escalation threshold
            cfg_result = await db.execute(
                select(TenantConfiguration).where(
                    TenantConfiguration.tenant_id == case.tenant_id,
                    TenantConfiguration.config_key == "escalation_policy",
                )
            )
            cfg = cfg_result.scalar_one_or_none()
            threshold_days = 90  # default
            if cfg and isinstance(cfg.config_value, dict):
                threshold_days = cfg.config_value.get("auto_escalate_days", 90)

            if case.overdue_days >= threshold_days:
                from automation.task_queue import get_task_queue
                queue = get_task_queue()
                await queue.run(
                    "auto_escalate",
                    tenant_id=str(case.tenant_id),
                    case_id=str(case.id),
                    escalation_target="management",
                    reason=f"Auto-escalated: {case.overdue_days} overdue days ≥ threshold {threshold_days}",
                    risk_score=100.0,
                )
                escalated += 1

        if escalated:
            logger.info("sweep_overdue_cases: escalated %d cases", escalated)


# ---------------------------------------------------------------------------
# Job: cleanup expired quota rows
# ---------------------------------------------------------------------------

async def cleanup_expired_quotas() -> None:
    """Delete quota window rows older than 2 hours (minute windows) or 2 months."""
    from database.base import AsyncSessionLocal
    from sqlalchemy import delete
    from database.models import TenantQuota

    now = datetime.now(timezone.utc)
    cutoff_minute = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    cutoff_monthly = (now - timedelta(days=60)).strftime("%Y-%m")

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(TenantQuota).where(
                TenantQuota.window_type == "minute",
                TenantQuota.window_key < cutoff_minute,
            )
        )
        await db.execute(
            delete(TenantQuota).where(
                TenantQuota.window_type == "monthly",
                TenantQuota.window_key < cutoff_monthly,
            )
        )
        await db.commit()
        logger.debug("cleanup_expired_quotas: done")


# ---------------------------------------------------------------------------
# Job: metrics snapshot
# ---------------------------------------------------------------------------

async def metrics_snapshot() -> None:
    """Write daily metrics to audit log for product analytics."""
    from database.base import AsyncSessionLocal
    from database.models import Tenant, AuditLog
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        tenants_result = await db.execute(
            select(Tenant).where(Tenant.is_active.is_(True))
        )
        tenants = tenants_result.scalars().all()

        for tenant in tenants:
            log = AuditLog(
                tenant_id=str(tenant.id),
                event_type="METRICS_SNAPSHOT",
                payload={
                    "snapshot_date": datetime.now(timezone.utc).isoformat(),
                    "tenant_name": tenant.name,
                },
            )
            db.add(log)

        await db.commit()
        logger.info("metrics_snapshot: snapshotted %d tenants", len(tenants))


# ---------------------------------------------------------------------------
# Startup: launch all background jobs
# ---------------------------------------------------------------------------

def start_scheduler() -> list[asyncio.Task]:
    """
    Launch all periodic jobs. Call from FastAPI lifespan startup.
    Returns tasks so they can be cancelled on shutdown.
    """
    jobs = [
        asyncio.create_task(
            run_periodically(sweep_overdue_cases, 86_400, "sweep_overdue_cases")
        ),
        asyncio.create_task(
            run_periodically(cleanup_expired_quotas, 3_600, "cleanup_expired_quotas")
        ),
        asyncio.create_task(
            run_periodically(metrics_snapshot, 86_400, "metrics_snapshot")
        ),
    ]
    return jobs
