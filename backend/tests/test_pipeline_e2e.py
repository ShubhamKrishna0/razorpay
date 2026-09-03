"""End-to-end: the pipeline, the accuracy claim, and idempotent restart."""

from __future__ import annotations

import uuid

import polars as pl

from app.bench.metrics import evaluate
from app.data import generator, storage
from app.services.pipeline import ReconciliationPipeline


def test_pipeline_meets_its_accuracy_claim():
    ds = generator.generate(4000, "e2e", seed=99)
    out = ReconciliationPipeline(f"E2E_{uuid.uuid4().hex[:8]}").run_sync(
        ds.orders, ds.payments, ds.settlements
    )
    recon = pl.read_parquet(out["recon_path"])
    report = evaluate(recon, ds.ground_truth)

    # These are the numbers on the benchmark screen. If they regress, the demo
    # is lying, so the build should fail first.
    assert report.precision >= 0.99
    assert report.recall >= 0.99
    assert report.label_accuracy >= 0.95


def test_deterministic_pass_is_reproducible():
    """Same inputs, same output. No model, no randomness, no drift."""
    ds = generator.generate(1500, "repro", seed=3)
    a = ReconciliationPipeline(f"R1_{uuid.uuid4().hex[:6]}").run_sync(
        ds.orders, ds.payments, ds.settlements
    )
    b = ReconciliationPipeline(f"R2_{uuid.uuid4().hex[:6]}").run_sync(
        ds.orders, ds.payments, ds.settlements
    )
    assert a["summary"] == b["summary"]

    ra = pl.read_parquet(a["recon_path"]).sort("case_id")
    rb = pl.read_parquet(b["recon_path"]).sort("case_id")
    assert ra["exception_type"].to_list() == rb["exception_type"].to_list()


def test_checkpoint_is_written_for_restart():
    run_id = f"CKPT_{uuid.uuid4().hex[:8]}"
    ds = generator.generate(500, "ckpt", seed=4)
    ReconciliationPipeline(run_id).run_sync(ds.orders, ds.payments, ds.settlements)
    state = storage.load_checkpoint(run_id)
    assert state.get("completed") is True


def test_ai_only_ever_sees_a_slice_of_the_dataset():
    """The efficiency claim, asserted rather than asserted-in-a-slide."""
    ds = generator.generate(4000, "cov", seed=8)
    out = ReconciliationPipeline(f"COV_{uuid.uuid4().hex[:8]}").run_sync(
        ds.orders, ds.payments, ds.settlements
    )
    summary = out["summary"]
    ai_share = summary["pending_ai"] / summary["total_cases"]
    assert ai_share < 0.10, f"AI would touch {ai_share:.1%} of cases"
