"""Finance control chat: natural-language questions over a completed run."""

from __future__ import annotations

import polars as pl
from fastapi import APIRouter, HTTPException

from app.ai.chat import answer_question
from app.services.moneyfmt import add_display_amounts
from app.api.schemas import ChatRequest, ChatResponse
from app.services import run_manager
from app.store.db import session_scope
from app.store.models import Run

router = APIRouter(prefix="/finance", tags=["finance"])


def build_context(run_id: str) -> dict:
    """Assemble a bounded, fully-aggregated context.

    Cost and latency here are flat regardless of dataset size, because the model
    sees totals and the top breaks — never the underlying rows.
    """
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"run {run_id} not found")
        manifest = run.manifest or {}

    recon = run_manager.read_recon(run_id)
    exceptions = recon.filter(pl.col("exception_type") != "MATCHED")

    by_type = (
        exceptions.group_by("exception_type")
        .agg(
            pl.len().alias("count"),
            (pl.col("payment_delta_minor").abs().fill_null(0)
             + pl.col("settlement_delta_minor").abs().fill_null(0)).sum().alias("impact_minor"),
        )
        .sort("impact_minor", descending=True)
    )

    top_breaks = (
        exceptions.with_columns(
            (pl.col("payment_delta_minor").abs().fill_null(0)
             + pl.col("settlement_delta_minor").abs().fill_null(0)).alias("impact_minor")
        )
        .sort("impact_minor", descending=True)
        .head(10)
        .select([
            "case_id", "exception_type", "merchant_id", "impact_minor",
            "order_amount_minor", "payment_amount_minor", "settlement_amount_minor",
        ])
    )

    by_merchant = (
        exceptions.group_by("merchant_id")
        .agg(
            pl.len().alias("count"),
            (pl.col("payment_delta_minor").abs().fill_null(0)
             + pl.col("settlement_delta_minor").abs().fill_null(0)).sum().alias("impact_minor"),
        )
        .sort("impact_minor", descending=True)
        .head(8)
    )

    gross_payment = int(recon["payment_amount_minor"].fill_null(0).sum())
    gross_settlement = int(recon["settlement_amount_minor"].fill_null(0).sum())

    context = {
        "run_id": run_id,
        "status": run.status,
        "records_processed": run.records_total,
        "cases": recon.height,
        "matched": run.matched,
        "exceptions": run.exceptions,
        "auto_resolved": run.auto_resolved,
        "ai_resolved": run.ai_resolved,
        "awaiting_human_review": run.human_review,
        "totals_minor": {
            "gross_orders": int(recon["order_amount_minor"].fill_null(0).sum()),
            "gross_payments": gross_payment,
            "gross_settlements": gross_settlement,
            "settlement_gap": gross_payment - gross_settlement,
        },
        "exceptions_by_type": by_type.to_dicts(),
        "exceptions_by_merchant": by_merchant.to_dicts(),
        "largest_breaks": top_breaks.to_dicts(),
        "ai_stats": manifest.get("ai", {}),
        "currency": "INR",
    }
    # The model must never convert paise to rupees itself — a slipped factor of
    # 100 in an answer a controller acts on is the worst bug this app can have,
    # and it happened in testing (Rs 16,215 reported as "Rs 16.22 lakh").
    return add_display_amounts(context)


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    try:
        context = build_context(req.run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    payload = await answer_question(req.question, context)
    return ChatResponse(**payload)


@router.get("/context/{run_id}")
def get_context(run_id: str) -> dict:
    """The exact context the chat endpoint sends to the model.

    Exposed deliberately: if the model can only see this, anyone can verify
    the answers are grounded rather than invented.
    """
    return build_context(run_id)
