"""
Background Scheduler — runs the sync job on a configurable interval.

Uses APScheduler with asyncio. The scheduler is started/stopped
as part of the FastAPI app lifespan.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.services.sync_service import sync_service

logger = get_logger(__name__)

scheduler = AsyncIOScheduler()


async def run_scheduled_sync() -> None:
    logger.info("Scheduled sync triggered.")
    try:
        result = await sync_service.run_full_sync()
        logger.info(f"Scheduled sync result: {result}")
    except Exception as e:
        logger.exception(f"Scheduled sync failed: {e}")


def start_scheduler() -> None:
    scheduler.add_job(
        run_scheduled_sync,
        trigger=IntervalTrigger(minutes=settings.SYNC_INTERVAL_MINUTES),
        id="full_sync",
        name="Full data sync from external accounting API",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started. Sync interval: every {settings.SYNC_INTERVAL_MINUTES} minutes.")


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped.")
