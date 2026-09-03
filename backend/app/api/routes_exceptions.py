"""Exception queue: browse, drill in, ask the AI, and record a human decision."""

from __future__ import annotations

import polars as pl
from fastapi import APIRouter, HTTPException, Query

from app.ai.analyzer import ExceptionAnalyzer
from app.api.schemas import (
    ExceptionPage, ExceptionRow, InvestigateResponse, ReviewRequest,
)
from app.core.enums import AI_ELIGIBLE, ExceptionType, Resolution
from app.services import run_manager
from app.services.audit import AuditTrail
from app.store.db import session_scope
from app.store.models import ReviewDecision

router = APIRouter(prefix="/runs/{run_id}/exceptions", tags=["exceptions"])

_ROW_FIELDS = set(ExceptionRow.model_fields.keys())


def _row(d: dict) -> ExceptionRow:
    payload = {k: v for k, v in d.items() if k in _ROW_FIELDS}
    payload.setdefault("case_id", d.get("case_id") or "unknown")
    ev = payload.get("ai_evidence")
    payload["ai_evidence"] = list(ev) if ev else []
    try:
        payload["ai_eligible"] = ExceptionType(d.get("exception_type")) in AI_ELIGIBLE
    except ValueError:
        payload["ai_eligible"] = False
    return ExceptionRow(**payload)


def _load(run_id: str) -> pl.DataFrame:
    try:
        return run_manager.read_exceptions(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("", response_model=ExceptionPage)
def list_exceptions(
    run_id: str,
    exception_type: str | None = None,
    resolution: str | None = None,
    merchant_id: str | None = None,
    min_impact_minor: int = Query(0, ge=0),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> ExceptionPage:
    df = _load(run_id)
    if exception_type:
        df = df.filter(pl.col("exception_type") == exception_type)
    if resolution:
        df = df.filter(pl.col("resolution") == resolution)
    if merchant_id:
        df = df.filter(pl.col("merchant_id") == merchant_id)
    if min_impact_minor:
        impact = (pl.col("payment_delta_minor").abs().fill_null(0)
                  + pl.col("settlement_delta_minor").abs().fill_null(0))
        df = df.filter(impact >= min_impact_minor)

    # Biggest money first — that is the order a controller works the queue in.
    df = df.with_columns(
        (pl.col("payment_delta_minor").abs().fill_null(0)
         + pl.col("settlement_delta_minor").abs().fill_null(0)).alias("_impact")
    ).sort("_impact", descending=True)

    total = df.height
    page = df.slice(offset, limit).drop("_impact")
    return ExceptionPage(
        items=[_row(d) for d in page.to_dicts()],
        total=total, offset=offset, limit=limit,
    )


@router.get("/{case_id}", response_model=ExceptionRow)
def get_exception(run_id: str, case_id: str) -> ExceptionRow:
    df = _load(run_id).filter(pl.col("case_id") == case_id)
    if df.height == 0:
        raise HTTPException(404, f"case {case_id} not found in run {run_id}")
    return _row(df.to_dicts()[0])


@router.post("/{case_id}/investigate", response_model=InvestigateResponse)
async def investigate(run_id: str, case_id: str) -> InvestigateResponse:
    """Ask the model about one case, on demand.

    Used from the drill-in view when a controller wants reasoning for a case
    the batch pass skipped, or wants it re-derived.
    """
    df = _load(run_id).filter(pl.col("case_id") == case_id)
    if df.height == 0:
        raise HTTPException(404, f"case {case_id} not found in run {run_id}")

    result = await ExceptionAnalyzer().analyze(df.to_dicts())
    verdict = result.verdicts.get(case_id)
    if verdict is None:
        raise HTTPException(502, "no verdict produced for this case")
    return InvestigateResponse(case_id=case_id, verdict=verdict)


@router.post("/{case_id}/review")
def review(run_id: str, case_id: str, req: ReviewRequest) -> dict:
    """Record a human decision.

    The AI's recommendation is never applied to the ledger on its own; this is
    the only path by which a below-threshold case gets closed.
    """
    if req.decision not in {"RESOLVED", "REJECTED", "ESCALATED"}:
        raise HTTPException(400, "decision must be RESOLVED, REJECTED or ESCALATED")

    with session_scope() as s:
        existing = (
            s.query(ReviewDecision)
            .filter(ReviewDecision.run_id == run_id, ReviewDecision.case_id == case_id)
            .one_or_none()
        )
        if existing is not None:
            existing.decision = req.decision
            existing.reviewer = req.reviewer
            existing.note = req.note
            existing.accepted_ai_suggestion = req.accepted_ai_suggestion
        else:
            s.add(ReviewDecision(
                run_id=run_id, case_id=case_id, decision=req.decision,
                reviewer=req.reviewer, note=req.note,
                accepted_ai_suggestion=req.accepted_ai_suggestion,
            ))

    AuditTrail(run_id).record_decision(case_id, req.decision, req.reviewer, req.note)

    if req.decision == "RESOLVED":
        _mark_resolved(run_id, case_id)

    return {"run_id": run_id, "case_id": case_id, "decision": req.decision, "recorded": True}


def _mark_resolved(run_id: str, case_id: str) -> None:
    """Write the human's decision back into the reconciliation artifact."""
    from app.data import storage

    path = storage.artifact_path(run_id, "recon")
    if not path.exists():
        return
    recon = pl.read_parquet(path)
    recon = recon.with_columns(
        pl.when(pl.col("case_id") == case_id)
        .then(pl.lit(Resolution.HUMAN_RESOLVED.value))
        .otherwise(pl.col("resolution"))
        .alias("resolution")
    )
    storage.write_parquet(recon, path)
    storage.write_parquet(
        recon.filter(pl.col("exception_type") != "MATCHED"),
        storage.artifact_path(run_id, "exceptions"),
    )
