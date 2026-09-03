"""Adversarial cases.

Clean data proves nothing. These are the shapes that make a naive matcher look
correct while it quietly mis-books money: near-duplicates, off-by-one amounts,
date-boundary drift, refunds that net to zero, and pairs that must NOT match.
"""

from __future__ import annotations

import uuid

import polars as pl
import pytest

from app.core.enums import ExceptionType
from app.services.pipeline import ReconciliationPipeline


def _run(orders, payments, settlements) -> pl.DataFrame:
    run_id = f"TEST_{uuid.uuid4().hex[:8]}"
    out = ReconciliationPipeline(run_id).run_sync(
        pl.DataFrame(orders), pl.DataFrame(payments), pl.DataFrame(settlements)
    )
    return pl.read_parquet(out["recon_path"])


def _order(oid, txn, amount, ts="2026-08-01 10:00:00", merchant="M1"):
    return {"order_id": oid, "txn_id": txn, "merchant_id": merchant,
            "amount": amount, "currency": "INR", "timestamp": ts,
            "status": "PLACED", "reference": f"ORD-{oid}"}


def _payment(oid, txn, amount, ts="2026-08-01 10:05:00", merchant="M1",
             fee=None, status="CAPTURED"):
    return {"transaction_id": txn, "order_id": oid, "merchant_id": merchant,
            "amount": amount, "fee": fee if fee is not None else round(amount * 0.02, 2),
            "currency": "INR", "payment_date": ts, "status": status,
            "narration": f"PAY-{oid}"}


def _settlement(oid, txn, amount, ts="2026-08-03 10:00:00", merchant="M1", fee=0.0):
    return {"utr": txn, "order_id": oid, "merchant_id": merchant,
            "settlement_amount": amount, "commission": fee, "currency": "INR",
            "settlement_date": ts, "status": "SETTLED",
            "settlement_reference": f"STL-{oid}"}


def _label(recon: pl.DataFrame, case_id: str) -> str:
    row = recon.filter(pl.col("case_id") == case_id)
    assert row.height == 1, f"expected exactly one case {case_id}, got {row.height}"
    return row["exception_type"][0]


