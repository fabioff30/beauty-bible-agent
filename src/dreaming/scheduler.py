"""
APScheduler wiring for the dream job.

Runs inside the bot's asyncio loop. Cron is configurable via DREAM_CRON
(default 03:00 every day, in the host's local timezone).
"""

import logging
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.dreaming.job import run_consolidation

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def _parse_cron(expr: str) -> CronTrigger:
    """Parse a 5-field cron expression (minute hour dom month dow)."""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"DREAM_CRON must have 5 fields, got: {expr!r}")
    minute, hour, day, month, dow = parts
    return CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow)


def start_scheduler() -> AsyncIOScheduler:
    """
    Start the APScheduler with the dream job registered.
    Idempotent — calling twice returns the existing instance.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    cron_expr = os.getenv('DREAM_CRON', '0 3 * * *')
    lookback = int(os.getenv('DREAM_LOOKBACK_HOURS', '24'))

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_consolidation,
        trigger=_parse_cron(cron_expr),
        kwargs={'lookback_hours': lookback},
        id='dream_consolidation',
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info(f"Dream scheduler started — cron='{cron_expr}', lookback={lookback}h")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Dream scheduler stopped")
        _scheduler = None
