"""Relational state.

Parquet holds the millions of rows; this holds the handful of facts an operator
queries: which runs exist, what they concluded, and who decided what. SQLite
locally, Postgres on Render — same schema either way.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: Idempotency key. The same inputs submitted twice reuse the same run
    #: rather than double-processing a settlement file.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    label: Mapped[str | None] = mapped_column(String(200))
    engine_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)

    records_total: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer, default=0)
    exceptions: Mapped[int] = mapped_column(Integer, default=0)
    auto_resolved: Mapped[int] = mapped_column(Integer, default=0)
    ai_resolved: Mapped[int] = mapped_column(Integer, default=0)
    human_review: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    throughput_per_second: Mapped[float] = mapped_column(Float, default=0.0)
    ai_calls: Mapped[int] = mapped_column(Integer, default=0)

    manifest: Mapped[dict] = mapped_column(JSON, default=dict)

    audits: Mapped[list["AuditEntry"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_run_idempotency"),)


class AuditEntry(Base):
    """Every decision, with the rule that made it and the version that made it."""

    __tablename__ = "audit_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    case_id: Mapped[str | None] = mapped_column(String(128), index=True)
    event: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64), default="engine")
    rule: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    engine_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    run: Mapped[Run] = relationship(back_populates="audits")


class ReviewDecision(Base):
    """A human closing the loop. Kept separate from the engine's own output so
    the two are never confused in an audit."""

    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(128), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    reviewer: Mapped[str] = mapped_column(String(120), default="unknown")
    note: Mapped[str | None] = mapped_column(Text)
    accepted_ai_suggestion: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("run_id", "case_id", name="uq_review_case"),)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="synthetic")
    orders: Mapped[int] = mapped_column(Integer, default=0)
    payments: Mapped[int] = mapped_column(Integer, default=0)
    settlements: Mapped[int] = mapped_column(Integer, default=0)
    has_ground_truth: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
