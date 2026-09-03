"""Normalization must absorb messy real-world source files."""

from __future__ import annotations

import polars as pl

from app.core.enums import SourceKind
from app.data.normalizer import detect_mapping, normalize_frame


def test_detects_aliased_columns():
    mapping = detect_mapping(
        ["Transaction ID", "Order No", "MERCHANT_ID", "Amount", "Txn Date", "Narration"]
    )
    assert mapping["txn_id"] == "Transaction ID"
    assert mapping["order_id"] == "Order No"
    assert mapping["merchant_id"] == "MERCHANT_ID"
    assert mapping["amount_minor"] == "Amount"
    assert mapping["txn_ts"] == "Txn Date"


def test_money_becomes_integer_minor_units():
    df = pl.DataFrame({
        "txn_id": ["T1", "T2", "T3"],
        "amount": ["₹1,250.00", "(500.50)", "99.999"],
        "date": ["2026-08-01", "2026-08-01", "2026-08-01"],
    })
    out = normalize_frame(df, SourceKind.PAYMENT, "test")
    # No floats survive: comparisons downstream are exact integer comparisons.
    assert out["amount_minor"].to_list() == [125000, 50050, 10000]
    assert out["amount_minor"].dtype == pl.Int64


def test_refund_detected_from_status_or_sign():
    df = pl.DataFrame({
        "txn_id": ["T1", "T2", "T3"],
        "amount": [100.0, -100.0, 100.0],
        "status": ["CAPTURED", "CAPTURED", "REFUNDED"],
        "date": ["2026-08-01"] * 3,
    })
    out = normalize_frame(df, SourceKind.PAYMENT, "test")
    assert out["is_refund"].to_list() == [False, True, True]


def test_failed_transactions_are_dropped():
    """A declined card was never money; it is noise, not an exception."""
    df = pl.DataFrame({
        "txn_id": ["T1", "T2"],
        "amount": [100.0, 100.0],
        "status": ["CAPTURED", "FAILED"],
        "date": ["2026-08-01", "2026-08-01"],
    })
    out = normalize_frame(df, SourceKind.PAYMENT, "test")
    assert out.height == 1
    assert out["txn_id"].to_list() == ["T1"]


def test_reference_digits_extracted():
    df = pl.DataFrame({
        "txn_id": ["T1"], "amount": [100.0], "date": ["2026-08-01"],
        "narration": ["PAY-ORD-98231-XYZ"],
    })
    out = normalize_frame(df, SourceKind.PAYMENT, "test")
    assert out["ref_digits"].to_list() == ["98231"]


def test_multiple_date_formats_parse():
    df = pl.DataFrame({
        "txn_id": ["T1", "T2", "T3"],
        "amount": [1.0, 1.0, 1.0],
        "date": ["2026-08-01 10:30:00", "01/08/2026", "2026-08-03"],
    })
    out = normalize_frame(df, SourceKind.PAYMENT, "test")
    assert out["txn_ts"].null_count() == 0
