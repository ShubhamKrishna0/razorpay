"""Exception classification.

MATCHED / NOT_MATCHED is useless to a finance team. This turns every unmatched
record into a *typed* exception with a computed delta, which is what makes the
output explainable and what lets the AI layer reason about a narrow question
instead of an open one.
"""

from __future__ import annotations

import duckdb

from app.config import settings
from app.core.enums import AI_ELIGIBLE, ExceptionType, Resolution

_AI_LIST = ", ".join(f"'{e.value}'" for e in AI_ELIGIBLE)


def build_reconciliation(
    con: duckdb.DuckDBPyConnection,
    orders: str = "orders",
    payments: str = "payments",
    settlements: str = "settlements",
    op_links: str = "op_links",
    ps_links: str = "ps_links",
    dupes: str = "payment_dupes",
    out: str = "recon",
) -> None:
    """Join the three legs into one case per unit of economic activity."""
    tol = settings.amount_tolerance_minor
    fee_tol = settings.fee_tolerance_minor
    fee_bps = settings.default_fee_bps
    window_sec = settings.time_window_hours * 3600
    settle_sec = settings.settlement_window_days * 86400

    con.execute(f"""
    CREATE OR REPLACE TABLE {out} AS
    WITH order_leg AS (
        SELECT
            o.record_uid AS order_uid, p.record_uid AS payment_uid,
            o.order_id, o.merchant_id, o.currency,
            o.amount_minor AS order_amount_minor,
            p.amount_minor AS payment_amount_minor,
            o.txn_ts AS order_ts, p.txn_ts AS payment_ts,
            p.is_refund AS payment_is_refund, p.fee_minor AS payment_fee_minor,
            p.merchant_id AS payment_merchant_id, p.currency AS payment_currency,
            opl.confidence AS op_confidence, opl.stage AS op_stage,
            opl.rule AS op_rule, opl.time_delta_sec AS op_time_delta_sec
        FROM {orders} o
        LEFT JOIN {op_links} opl ON opl.left_uid = o.record_uid
        LEFT JOIN {payments} p ON p.record_uid = opl.right_uid
    ),
    -- Payments the cascade never tied to an order: real money with no invoice.
    orphan_payments AS (
        SELECT
            NULL AS order_uid, p.record_uid AS payment_uid,
            p.order_id, p.merchant_id, p.currency,
            NULL::BIGINT AS order_amount_minor,
            p.amount_minor AS payment_amount_minor,
            NULL::TIMESTAMP AS order_ts, p.txn_ts AS payment_ts,
            p.is_refund AS payment_is_refund, p.fee_minor AS payment_fee_minor,
            p.merchant_id AS payment_merchant_id, p.currency AS payment_currency,
            NULL::DOUBLE AS op_confidence, NULL AS op_stage, NULL AS op_rule,
            NULL::BIGINT AS op_time_delta_sec
        FROM {payments} p
        WHERE NOT EXISTS (SELECT 1 FROM {op_links} m WHERE m.right_uid = p.record_uid)
    ),
    combined AS (
        SELECT * FROM order_leg UNION ALL SELECT * FROM orphan_payments
    ),
    with_settlement AS (
        SELECT c.*,
            s.record_uid AS settlement_uid,
            s.amount_minor AS settlement_amount_minor,
            s.fee_minor AS settlement_fee_minor,
            s.txn_ts AS settlement_ts,
            psl.confidence AS ps_confidence,
            psl.time_delta_sec AS ps_time_delta_sec
        FROM combined c
        LEFT JOIN {ps_links} psl ON psl.left_uid = c.payment_uid
        LEFT JOIN {settlements} s ON s.record_uid = psl.right_uid
    ),
    -- Settlements with no payment behind them: money arrived from nowhere.
    orphan_settlements AS (
        SELECT
            NULL AS order_uid, NULL AS payment_uid, s.order_id, s.merchant_id, s.currency,
            NULL::BIGINT AS order_amount_minor, NULL::BIGINT AS payment_amount_minor,
            NULL::TIMESTAMP AS order_ts, NULL::TIMESTAMP AS payment_ts,
            FALSE AS payment_is_refund, 0::BIGINT AS payment_fee_minor,
            s.merchant_id AS payment_merchant_id, s.currency AS payment_currency,
            NULL::DOUBLE AS op_confidence, NULL AS op_stage, NULL AS op_rule,
            NULL::BIGINT AS op_time_delta_sec,
            s.record_uid AS settlement_uid, s.amount_minor AS settlement_amount_minor,
            s.fee_minor AS settlement_fee_minor, s.txn_ts AS settlement_ts,
            NULL::DOUBLE AS ps_confidence, NULL::BIGINT AS ps_time_delta_sec
        FROM {settlements} s
        WHERE NOT EXISTS (SELECT 1 FROM {ps_links} m WHERE m.right_uid = s.record_uid)
    ),
    all_cases AS (
        SELECT * FROM with_settlement UNION ALL SELECT * FROM orphan_settlements
    ),
    enriched AS (
        SELECT a.*,
            (d.record_uid IS NOT NULL) AS is_duplicate,
            d.dupe_reason,
            -- Two different fees, and the distinction is the whole point:
            -- `expected_fee` is what the gateway SAYS it charged; `configured_fee`
            -- is what our contract says it should have charged. A settlement that
            -- matches the declared fee is arithmetic, not a break. A declared fee
            -- that disagrees with the contract is the break.
            COALESCE(
                NULLIF(a.settlement_fee_minor, 0),
                NULLIF(a.payment_fee_minor, 0),
                (COALESCE(a.payment_amount_minor, 0) * {fee_bps}) / 10000
            )::BIGINT AS expected_fee_minor,
            ((COALESCE(a.payment_amount_minor, 0) * {fee_bps}) / 10000)::BIGINT
                AS configured_fee_minor,
            (COALESCE(a.payment_amount_minor, 0) - COALESCE(a.order_amount_minor, 0)) AS payment_delta_minor,
            (COALESCE(a.payment_amount_minor, 0) - COALESCE(a.settlement_amount_minor, 0)) AS settlement_delta_minor
        FROM all_cases a
        LEFT JOIN {dupes} d ON d.record_uid = a.payment_uid
    )
    SELECT
        COALESCE(order_uid, payment_uid, settlement_uid) AS case_id,
        *,
        CASE
            WHEN is_duplicate THEN '{ExceptionType.DUPLICATE.value}'
            WHEN payment_is_refund THEN '{ExceptionType.REFUND.value}'
            WHEN order_uid IS NULL AND payment_uid IS NULL THEN '{ExceptionType.ORPHAN_SETTLEMENT.value}'
            WHEN order_uid IS NULL THEN '{ExceptionType.ORPHAN_PAYMENT.value}'
            WHEN payment_uid IS NULL THEN '{ExceptionType.MISSING_PAYMENT.value}'
            WHEN payment_currency IS NOT NULL AND currency IS NOT NULL
                 AND payment_currency <> currency THEN '{ExceptionType.CURRENCY_MISMATCH.value}'
            WHEN payment_merchant_id IS NOT NULL AND merchant_id IS NOT NULL
                 AND payment_merchant_id <> merchant_id THEN '{ExceptionType.MERCHANT_MISMATCH.value}'
            WHEN payment_delta_minor < -{tol} THEN '{ExceptionType.PARTIAL_PAYMENT.value}'
            WHEN payment_delta_minor > {tol} THEN '{ExceptionType.OVERPAYMENT.value}'
            WHEN settlement_uid IS NULL THEN '{ExceptionType.MISSING_SETTLEMENT.value}'
            -- Money is short by more than the declared fee explains: real gap.
            WHEN settlement_delta_minor > {tol}
                 AND abs(settlement_delta_minor - expected_fee_minor) > {fee_tol}
                 THEN '{ExceptionType.SETTLEMENT_SHORTFALL.value}'
            -- Settled MORE than was paid. Rare, and always worth a human.
            WHEN settlement_delta_minor < -{tol} THEN '{ExceptionType.AMOUNT_MISMATCH.value}'
            -- Gap equals the declared fee, but the declared fee is not the rate
            -- we contracted for. Explainable, but someone should know.
            WHEN abs(expected_fee_minor - configured_fee_minor) > {fee_tol}
                 THEN '{ExceptionType.FEE_VARIANCE.value}'
            WHEN op_time_delta_sec IS NOT NULL AND abs(op_time_delta_sec) > {window_sec}
                 THEN '{ExceptionType.TIMING_MISMATCH.value}'
            WHEN ps_time_delta_sec IS NOT NULL AND ps_time_delta_sec > {settle_sec}
                 THEN '{ExceptionType.TIMING_MISMATCH.value}'
            ELSE '{ExceptionType.MATCHED.value}'
        END AS exception_type,
        COALESCE(op_confidence, ps_confidence, 0.0) AS confidence
    FROM enriched
    """)

    _assign_resolution(con, out)


