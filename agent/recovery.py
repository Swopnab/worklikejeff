"""
agent/recovery.py
On-startup crash recovery.
Scans for interrupted/unfinished applications and determines safe recovery actions.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from database.connection import db_session
from database.models import Application, ApplicationStatus, AgentState, AgentStateEnum, ActivityLog

logger = logging.getLogger(__name__)


async def recover_on_startup() -> dict:
    """
    Called at agent startup. Scans for interrupted work.
    Returns a recovery report.
    
    Rules:
    - status=applying → mark as INTERRUPTED (unknown if submitted)
    - status=interrupted → leave for user review
    - status=paused → eligible to resume
    - status=needs_attention → notify user
    - status=needs_review → never auto-retry submission
    """
    report = {
        "interrupted": [],
        "needs_review": [],
        "paused": [],
        "needs_attention": [],
        "action_taken": [],
    }

    async with db_session() as session:
        # Fix any stuck APPLYING → INTERRUPTED
        result = await session.execute(
            select(Application).where(Application.status == ApplicationStatus.APPLYING)
        )
        stuck_applying = result.scalars().all()
        for app in stuck_applying:
            old_status = app.status
            app.status = ApplicationStatus.INTERRUPTED
            # Log the recovery action
            log = ActivityLog(
                application_id=app.id,
                event_type="RECOVERY",
                description=f"Recovered from crash: status {old_status.value} → INTERRUPTED",
                details="Application was mid-flight when agent stopped. Marked INTERRUPTED. Manual review required before retry.",
            )
            session.add(log)
            report["interrupted"].append({"id": app.id, "company": app.company, "role": app.job_title})
            report["action_taken"].append(f"Marked #{app.id} {app.company}/{app.job_title} as INTERRUPTED")

        # Include already-interrupted records on every startup so review remains visible.
        result = await session.execute(select(Application).where(Application.status == ApplicationStatus.INTERRUPTED))
        report["interrupted"] = [{"id": app.id, "company": app.company, "role": app.job_title} for app in result.scalars().all()]

        # Reset the global agent state to STOPPED (in case it was stuck RUNNING)
        result = await session.execute(select(AgentState).where(AgentState.id == 1))
        state = result.scalar_one_or_none()
        if state and state.state not in (AgentStateEnum.STOPPED, AgentStateEnum.ERROR):
            previous_state = state.state
            state.state = AgentStateEnum.STOPPED
            state.stop_requested = False
            state.pause_requested = False
            state.force_kill_requested = False
            state.stopped_at = datetime.now(timezone.utc)
            report["action_taken"].append(f"Reset stuck agent state from {previous_state.value} to STOPPED")

        # Find paused applications eligible to resume
        result = await session.execute(
            select(Application).where(Application.status == ApplicationStatus.PAUSED)
        )
        for app in result.scalars().all():
            report["paused"].append({"id": app.id, "company": app.company, "role": app.job_title})

        # Find needs_attention
        result = await session.execute(
            select(Application).where(Application.status == ApplicationStatus.NEEDS_ATTENTION)
        )
        for app in result.scalars().all():
            report["needs_attention"].append({"id": app.id, "company": app.company, "role": app.job_title})

        # Find needs_review (do NOT auto-retry)
        result = await session.execute(
            select(Application).where(Application.status == ApplicationStatus.NEEDS_REVIEW)
        )
        for app in result.scalars().all():
            report["needs_review"].append({"id": app.id, "company": app.company, "role": app.job_title})

    if report["action_taken"]:
        logger.warning("Recovery actions taken on startup: %s", report["action_taken"])
    else:
        logger.info("No recovery needed — clean startup.")

    return report
