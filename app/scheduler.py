import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.services.balance_job import run_balance_job_exclusive, try_reserve_job_slot

logger = logging.getLogger(__name__)


def create_scheduler(settings: Settings) -> AsyncIOScheduler:
    tz = ZoneInfo(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    trigger = CronTrigger.from_crontab(settings.cron_expression, timezone=tz)

    async def scheduled_job() -> None:
        if not try_reserve_job_slot():
            logger.warning("Skipping scheduled balance job because another run is already in progress")
            return
        await run_balance_job_exclusive(settings, trigger="schedule")

    scheduler.add_job(
        scheduled_job,
        trigger=trigger,
        id="bank-balance-tracking",
        name="Bank balance tracking",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    logger.info(
        "Scheduled balance job with cron='%s' timezone='%s'",
        settings.cron_expression,
        settings.timezone,
    )
    return scheduler
