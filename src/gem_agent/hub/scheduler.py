"""Daily Pathankot Pulse scrape — runs inside the API process (Asia/Kolkata 07:00)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("pathankot_pulse.scheduler")

_scheduler: Any = None


def start_daily_scheduler() -> None:
    """Idempotent: schedule hub-scrape (tenders + private jobs + alerts) at 07:00 IST."""
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("apscheduler not installed — daily scrape disabled")
        return

    from . import run_hub_scrape

    def _job() -> None:
        logger.info("Daily hub scrape starting (tenders + private jobs + alerts)")
        try:
            result = run_hub_scrape()
            logger.info(
                "Daily hub scrape done: counts=%s alerts=%s",
                result.get("counts"),
                result.get("alerts"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Daily hub scrape failed")

    def _jobs_only() -> None:
        logger.info("Afternoon private-jobs scrape starting")
        try:
            result = run_hub_scrape(portals=["private_jobs"], with_recommendations=False)
            logger.info("Afternoon jobs scrape done: %s", result.get("counts"))
        except Exception:  # noqa: BLE001
            logger.exception("Afternoon jobs scrape failed")

    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    sched.add_job(
        _job,
        CronTrigger(hour=7, minute=0, timezone="Asia/Kolkata"),
        id="hub_daily_scrape",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _jobs_only,
        CronTrigger(hour=14, minute=0, timezone="Asia/Kolkata"),
        id="hub_jobs_afternoon",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    logger.info("Daily scrape 07:00 + private jobs 14:00 Asia/Kolkata")


def stop_daily_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_status() -> dict[str, Any]:
    if _scheduler is None:
        return {"running": False, "next_run": None}
    job = _scheduler.get_job("hub_daily_scrape")
    jobs_job = _scheduler.get_job("hub_jobs_afternoon")
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    next_jobs = (
        jobs_job.next_run_time.isoformat() if jobs_job and jobs_job.next_run_time else None
    )
    return {
        "running": True,
        "next_run": next_run,
        "next_jobs_run": next_jobs,
        "timezone": "Asia/Kolkata",
        "cron": "07:00 full · 14:00 private jobs",
    }
