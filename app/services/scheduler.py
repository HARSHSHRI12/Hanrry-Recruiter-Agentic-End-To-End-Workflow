"""
Scheduler Service
Uses APScheduler to trigger AI calls at the exact scheduled datetime.
Uses in-memory jobstore for reliability (no SQLite concurrency issues).
"""
import asyncio
from datetime import datetime
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from app.core.config import settings
from app.core.logger import get_logger
from app.core.exceptions import SchedulerError

log = get_logger(__name__)

# ── Singleton Scheduler ────────────────────────────────────────────────────────
_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        # Use in-memory jobstore instead of SQLite to avoid concurrency issues
        jobstores = {
            "default": MemoryJobStore()
        }
        executors = {"default": ThreadPoolExecutor(max_workers=5)}
        _scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            timezone=settings.SCHEDULER_TIMEZONE,
            job_defaults={
                'misfire_grace_time': 60,  # Allow 60 seconds grace before marking as missed
                'coalesce': True,           # Don't run multiple missed jobs
            }
        )
    return _scheduler


def _run_async_job(async_func: Callable, kwargs: dict):
    """
    Wrapper to run async function from ThreadPoolExecutor.
    Uses asyncio.run() for clean event loop management.
    """
    import traceback
    import sys
    
    job_id = kwargs.get('session_id', 'unknown')
    log.info(f"")
    log.info(f"{'='*80}")
    log.info(f"🚀 [EXECUTOR THREAD START] Job: {job_id}")
    log.info(f"   Function: {async_func.__name__}")
    log.info(f"   Args: {list(kwargs.keys())}")
    log.info(f"   Python: {sys.version.split()[0]}")
    log.info(f"{'='*80}")
    
    try:
        log.info(f"⏳ Calling asyncio.run()...")
        result = asyncio.run(async_func(**kwargs))
        log.info(f"✅ [EXECUTOR THREAD END] Job completed successfully")
        log.info(f"{'='*80}")
        return result
    except Exception as e:
        log.error(f"")
        log.error(f"{'='*80}")
        log.error(f"❌ [EXECUTOR THREAD ERROR] Job: {job_id}")
        log.error(f"   Function: {async_func.__name__}")
        log.error(f"   Exception type: {type(e).__name__}")
        log.error(f"   Exception message: {str(e)}")
        log.error(f"   Traceback:")
        log.error(f"{traceback.format_exc()}")
        log.error(f"{'='*80}")
        raise


def start_scheduler():
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        log.info("APScheduler started.")
        
        # Schedule daily storage cleanup (runs every day at midnight)
        from app.tasks.cleanup_task import run_storage_cleanup
        # Need to create a synchronous wrapper for the async task
        def _sync_cleanup():
            import asyncio
            asyncio.run(run_storage_cleanup(days_old=7))
            
        scheduler.add_job(
            _sync_cleanup,
            trigger="cron",
            hour=0,
            minute=0,
            id="daily_storage_cleanup",
            replace_existing=True
        )
        log.info("Scheduled daily storage cleanup (midnight).")


def shutdown_scheduler():
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("APScheduler stopped.")


def schedule_call(
    job_id_str: str,
    run_datetime: datetime,
    call_func: Callable,
    kwargs: dict,
):
    """
    Schedule a call function at a specific datetime.
    job_id_str: unique ID for this scheduled job
    run_datetime: when to trigger (MUST BE NAIVE - in SCHEDULER_TIMEZONE)
    call_func: async function to call
    kwargs: arguments to pass to call_func
    
    IMPORTANT: Pass naive datetime. The scheduler will interpret it in SCHEDULER_TIMEZONE.
    Do NOT pass timezone-aware datetimes - they will be double-converted.
    """
    scheduler = get_scheduler()
    try:
        # Ensure datetime is NAIVE (no timezone info)
        if run_datetime.tzinfo is not None:
            log.warning(f"⚠️  Received timezone-aware datetime, converting to naive for {settings.SCHEDULER_TIMEZONE}")
            # Convert to naive in the scheduler's timezone
            run_datetime = run_datetime.replace(tzinfo=None)
        
        log.info(f"📅 [SCHEDULE] Scheduling job: {job_id_str}")
        log.info(f"   Function: {call_func.__name__}")
        log.info(f"   Scheduled time (naive): {run_datetime}")
        log.info(f"   Will be interpreted as: {settings.SCHEDULER_TIMEZONE}")
        log.info(f"   Arguments: {list(kwargs.keys())}")
        
        # Wrap async function for ThreadPoolExecutor
        job = scheduler.add_job(
            _run_async_job,
            trigger="date",
            run_date=run_datetime,  # Pass NAIVE datetime
            id=job_id_str,
            replace_existing=True,
            kwargs={"async_func": call_func, "kwargs": kwargs},
        )
        log.info(f"✅ Job scheduled successfully: {job_id_str}")
        log.info(f"   Next run: {job.next_run_time}")
    except Exception as e:
        log.error(f"❌ Failed to schedule call: {e}")
        raise SchedulerError(f"Failed to schedule call: {e}")


def cancel_scheduled_call(job_id_str: str):
    """Cancel a previously scheduled call."""
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id_str)
        log.info(f"Cancelled scheduled call: {job_id_str}")
    except Exception as e:
        log.warning(f"Could not cancel job {job_id_str}: {e}")
