"""Reconciliation run endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import polars as pl
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import select

from app.api.schemas import RunDetail, RunRequest, RunSummary
from app.core.enums import RunStatus
from app.services import run_manager
from app.store.db import session_scope
from app.store.models import Run

router = APIRouter(prefix="/runs", tags=["runs"])


def _to_summary(run: Run) -> RunSummary:
    total_cases = max(run.matched + run.exceptions, 1)
    manifest = run.manifest or {}
    pending = manifest.get("summary", {}).get("pending_ai", 0)
    analyzed = manifest.get("ai", {}).get("analyzed", pending)
    return RunSummary(
        run_id=run.id, status=run.status, label=run.label,
        records_total=run.records_total, matched=run.matched,
        exceptions=run.exceptions, auto_resolved=run.auto_resolved,
        ai_resolved=run.ai_resolved, human_review=run.human_review,
        match_rate=round(run.matched / total_cases, 4),
        duration_seconds=run.duration_seconds,
        throughput_per_second=run.throughput_per_second,
        ai_calls=run.ai_calls,
        # The number worth putting on a slide: how little of the dataset the
        # model ever had to touch.
        ai_coverage=round(analyzed / max(run.records_total, 1), 6),
        created_at=run.created_at, completed_at=run.completed_at, error=run.error,
    )


@router.post("", response_model=RunSummary, status_code=202)
async def start_run(req: RunRequest, background: BackgroundTasks) -> RunSummary:
    try:
        frames = run_manager.load_dataset(req.dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    run, created = run_manager.create_run(
        label=req.label or f"Run over {req.dataset_id}",
        idempotency_key=req.idempotency_key,
    )
    if not created:
        # Idempotent replay: same key, same answer, no double-processing.
        with session_scope() as s:
            return _to_summary(s.get(Run, run.id))

    run_manager._set(run.id, status=RunStatus.QUEUED.value)
    background.add_task(
        _run_in_background, run.id, frames, req.dataset_id, req.use_ai
    )
    with session_scope() as s:
        return _to_summary(s.get(Run, run.id))


async def _run_in_background(
    run_id: str, frames: dict[str, pl.DataFrame], dataset_id: str, use_ai: bool
) -> None:
    await run_manager.execute_run(
        run_id, frames,
        source_names={"ORDER": f"{dataset_id}:orders",
                      "PAYMENT": f"{dataset_id}:payments",
                      "SETTLEMENT": f"{dataset_id}:settlements"},
        use_ai=use_ai,
    )


@router.get("", response_model=list[RunSummary])
def list_runs(limit: int = Query(25, ge=1, le=200)) -> list[RunSummary]:
    with session_scope() as s:
        rows = s.execute(
            select(Run).order_by(Run.created_at.desc()).limit(limit)
        ).scalars().all()
        return [_to_summary(r) for r in rows]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"run {run_id} not found")
        base = _to_summary(run)
        return RunDetail(**base.model_dump(), manifest=run.manifest or {})


@router.get("/{run_id}/breakdown")
def get_breakdown(run_id: str) -> dict:
    """Exception mix plus the money each bucket represents."""
    try:
        recon = run_manager.read_recon(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    grouped = (
        recon.group_by(["exception_type", "resolution"])
        .agg(
            pl.len().alias("count"),
            (pl.col("payment_delta_minor").abs().fill_null(0)
             + pl.col("settlement_delta_minor").abs().fill_null(0)).sum().alias("impact_minor"),
        )
        .sort("count", descending=True)
    )
    totals = {
        "gross_order_minor": int(recon["order_amount_minor"].fill_null(0).sum()),
        "gross_payment_minor": int(recon["payment_amount_minor"].fill_null(0).sum()),
        "gross_settlement_minor": int(recon["settlement_amount_minor"].fill_null(0).sum()),
    }
    totals["settlement_gap_minor"] = totals["gross_payment_minor"] - totals["gross_settlement_minor"]
    return {
        "run_id": run_id,
        "totals": totals,
        "buckets": grouped.to_dicts(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{run_id}/cascade")
def get_cascade(run_id: str) -> dict:
    """How many records each level of the cascade closed.

    This is the efficiency story in one table: L1 does the heavy lifting, the
    fuzzy stage sees almost nothing, and the model sees less still.
    """
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, f"run {run_id} not found")
        manifest = run.manifest or {}
        return {
            "run_id": run_id,
            "cascade": manifest.get("cascade", {}),
            "timings": manifest.get("timings", {}),
            "counts": manifest.get("counts", {}),
            "ai": manifest.get("ai", {}),
        }