def _assign_resolution(con: duckdb.DuckDBPyConnection, table: str) -> None:
    """Route each case into auto-resolve, AI investigation, or the human queue.

    The AI never writes to the ledger directly — it can only move a case out of
    the queue *after* a deterministic rule has agreed with it (see ai/analyzer).
    """
    auto = settings.auto_resolve_threshold
    fee_tol = settings.fee_tolerance_minor
    settle_sec = settings.settlement_window_days * 86400

    con.execute(f"""
    ALTER TABLE {table} ADD COLUMN IF NOT EXISTS resolution VARCHAR;
    """)
    con.execute(f"""
    UPDATE {table} SET resolution = CASE
        WHEN exception_type = '{ExceptionType.MATCHED.value}'
            THEN '{Resolution.AUTO_RESOLVED.value}'
        -- Auto-resolvable: the difference is fully explained by a known rule.
        WHEN exception_type = '{ExceptionType.REFUND.value}'
            THEN '{Resolution.AUTO_RESOLVED.value}'
        WHEN exception_type = '{ExceptionType.TIMING_MISMATCH.value}'
             AND coalesce(ps_time_delta_sec, 0) <= {settle_sec * 2}
             AND confidence >= {auto}
            THEN '{Resolution.AUTO_RESOLVED.value}'
        -- Worth an LLM call: ambiguous enough that reasoning adds information.
        WHEN exception_type IN ({_AI_LIST})
            THEN '{Resolution.UNRESOLVED.value}'
        ELSE '{Resolution.HUMAN_REVIEW.value}'
    END
    """)


