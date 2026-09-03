"""Run lifecycle.

Owns idempotency, background execution, and the run record that the dashboard
polls. Submitting the same batch twice returns the original run instead of
double-processing a settlement file — the one bug you cannot ship in finance.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from app.config import settings
from app.core.enums import RunStatus
from app.data import generator, storage
from app.services.pipeline import ReconciliationPipeline
from app.store.db import session_scope
from app.store.models import Dataset, Run

log = logging.getLogger(__name__)


def new_run_id() -> str:
    return f"RUN_{uuid.uuid4().hex[:12].upper()}"


def _set(run_id: str, **fields: Any) -> None:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        for k, v in fields.items():
            setattr(run, k, v)


def create_run(
    *,
    label: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[Run, bool]:
    """Returns (run, created). `created=False` means we replayed an existing run."""
    with session_scope() as s:
        if idempotency_key:
            existing = s.query(Run).filter(Run.idempotency_key == idempotency_key).one_or_none()
            if existing is not None:
                log.info("idempotent replay for key %s -> %s", idempotency_key, existing.id)
                return existing, False
        run = Run(
            id=new_run_id(), label=label, idempotency_key=idempotency_key,
            status=RunStatus.QUEUED.value,
        )
        s.add(run)
        s.flush()
        s.expunge(run)
        return run, True


def load_dataset(dataset_id: str) -> dict[str, pl.DataFrame]:
    root = settings.dataset_dir(dataset_id)
    if not root.exists():
        raise FileNotFoundError(f"dataset {dataset_id} not found")
    return {
        "orders": pl.read_parquet(root / "orders.parquet"),
        "payments": pl.read_parquet(root / "payments.parquet"),
        "settlements": pl.read_parquet(root / "settlements.parquet"),
    }


def register_dataset(dataset_id: str, label: str, ds: generator.GeneratedDataset) -> None:
    with session_scope() as s:
        s.merge(Dataset(
            id=dataset_id, label=label, kind="synthetic",
            orders=ds.orders.height, payments=ds.payments.height,
            settlements=ds.settlements.height, has_ground_truth=True,
            meta=ds.stats,
        ))


async def execute_run(
    run_id: str,
    frames: dict[str, pl.DataFrame],
    source_names: dict[str, str] | None = None,
    mappings: dict[str, dict[str, str]] | None = None,
    use_ai: bool = True,
) -> None:
    """Background executor. Failures are recorded, never swallowed."""

    def progress(**kwargs: Any) -> None:
        _set(run_id, **kwargs)

    try:
        pipeline = ReconciliationPipeline(run_id=run_id, on_progress=progress)

        # The deterministic pass is CPU-bound; keep it off the event loop so the
        # API stays responsive while a million rows reconcile.
        outcome = await asyncio.to_thread(
            pipeline.run_sync,
            frames["orders"], frames["payments"], frames["settlements"],
            source_names, mappings,
        )

        if use_ai and settings.ai_enabled:
            outcome = await pipeline.run_ai_stage(outcome)

        summary = outcome["summary"]
        _set(
            run_id,
            status=RunStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc),
            records_total=sum(outcome["counts"].values()),
            matched=summary.get("matched", 0),
            exceptions=summary.get("exceptions", 0),
            auto_resolved=summary.get("auto_resolved", 0),
            ai_resolved=summary.get("ai_resolved", 0),
            human_review=summary.get("human_review", 0),
            duration_seconds=outcome["timings"]["total_seconds"],
            throughput_per_second=outcome["throughput_per_second"],
            ai_calls=outcome.get("ai", {}).get("ai_calls", 0),
            manifest=outcome,
        )
        log.info("run %s completed in %.2fs", run_id, outcome["timings"]["total_seconds"])

    except Exception as exc:  # noqa: BLE001
        log.exception("run %s failed", run_id)
        _set(run_id, status=RunStatus.FAILED.value, error=str(exc),
             completed_at=datetime.now(timezone.utc))


def read_recon(run_id: str) -> pl.DataFrame:
    path = storage.artifact_path(run_id, "recon")
    if not path.exists():
        raise FileNotFoundError(f"no reconciliation output for {run_id}")
    return pl.read_parquet(path)


def read_exceptions(run_id: str) -> pl.DataFrame:
    path = storage.artifact_path(run_id, "exceptions")
    if not path.exists():
        return read_recon(run_id).filter(pl.col("exception_type") != "MATCHED")
    return pl.read_parquet(path)


def save_uploads(run_id: str, files: dict[str, tuple[str, bytes]]) -> dict[str, Path]:
    """Persist raw uploads before touching them, so a failed run can be replayed
    against the exact bytes that produced it."""
    root = settings.run_dir(run_id) / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for kind, (filename, blob) in files.items():
        path = root / f"{kind.lower()}_{Path(filename).name}"
        path.write_bytes(blob)
        out[kind] = path
    return out
