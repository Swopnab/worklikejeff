"""
database/models.py
SQLAlchemy ORM models for the JobAgent database.
All models use Integer primary keys for SQLite compatibility.
"""
import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, event,
    Integer, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ============================================================
# ENUMS
# ============================================================

class ApplicationStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    FILTERED_OUT = "filtered_out"
    ANALYZED = "analyzed"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    SKIPPED = "skipped"
    RESUME_GENERATED = "resume_generated"
    RESUME_COMPILE_ERROR = "resume_compile_error"
    READY = "ready"
    FORM_FILLED = "form_filled"
    READY_FOR_REVIEW = "ready_for_review"
    USER_REVIEWING = "user_reviewing"
    APPLYING = "applying"
    NEEDS_ATTENTION = "needs_attention"
    HANDOFF = "handoff"
    PAUSED = "paused"
    SUBMITTED = "submitted"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    NEEDS_REVIEW = "needs_review"
    WITHDRAWN = "withdrawn"
    ARTIFACT_ERROR = "artifact_error"


class AgentStateEnum(str, enum.Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    NEEDS_ATTENTION = "needs_attention"
    HANDOFF = "handoff"
    STOP_REQUESTED = "stop_requested"
    STOPPING = "stopping"
    ERROR = "error"


class ActivityEventType(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    OPENING_JOB = "OPENING_JOB"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
    MFA_DETECTED = "MFA_DETECTED"
    HANDOFF_STARTED = "HANDOFF_STARTED"
    HANDOFF_RETURNED = "HANDOFF_RETURNED"
    DESCRIPTION_EXTRACTED = "DESCRIPTION_EXTRACTED"
    ELIGIBILITY_PASSED = "ELIGIBILITY_PASSED"
    ELIGIBILITY_FAILED = "ELIGIBILITY_FAILED"
    MATCH_SCORE = "MATCH_SCORE"
    RESUME_GENERATED = "RESUME_GENERATED"
    RESUME_VALIDATED = "RESUME_VALIDATED"
    ATS_OPENED = "ATS_OPENED"
    APPLICATION_PAGE = "APPLICATION_PAGE"
    FORM_FILLED = "FORM_FILLED"
    SUBMITTED = "SUBMITTED"
    CONFIRMATION_DETECTED = "CONFIRMATION_DETECTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_STOPPED = "AGENT_STOPPED"
    AGENT_ERROR = "AGENT_ERROR"
    CHECKPOINT_SAVED = "CHECKPOINT_SAVED"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    POSTING_CLOSED = "POSTING_CLOSED"
    AI_OFFLINE = "AI_OFFLINE"
    DRY_RUN_STOP = "DRY_RUN_STOP"


# ============================================================
# MODELS
# ============================================================

class Application(Base):
    """
    Central record for every job the agent processes.
    One row per unique job. Never deleted — only status updated.
    """
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    job_title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    job_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_job_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalized_company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    normalized_job_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # greenhouse, lever, linkedin, manual
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remote_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # remote, hybrid, onsite
    external_job_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Job content
    job_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_description_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Timestamps
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    application_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    application_submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Eligibility
    eligibility_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    eligibility_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Matching
    match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    match_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON

    # Decision & status
    decision: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # apply, skip
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus),
        default=ApplicationStatus.DISCOVERED,
        nullable=False,
        index=True,
    )

    # Resume artifacts
    resume_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resume_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resume_projects: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    resume_skills: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # JSON list

    # Application artifacts
    cover_letter_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answers_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    artifact_dir: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # local fs path

    # Review gate & Safety
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    review_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    submission_confirmed_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    resume_compiler_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Outcome
    submission_confirmation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pause_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        "ActivityLog", back_populates="application", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_applications_company_title", "company", "job_title"),
        Index("ix_applications_normalized_identity", "normalized_company", "normalized_job_title", "status"),
        Index("ix_applications_canonical_url", "canonical_job_url"),
        Index("ix_applications_job_url", "job_url"),
        Index("ix_applications_external_job_id", "external_job_id"),
        Index("ix_applications_status_discovered", "status", "discovered_at"),
    )

    def __repr__(self) -> str:
        return f"<Application id={self.id} company={self.company!r} status={self.status}>"


class ActivityLog(Base):
    """
    Append-only event log for every application.
    Never update or delete rows — only insert.
    NEVER log passwords, tokens, cookies, or secrets.
    """
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON or plain text
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    application: Mapped[Optional["Application"]] = relationship(
        "Application", back_populates="activity_logs"
    )

    def __repr__(self) -> str:
        return f"<ActivityLog id={self.id} event={self.event_type} app_id={self.application_id}>"


class AgentState(Base):
    """
    Singleton-ish table storing the current agent FSM state.
    Only one active row (id=1) at a time.
    """
    __tablename__ = "agent_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    state: Mapped[AgentStateEnum] = mapped_column(
        Enum(AgentStateEnum),
        default=AgentStateEnum.STOPPED,
        nullable=False,
    )
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    force_kill_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    current_task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("applications.id"), nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checkpoint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AgentState state={self.state} task_id={self.current_task_id}>"


class JobQueue(Base):
    """
    Queue of discovered jobs waiting to be processed.
    Jobs move from here into Application records.
    """
    __tablename__ = "job_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    job_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1=highest, 10=lowest
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    application_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("applications.id"), nullable=True
    )

    __table_args__ = (
        Index("ix_job_queue_processed_priority", "processed", "priority", "queued_at"),
    )

    def __repr__(self) -> str:
        return f"<JobQueue id={self.id} url={self.job_url[:50]!r} processed={self.processed}>"


@event.listens_for(Application, "before_insert")
@event.listens_for(Application, "before_update")
def maintain_job_identity(mapper, connection, application):
    from jobs.dedupe import normalize_text, normalize_url
    application.normalized_company = normalize_text(application.company)
    application.normalized_job_title = normalize_text(application.job_title)
    application.canonical_job_url = normalize_url(application.job_url)
