"""The canonical transaction shape.

Every source file — bank statement, gateway dump, settlement report — is
normalized into this one schema. Everything downstream of normalization is
source-agnostic, which is what makes adding a fourth or fifth source a config
change rather than an engine change.
"""

from __future__ import annotations

CANONICAL_COLUMNS: dict[str, str] = {
    "record_uid": "VARCHAR",       # unique within (run, source_kind)
    "source_kind": "VARCHAR",      # ORDER | PAYMENT | SETTLEMENT
    "source_name": "VARCHAR",      # which file/system it came from
    "txn_id": "VARCHAR",           # gateway/bank transaction id
    "order_id": "VARCHAR",         # merchant order id
    "reference_id": "VARCHAR",     # free-text reference, often dirty
    "ref_digits": "VARCHAR",       # digits extracted from reference_id
    "merchant_id": "VARCHAR",
    "amount_minor": "BIGINT",      # integer minor units. never a float.
    "fee_minor": "BIGINT",         # known/declared fee, 0 when absent
    "currency": "VARCHAR",
    "txn_ts": "TIMESTAMP",
    "day_bucket": "DATE",
    "status": "VARCHAR",           # CAPTURED | REFUNDED | FAILED | ...
    "is_refund": "BOOLEAN",
    "raw": "VARCHAR",              # original row as JSON, for the audit trail
}

#: Column aliases we auto-detect during ingestion. Lowercased, non-alphanumeric
#: stripped. Extend this rather than writing a bespoke normalizer per source.
COLUMN_ALIASES: dict[str, list[str]] = {
    "txn_id": [
        "txnid", "transactionid", "txn", "paymentid", "utr", "rrn",
        "gatewaytxnid", "transactionreference", "bankreferenceno",
    ],
    "order_id": [
        "orderid", "order", "orderno", "ordernumber", "invoiceid",
        "invoiceno", "merchantorderid", "externalorderid",
    ],
    "reference_id": [
        "referenceid", "reference", "ref", "refno", "narration",
        "description", "remarks", "particulars", "settlementreference",
    ],
    "merchant_id": [
        "merchantid", "merchant", "sellerid", "storeid", "vendorid", "mid",
    ],
    "amount_minor": [
        "amount", "amt", "grossamount", "orderamount", "paymentamount",
        "settlementamount", "netamount", "value", "credit", "transactionamount",
    ],
    "fee_minor": [
        "fee", "fees", "commission", "charges", "gatewayfee", "mdr",
        "processingfee", "deduction",
    ],
    "currency": ["currency", "curr", "ccy", "currencycode"],
    "txn_ts": [
        "timestamp", "datetime", "date", "txndate", "transactiondate",
        "createdat", "paymentdate", "settlementdate", "valuedate", "time",
    ],
    "status": ["status", "state", "txnstatus", "paymentstatus"],
}

#: Values in a status column that mean "this money went back to the customer".
REFUND_STATUSES = {"refund", "refunded", "reversal", "reversed", "chargeback"}
FAILED_STATUSES = {"failed", "failure", "declined", "cancelled", "canceled", "void"}


def canonical_ddl(table: str) -> str:
    cols = ",\n  ".join(f"{name} {dtype}" for name, dtype in CANONICAL_COLUMNS.items())
    return f"CREATE OR REPLACE TABLE {table} (\n  {cols}\n)"
