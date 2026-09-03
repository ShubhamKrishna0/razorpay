"""Structured output contracts.

The model is never allowed to answer in prose. Every response is validated
against these schemas at the API layer, so a malformed verdict is a retry
rather than a corrupt ledger entry.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.enums import ExceptionType


class ExceptionVerdict(BaseModel):
    """One adjudicated exception."""

    case_id: str = Field(description="The case_id exactly as given in the input.")
    classification: ExceptionType = Field(
        description="The exception type you believe is correct after analysis."
    )
    resolution: Literal["RESOLVED", "NEEDS_HUMAN"] = Field(
        description=(
            "RESOLVED only when the discrepancy is fully explained by the evidence "
            "provided. If any part of the difference is unaccounted for, say NEEDS_HUMAN."
        )
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Your calibrated confidence. Do not inflate; low confidence is useful.",
    )
    explanation: str = Field(
        max_length=500,
        description="One or two sentences a finance controller can act on.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Specific figures from the input that support the classification.",
    )
    suggested_action: str = Field(
        default="",
        max_length=200,
        description="What a human should do next, if anything.",
    )


class BatchVerdict(BaseModel):
    """Wrapper so one request adjudicates many exceptions."""

    verdicts: list[ExceptionVerdict] = Field(
        description="Exactly one verdict per input case, in any order."
    )


class ChatAnswer(BaseModel):
    """Answer to a finance controller's natural-language question."""

    answer: str = Field(max_length=2000, description="Direct answer, leading with the number.")
    breakdown: list["ChatBreakdownLine"] = Field(default_factory=list, max_length=12)
    followups: list[str] = Field(default_factory=list, max_length=3)
    used_figures: list[str] = Field(
        default_factory=list, max_length=10,
        description="Figures quoted from the supplied context. Never invent one.",
    )


class ChatBreakdownLine(BaseModel):
    label: str = Field(max_length=80)
    amount_minor: int
    count: int = 0


ChatAnswer.model_rebuild()