def test_clean_three_way_match_is_clean():
    recon = _run(
        [_order("ORD1", "T1", 1000.0)],
        [_payment("ORD1", "T1", 1000.0, fee=20.0)],
        [_settlement("ORD1", "T1", 980.0, fee=20.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.MATCHED.value


def test_exact_duplicate_payment_is_flagged():
    recon = _run(
        [_order("ORD1", "T1", 1000.0)],
        [_payment("ORD1", "T1", 1000.0, fee=20.0),
         _payment("ORD1", "T1", 1000.0, ts="2026-08-01 10:06:30", fee=20.0)],
        [_settlement("ORD1", "T1", 980.0, fee=20.0)],
    )
    assert ExceptionType.DUPLICATE.value in recon["exception_type"].to_list()


def test_off_by_one_rupee_is_not_a_break():
    """₹1 of rounding noise must not become an exception, or the queue drowns."""
    recon = _run(
        [_order("ORD1", "T1", 1000.0)],
        [_payment("ORD1", "T1", 999.50, fee=20.0)],
        [_settlement("ORD1", "T1", 979.50, fee=20.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.MATCHED.value


def test_underpayment_is_partial_payment():
    recon = _run(
        [_order("ORD1", "T1", 5000.0)],
        [_payment("ORD1", "T1", 3000.0, fee=60.0)],
        [_settlement("ORD1", "T1", 2940.0, fee=60.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.PARTIAL_PAYMENT.value


def test_overpayment_is_distinguished_from_underpayment():
    recon = _run(
        [_order("ORD1", "T1", 1000.0)],
        [_payment("ORD1", "T1", 1500.0, fee=30.0)],
        [_settlement("ORD1", "T1", 1470.0, fee=30.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.OVERPAYMENT.value


def test_settlement_short_by_the_declared_fee_is_matched():
    """settlement = payment - fee is arithmetic, not a discrepancy."""
    recon = _run(
        [_order("ORD1", "T1", 5000.0)],
        [_payment("ORD1", "T1", 5000.0, fee=100.0)],
        [_settlement("ORD1", "T1", 4900.0, fee=100.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.MATCHED.value


def test_settlement_short_beyond_the_fee_is_a_shortfall():
    """₹100 fee declared, ₹400 actually withheld — ₹300 is unexplained."""
    recon = _run(
        [_order("ORD1", "T1", 5000.0)],
        [_payment("ORD1", "T1", 5000.0, fee=100.0)],
        [_settlement("ORD1", "T1", 4600.0, fee=100.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.SETTLEMENT_SHORTFALL.value


def test_fee_above_contracted_rate_is_a_variance():
    """Gap equals the declared fee, but the gateway declared 6% on a 2% contract."""
    recon = _run(
        [_order("ORD1", "T1", 5000.0)],
        [_payment("ORD1", "T1", 5000.0, fee=300.0)],
        [_settlement("ORD1", "T1", 4700.0, fee=300.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.FEE_VARIANCE.value


def test_missing_payment_detected():
    recon = _run([_order("ORD1", "T1", 1000.0)], [], [])
    assert _label(recon, "ORD-0000000000") == ExceptionType.MISSING_PAYMENT.value


def test_missing_settlement_detected():
    recon = _run(
        [_order("ORD1", "T1", 1000.0)],
        [_payment("ORD1", "T1", 1000.0, fee=20.0)],
        [],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.MISSING_SETTLEMENT.value


def test_orphan_settlement_detected():
    recon = _run([], [], [_settlement("ORDX", "TX", 900.0)])
    assert ExceptionType.ORPHAN_SETTLEMENT.value in recon["exception_type"].to_list()


def test_wrong_merchant_is_not_silently_matched():
    """Same ids, different merchant. Matching is right; ignoring it is not."""
    recon = _run(
        [_order("ORD1", "T1", 1000.0, merchant="M1")],
        [_payment("ORD1", "T1", 1000.0, merchant="M2", fee=20.0)],
        [_settlement("ORD1", "T1", 980.0, merchant="M2", fee=20.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.MERCHANT_MISMATCH.value


def test_refund_is_classified_not_treated_as_a_break():
    recon = _run(
        [_order("ORD1", "T1", 1000.0)],
        [_payment("ORD1", "T1", 1000.0, status="REFUNDED", fee=0.0)],
        [],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.REFUND.value


def test_late_payment_beyond_window_is_timing_mismatch():
    recon = _run(
        [_order("ORD1", "T1", 1000.0, ts="2026-08-01 10:00:00")],
        [_payment("ORD1", "T1", 1000.0, ts="2026-08-06 10:00:00", fee=20.0)],
        [_settlement("ORD1", "T1", 980.0, ts="2026-08-08 10:00:00", fee=20.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.TIMING_MISMATCH.value


def test_unrelated_records_are_never_cross_matched():
    """Two different merchants, different amounts, different days. Any link
    here would be a false positive — the expensive kind of error."""
    recon = _run(
        [_order("ORDA", "TA", 1000.0, ts="2026-08-01 10:00:00", merchant="M1")],
        [_payment("ORDB", "TB", 7777.0, ts="2026-08-20 10:00:00", merchant="M9", fee=0.0)],
        [],
    )
    labels = set(recon["exception_type"].to_list())
    assert ExceptionType.MISSING_PAYMENT.value in labels
    assert ExceptionType.ORPHAN_PAYMENT.value in labels
    assert ExceptionType.MATCHED.value not in labels


@pytest.mark.parametrize("amount", [0.01, 0.99, 12345678.90])
def test_extreme_amounts_survive_the_round_trip(amount: float):
    recon = _run(
        [_order("ORD1", "T1", amount)],
        [_payment("ORD1", "T1", amount, fee=0.0)],
        [_settlement("ORD1", "T1", amount, fee=0.0)],
    )
    assert _label(recon, "ORD-0000000000") == ExceptionType.MATCHED.value


def test_missing_settlement_exposes_the_full_amount_not_net_of_fee():
    """A fee that was never charged must not be netted off the exposure.

    The gateway deducts its fee when it settles. If it never settled, there is
    no fee — so the outstanding amount is the whole payment. Reporting it net
    of a phantom fee under-states what is at risk.
    """
    recon = _run(
        [_order("ORD1", "T1", 12500.0)],
        [_payment("ORD1", "T1", 12500.0, fee=250.0)],
        [],
    )
    row = recon.filter(pl.col("case_id") == "ORD-0000000000").to_dicts()[0]

    assert row["exception_type"] == ExceptionType.MISSING_SETTLEMENT.value
    assert row["settlement_amount_minor"] is None
    # The engine still reports the declared fee — it is a fact about the
    # payment — but nothing settled, so it must not reduce the exposure.
    assert row["expected_fee_minor"] == 25000
    assert row["payment_amount_minor"] == 1250000


def test_structural_breaks_are_never_sent_to_the_model():
    """MISSING_PAYMENT / MISSING_SETTLEMENT are absences, not ambiguities.
    Spending a model call to be told a record is missing buys nothing."""
    from app.core.enums import AI_ELIGIBLE

    for absent in (ExceptionType.MISSING_PAYMENT, ExceptionType.MISSING_SETTLEMENT):
        assert absent not in AI_ELIGIBLE


def test_duplicate_payment_cannot_steal_the_originals_settlement():
    """The duplicate arrives 90s after the original, so it sits CLOSER to the
    settlement in time and used to win the tie-break — booking the real payment
    as missing-settlement while the duplicate looked reconciled."""
    recon = _run(
        [_order("ORD1", "T1", 1000.0)],
        [_payment("ORD1", "T1", 1000.0, fee=20.0),
         _payment("ORD1", "T1", 1000.0, ts="2026-08-01 10:06:30", fee=20.0)],
        [_settlement("ORD1", "T1", 980.0, fee=20.0)],
    )
    order_case = recon.filter(pl.col("case_id") == "ORD-0000000000").to_dicts()[0]
    # The original keeps its settlement; the order side reconciles clean.
    assert order_case["settlement_uid"] is not None
    assert order_case["exception_type"] == ExceptionType.MATCHED.value
    # The duplicate is still surfaced as its own finding.
    assert ExceptionType.DUPLICATE.value in recon["exception_type"].to_list()


def test_fuzzy_match_refuses_when_every_identifier_disagrees():
    """Same merchant, same amount, same day — but both sides carry txn and
    order ids that all contradict. A coincidence of merchant+amount+day is not
    evidence; gluing these together would hide two real breaks."""
    recon = _run(
        [_order("ORD1", "T1", 1000.0, ts="2026-08-01 10:00:00")],
        [_payment("ORD9", "T9", 1000.0, ts="2026-08-01 11:00:00")],
        [],
    )
    labels = set(recon["exception_type"].to_list())
    assert ExceptionType.MISSING_PAYMENT.value in labels
    assert ExceptionType.ORPHAN_PAYMENT.value in labels
    assert ExceptionType.MATCHED.value not in labels
