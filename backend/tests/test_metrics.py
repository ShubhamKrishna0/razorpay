"""Metric correctness — the benchmark's own tests."""

from __future__ import annotations

import polars as pl

from app.bench.metrics import evaluate
from app.data import generator


def test_perfect_prediction_scores_one():
    truth = pl.DataFrame({
        "order_id": ["A", "B", "C"],
        "expected_label": ["MATCHED", "DUPLICATE", "MATCHED"],
    })
    pred = pl.DataFrame({
        "order_id": ["A", "B", "C"],
        "exception_type": ["MATCHED", "DUPLICATE", "MATCHED"],
    })
    r = evaluate(pred, truth)
    assert r.precision == 1.0 and r.recall == 1.0 and r.label_accuracy == 1.0


def test_closing_a_real_break_is_a_false_positive():
    """The expensive error: the engine called a genuine break clean."""
    truth = pl.DataFrame({"order_id": ["A"], "expected_label": ["DUPLICATE"]})
    pred = pl.DataFrame({"order_id": ["A"], "exception_type": ["MATCHED"]})
    r = evaluate(pred, truth)
    assert r.false_positive == 1
    assert r.precision == 0.0


def test_cause_outranks_symptom_when_an_order_yields_many_cases():
    truth = pl.DataFrame({"order_id": ["A"], "expected_label": ["DUPLICATE"]})
    pred = pl.DataFrame({
        "order_id": ["A", "A"],
        "exception_type": ["MISSING_SETTLEMENT", "DUPLICATE"],
    })
    assert evaluate(pred, truth).label_accuracy == 1.0


def test_generator_injects_the_requested_anomaly_mix():
    ds = generator.generate(2000, "unit", seed=1)
    labels = set(ds.ground_truth["expected_label"].to_list())
    for expected in ("MATCHED", "DUPLICATE", "MISSING_PAYMENT", "FEE_VARIANCE",
                     "ORPHAN_SETTLEMENT", "REFUND"):
        assert expected in labels, f"{expected} never injected"
    clean = ds.ground_truth.filter(pl.col("expected_label") == "MATCHED").height
    # Most records must stay clean, as they do in production.
    assert clean / ds.ground_truth.height > 0.85
