"""Source → canonical normalization.

Two jobs: map arbitrary column names onto the canonical schema, and coerce
values into forms the matcher can join on (integer minor units, UTC timestamps,
digit-only reference keys). Everything dirty gets cleaned exactly once, here.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from app.config import settings
from app.core.canonical import (
    COLUMN_ALIASES,
    FAILED_STATUSES,
    REFUND_STATUSES,
)
from app.core.enums import SourceKind

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _slug(name: str) -> str:
    return _NON_ALNUM.sub("", name.strip().lower())


def detect_mapping(columns: list[str], explicit: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve canonical field -> source column.

    Explicit user mapping always wins; alias detection fills the rest. Exact
    slug matches beat alias matches so a column literally called `order_id`
    never loses to a fuzzy alias hit on another column.
    """
    mapping: dict[str, str] = dict(explicit or {})
    slugs = {_slug(c): c for c in columns}

    for field, aliases in COLUMN_ALIASES.items():
        if field in mapping:
            continue
        if field in slugs:
            mapping[field] = slugs[field]
            continue
        for alias in aliases:
            if alias in slugs:
                mapping[field] = slugs[alias]
                break
    return mapping


def _to_minor(expr: pl.Expr) -> pl.Expr:
    """Money -> integer minor units.

    Strips currency symbols, thousands separators and parenthesized negatives,
    then scales. Rounding happens once, here, so no downstream comparison ever
    has to reason about float equality.
    """
    cleaned = (
        expr.cast(pl.Utf8)
        .str.replace_all(r"[^0-9.\-()]", "")
        .str.replace_all(r"^\((.*)\)$", r"-${1}")
    )
    return (
        cleaned.cast(pl.Float64, strict=False).fill_null(0.0) * settings.amount_scale
    ).round(0).cast(pl.Int64)


def _parse_ts(expr: pl.Expr) -> pl.Expr:
    """Best-effort timestamp parsing across the formats finance systems emit."""
    s = expr.cast(pl.Utf8).str.strip_chars()
    parsed = s.str.to_datetime(strict=False, time_unit="us")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y",
                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        parsed = parsed.fill_null(s.str.to_datetime(format=fmt, strict=False, time_unit="us"))
    return parsed


def _col(df: pl.DataFrame, mapping: dict[str, str], field: str) -> pl.Expr | None:
    src = mapping.get(field)
    if src is None or src not in df.columns:
        return None
    return pl.col(src)


def normalize_frame(
    df: pl.DataFrame,
    source_kind: SourceKind,
    source_name: str,
    mapping: dict[str, str] | None = None,
) -> pl.DataFrame:
    """Turn one raw dataframe into canonical rows."""
    mapping = detect_mapping(df.columns, mapping)
    # The original row travels with the record for the audit trail. Serialized
    # natively — a per-row json.dumps loop was 30x slower and dominated the
    # normalize stage at 1M records.
    if df.width == 0:
        # A source can legitimately be empty (no settlements yet today).
        df = pl.DataFrame({"raw": pl.Series([], dtype=pl.Utf8)})
    else:
        df = df.with_columns(
            pl.struct(pl.all()).struct.json_encode().alias("raw")
        )

    def text(field: str) -> pl.Expr:
        c = _col(df, mapping, field)
        base = pl.lit(None, dtype=pl.Utf8) if c is None else c.cast(pl.Utf8)
        return base.str.strip_chars().alias(field)

    amount_col = _col(df, mapping, "amount_minor")
    fee_col = _col(df, mapping, "fee_minor")
    ts_col = _col(df, mapping, "txn_ts")

    out = df.select(
        text("txn_id"),
        text("order_id"),
        text("reference_id"),
        text("merchant_id"),
        text("currency"),
        text("status"),
        (_to_minor(amount_col) if amount_col is not None else pl.lit(0, dtype=pl.Int64)).alias("amount_minor"),
        (_to_minor(fee_col) if fee_col is not None else pl.lit(0, dtype=pl.Int64)).alias("fee_minor"),
        (_parse_ts(ts_col) if ts_col is not None else pl.lit(None, dtype=pl.Datetime("us"))).alias("txn_ts"),
        pl.col("raw"),
    )

    status_lc = pl.col("status").str.to_lowercase().fill_null("")
    out = out.with_columns(
        # A negative amount is the other common way sources signal a refund.
        pl.when(status_lc.is_in(list(REFUND_STATUSES)) | (pl.col("amount_minor") < 0))
        .then(True).otherwise(False).alias("is_refund"),
        pl.col("currency").fill_null(settings.default_currency).str.to_uppercase().alias("currency"),
        pl.col("merchant_id").fill_null("UNKNOWN").alias("merchant_id"),
        # Reference IDs arrive as "PAY-ORD-98231-XYZ". The digits are the signal.
        pl.col("reference_id").fill_null("").str.replace_all(r"\D", "").alias("ref_digits"),
    )

    # Failed transactions are noise, not exceptions — a declined card was never
    # money. Dropping them here keeps the exception queue honest.
    out = out.filter(~status_lc.is_in(list(FAILED_STATUSES)))

    out = out.with_columns(
        pl.lit(source_kind.value).alias("source_kind"),
        pl.lit(source_name).alias("source_name"),
        pl.col("txn_ts").dt.date().alias("day_bucket"),
        pl.col("amount_minor").abs().alias("amount_minor"),
        pl.col("fee_minor").abs().alias("fee_minor"),
    )

    # Deterministic surrogate key: same input file always yields the same uids,
    # which is what makes a re-run idempotent.
    out = out.with_row_index("_rn").with_columns(
        (pl.lit(f"{source_kind.value[:3]}-") + pl.col("_rn").cast(pl.Utf8).str.zfill(10)).alias("record_uid")
    ).drop("_rn")

    return out.select(
        "record_uid", "source_kind", "source_name", "txn_id", "order_id",
        "reference_id", "ref_digits", "merchant_id", "amount_minor", "fee_minor",
        "currency", "txn_ts", "day_bucket", "status", "is_refund", "raw",
    )


def load_any(path: Path) -> pl.DataFrame:
    """Read CSV/Parquet/JSON without caring which one it is."""
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pl.read_parquet(path)
    if suffix in {".json", ".ndjson", ".jsonl"}:
        return pl.read_ndjson(path) if suffix != ".json" else pl.read_json(path)
    return pl.read_csv(path, infer_schema_length=10_000, try_parse_dates=False)
