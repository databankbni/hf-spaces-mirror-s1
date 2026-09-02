"""
Heaven on Earth CMS Backend - 15-Day Content Refresh Scheduler

Uses APScheduler's AsyncIOScheduler to periodically refresh dynamic content
(events, ministries) from PostgreSQL into the pgvector knowledge base.

Usage
-----
Call ``start_scheduler(knowledge_base_service)`` during FastAPI startup and
``stop_scheduler()`` during shutdown.  The ``refresh_job`` coroutine is run
on the configured interval (default: every 15 days).
"""

from __future__ import annotations

from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import async_session_maker

# Logger for this module — matches existing structlog usage in the project
logger = structlog.get_logger(__name__)

# Module-level APScheduler singleton
scheduler = AsyncIOScheduler()

# Injected by start_scheduler(); None until the scheduler is started.
# Declared here so refresh_job() can reference it without a circular import.
_knowledge_base_service: Optional[object] = None  # type: KnowledgeBaseService


# ---------------------------------------------------------------------------
# Scheduled job
# ---------------------------------------------------------------------------


async def refresh_job() -> None:
    """
    Scheduled coroutine that refreshes dynamic content in the knowledge base.

    Opens a short-lived database session, delegates to
    ``KnowledgeBaseService.refresh_dynamic_content(db)``, and logs the
    result summary with structlog.

    The ``_knowledge_base_service`` module-level variable must be set by
    ``start_scheduler`` before this job runs.
    """
    if _knowledge_base_service is None:
        logger.error(
            "refresh_job_skipped",
            reason="KnowledgeBaseService not initialised — start_scheduler was not called",
        )
        return

    logger.info("knowledge_refresh_started")

    try:
        async with async_session_maker() as db:
            summary = await _knowledge_base_service.refresh_dynamic_content(db)
            await db.commit()

        logger.info(
            "knowledge_refresh_succeeded",
            events_fetched=summary.get("events_fetched"),
            ministries_fetched=summary.get("ministries_fetched"),
            chunks_upserted=summary.get("chunks_upserted"),
            chunks_deleted=summary.get("chunks_deleted"),
            duration_ms=summary.get("duration_ms"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "knowledge_refresh_failed",
            error=str(exc),
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------


def start_scheduler(knowledge_base_service: object) -> None:  # type: KnowledgeBaseService
    """
    Initialise and start the APScheduler instance.

    Parameters
    ----------
    knowledge_base_service:
        A ``KnowledgeBaseService`` instance whose
        ``refresh_dynamic_content(db)`` method will be called on each
        scheduled run.  Stored in the module-level ``_knowledge_base_service``
        variable so that ``refresh_job`` can access it without being passed
        as an argument by APScheduler.
    """
    global _knowledge_base_service  # noqa: PLW0603

    _knowledge_base_service = knowledge_base_service

    scheduler.add_job(
        refresh_job,
        trigger=IntervalTrigger(days=settings.knowledge_base_refresh_days),
        id="knowledge_base_refresh",
        replace_existing=True,
        max_instances=1,  # Prevent overlapping runs
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        refresh_interval_days=settings.knowledge_base_refresh_days,
    )


def stop_scheduler() -> None:
    """
    Shut down the APScheduler instance gracefully.

    Passes ``wait=True`` so that any currently executing job is allowed to
    finish before the scheduler exits.
    """
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("scheduler_stopped")
    else:
        logger.warning("scheduler_stop_called_but_not_running")
