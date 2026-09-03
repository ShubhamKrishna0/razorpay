"""Request/response models for the HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GenerateDatasetRequest(BaseModel):
    size: int = Field(default=10_000, ge=10, le=5_000_000)
    seed: int = 42
    label: str | None = None


class DatasetInfo(BaseModel):
    id: str
    label: str
    orders: int
    payments: int
    settlements: int
    has_ground_truth: bool
    created_at: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    dataset_id: str = Field(description="A dataset registered via /datasets.")
    label: str | None = None
    use_ai: bool = True
    idempotency_key: str | None = Field(
        default=None,
        description="Same key + same inputs returns the original run instead of re-processing.",
    )


class RunSummary(BaseModel):
    run_id: str
    status: str
    label: str | None = None
    records_total: int = 0
    matched: int = 0
    exceptions: int = 0
    auto_resolved: int = 0
    ai_resolved: int = 0
    human_review: int = 0
    match_rate: float = 0.0
    duration_seconds: float = 0.0
    throughput_per_second: float = 0.0
    ai_calls: int = 0
    ai_coverage: float = 0.0
    created_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class RunDetail(RunSummary):
    manifest: dict[str, Any] = Field(default_factory=dict)


class ExceptionRow(BaseModel):
    case_id: str
    exception_type: str
    resolution: str
    merchant_id: str | None = None
    currency: str | None = None
    order_id: str | None = None
    order_amount_minor: int | None = None
    payment_amount_minor: int | None = None
    settlement_amount_minor: int | None = None
    expected_fee_minor: int | None = None
    payment_delta_minor: int | None = None
    settlement_delta_minor: int | None = None
    confidence: float | None = None
    ai_classification: str | None = None
    ai_confidence: float | None = None
    ai_explanation: str | None = None
    ai_evidence: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    validation_reason: str | None = None
    #: Whether this exception type is ever sent to the model. Structural breaks
    #: (a record that simply is not there) need a person, not an explanation.
    ai_eligible: bool = False


class ExceptionPage(BaseModel):
    items: list[ExceptionRow]
    total: int
    offset: int
    limit: int


class InvestigateResponse(BaseModel):
    case_id: str
    verdict: dict[str, Any]


class ReviewRequest(BaseModel):
    decision: str = Field(description="RESOLVED | REJECTED | ESCALATED")
    reviewer: str = "operator"
    note: str | None = None
    accepted_ai_suggestion: bool = False


class ChatRequest(BaseModel):
    run_id: str
    question: str = Field(min_length=3, max_length=1000)


class ChatResponse(BaseModel):
    answer: str
    breakdown: list[dict[str, Any]] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    used_figures: list[str] = Field(default_factory=list)
    degraded: bool = False


class BenchmarkRequest(BaseModel):
    sizes: list[int] | None = None
    seed: int = 42


class BenchmarkResponse(BaseModel):
    results: list[dict[str, Any]]
    generated_at: datetime