def summarize(con: duckdb.DuckDBPyConnection, table: str = "recon") -> dict:
    row = con.execute(f"""
        SELECT
            count(*) AS total_cases,
            sum(CASE WHEN exception_type = 'MATCHED' THEN 1 ELSE 0 END) AS matched,
            sum(CASE WHEN exception_type <> 'MATCHED' THEN 1 ELSE 0 END) AS exceptions,
            sum(CASE WHEN resolution = 'AUTO_RESOLVED' THEN 1 ELSE 0 END) AS auto_resolved,
            sum(CASE WHEN resolution = 'UNRESOLVED' THEN 1 ELSE 0 END) AS pending_ai,
            sum(CASE WHEN resolution = 'HUMAN_REVIEW' THEN 1 ELSE 0 END) AS human_review,
            coalesce(sum(order_amount_minor), 0) AS gross_order_minor,
            coalesce(sum(payment_amount_minor), 0) AS gross_payment_minor,
            coalesce(sum(settlement_amount_minor), 0) AS gross_settlement_minor
        FROM {table}
    """).fetchone()
    keys = ["total_cases", "matched", "exceptions", "auto_resolved", "pending_ai",
            "human_review", "gross_order_minor", "gross_payment_minor",
            "gross_settlement_minor"]
    return {k: int(v or 0) for k, v in zip(keys, row)}


def breakdown(con: duckdb.DuckDBPyConnection, table: str = "recon") -> list[dict]:
    rows = con.execute(f"""
        SELECT exception_type, resolution, count(*) AS n,
               coalesce(sum(abs(coalesce(payment_delta_minor, 0)
                              + coalesce(settlement_delta_minor, 0))), 0) AS impact_minor
        FROM {table}
        GROUP BY 1, 2 ORDER BY n DESC
    """).fetchall()
    return [
        {"exception_type": r[0], "resolution": r[1], "count": int(r[2]),
         "impact_minor": int(r[3])}
        for r in rows
    ]
