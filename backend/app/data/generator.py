"""Ground-truth dataset generator.

Random data proves nothing. This builds a clean three-way-consistent dataset,
then *injects specific, labelled anomalies* while retaining the truth. The
benchmark can therefore compute real precision and recall instead of eyeballing
a match rate — which is the difference between "our system found 97%" and "our
system found 97% and here is the file that proves it."
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

from app.config import settings
from app.core.enums import ExceptionType

MERCHANTS = [f"M{1000 + i}" for i in range(40)]
GATEWAYS = ["RAZORPAY", "PAYU", "CASHFREE", "STRIPE"]


#: Every anomaly the generator knows how to inject, in injection order.
ANOMALY_KINDS = (
    "amount_mismatch", "duplicate", "missing_payment", "missing_settlement",
    "timing_mismatch", "refund", "fee_variance", "partial_payment",
    "orphan_payment", "merchant_mismatch",
)


def _assign_kinds(
    n: int, mix: "AnomalyMix", rng: random.Random, guarantee_coverage: bool
) -> list[str | None]:
    """Decide which anomaly (if any) each record carries.

    The probabilistic pass runs first and is the only thing that happens on a
    large batch. On a small one those rates produce zero of most kinds, so a
    top-up pass forces one of each missing kind into a still-clean record. That
    keeps a 50-record demo exercising the whole state machine without touching
    the distribution of a 50,000-record run, where every kind already appears.
    """
    kinds: list[str | None] = [None] * n
    rates = mix.as_dict()

    for i in range(n):
        roll = rng.random()
        cursor = 0.0
        for kind in ANOMALY_KINDS:
            lo, cursor = cursor, cursor + rates[kind]
            if lo <= roll < cursor:
                kinds[i] = kind
                break

    if guarantee_coverage:
        present = {k for k in kinds if k is not None}
        missing = [k for k in ANOMALY_KINDS if k not in present]
        clean = [i for i, k in enumerate(kinds) if k is None]
        rng.shuffle(clean)
        for kind in missing:
            if not clean:
                break
            kinds[clean.pop()] = kind

    return kinds


@dataclass
class AnomalyMix:
    """Injection rates. They sum to well under 1.0 — most records stay clean,
    exactly as they do in production."""

    amount_mismatch: float = 0.020
    duplicate: float = 0.010
    missing_payment: float = 0.010
    missing_settlement: float = 0.005
    timing_mismatch: float = 0.005
    refund: float = 0.005
    fee_variance: float = 0.010
    partial_payment: float = 0.005
    orphan_payment: float = 0.003
    merchant_mismatch: float = 0.002

    def as_dict(self) -> dict[str, float]:
        return self.__dict__.copy()


@dataclass
class GeneratedDataset:
    dataset_id: str
    orders: pl.DataFrame
    payments: pl.DataFrame
    settlements: pl.DataFrame
    ground_truth: pl.DataFrame
    stats: dict = field(default_factory=dict)


def generate(
    n_orders: int,
    dataset_id: str,
    seed: int = 42,
    mix: AnomalyMix | None = None,
    start: datetime | None = None,
    guarantee_coverage: bool | None = None,
) -> GeneratedDataset:
    rng = random.Random(seed)
    mix = mix or AnomalyMix()
    # Small batches top up to full coverage by default; large ones never need it.
    if guarantee_coverage is None:
        guarantee_coverage = n_orders < 2_000
    start = start or datetime(2026, 8, 1, 0, 0, 0)
    scale = settings.amount_scale

    orders: list[dict] = []
    payments: list[dict] = []
    settlements: list[dict] = []
    truth: list[dict] = []
    orphan_truth: list[dict] = []
    kinds = _assign_kinds(n_orders, mix, rng, guarantee_coverage)

    for i in range(n_orders):
        oid = f"ORD{100000 + i}"
        txn = f"TXN{500000 + i}"
        merchant = rng.choice(MERCHANTS)
        gross = rng.choice([499, 899, 1250, 2500, 4999, 12500, 250, 75]) * scale
        ts = start + timedelta(seconds=rng.randint(0, 30 * 86400))
        fee = int(gross * settings.default_fee_bps / 10000)

        kind = kinds[i]
        label = ExceptionType.MATCHED.value

        orders.append({
            "order_id": oid, "txn_id": txn, "merchant_id": merchant,
            "amount": gross / scale, "currency": "INR",
            "timestamp": ts.isoformat(sep=" "), "status": "PLACED",
            "reference": f"ORD-{100000 + i}",
        })

        pay_amount = gross
        pay_ts = ts + timedelta(minutes=rng.randint(1, 90))
        pay_merchant = merchant
        pay_status = "CAPTURED"
        emit_payment = True
        emit_settlement = True
        settle_amount = gross - fee
        settle_ts = pay_ts + timedelta(days=rng.randint(1, 3))
        emit_duplicate = False
        payment_order_id = oid

        if kind == "amount_mismatch":
            # Label by direction: the engine distinguishes underpayment from
            # overpayment, so the ground truth must too or the comparison is unfair.
            # The shortfall is bounded to at most half the order — an unbounded
            # delta on a small order flips the payment negative, which the
            # normalizer (correctly) reads as a refund, corrupting the truth.
            sign = rng.choice([-1, 1])
            if sign < 0:
                delta = -rng.randint(5, max(6, min(400, gross // (2 * scale)))) * scale
            else:
                delta = rng.randint(5, 400) * scale
            label = (ExceptionType.OVERPAYMENT.value if delta > 0
                     else ExceptionType.PARTIAL_PAYMENT.value)
            pay_amount = gross + delta
            settle_amount = pay_amount - int(pay_amount * settings.default_fee_bps / 10000)
        elif kind == "duplicate":
            label = ExceptionType.DUPLICATE.value
            emit_duplicate = True
        elif kind == "missing_payment":
            label = ExceptionType.MISSING_PAYMENT.value
            emit_payment = False
            emit_settlement = False
        elif kind == "missing_settlement":
            label = ExceptionType.MISSING_SETTLEMENT.value
            emit_settlement = False
        elif kind == "timing_mismatch":
            label = ExceptionType.TIMING_MISMATCH.value
            pay_ts = ts + timedelta(days=rng.randint(4, 9))
            settle_ts = pay_ts + timedelta(days=rng.randint(9, 20))
        elif kind == "refund":
            label = ExceptionType.REFUND.value
            pay_status = "REFUNDED"
            emit_settlement = False
        elif kind == "fee_variance":
            # Fee higher than the configured rate — the classic "why is the
            # settlement short?" case that should resolve, not escalate.
            label = ExceptionType.FEE_VARIANCE.value
            # Guarantee the variance clears the configured tolerance, or the
            # injection is undetectable by policy (worst on small orders, where
            # 30bps of Rs 75 rounds to nothing) and the truth label is a lie.
            base_fee = int(gross * settings.default_fee_bps / 10000)
            extra = max(
                int(gross * rng.randint(30, 120) / 10000),
                settings.fee_tolerance_minor * 3,
            )
            fee = base_fee + extra
            settle_amount = gross - fee
        elif kind == "partial_payment":
            label = ExceptionType.PARTIAL_PAYMENT.value
            pay_amount = int(gross * rng.uniform(0.35, 0.75))
            settle_amount = pay_amount - int(pay_amount * settings.default_fee_bps / 10000)
        elif kind == "orphan_payment":
            # Break the link: the payment carries ids that match no order. That
            # produces TWO true findings — the order lost its payment, and a
            # payment exists with no order — so we assert both.
            label = ExceptionType.MISSING_PAYMENT.value
            txn = f"TXNX{900000 + i}"
            payment_order_id = f"ORDX{900000 + i}"
            # Also change merchant and amount, otherwise the fuzzy stage
            # legitimately re-pairs them via the blocking key and the case is
            # no longer an orphan at all.
            pay_merchant = f"MX{9000 + i % 50}"
            pay_amount = gross + rng.randint(1, 20) * 7 * scale
            orphan_truth.append({
                "order_id": payment_order_id, "txn_id": txn,
                "expected_label": ExceptionType.ORPHAN_PAYMENT.value,
                "expected_payment": True, "expected_settlement": True,
            })
        elif kind == "merchant_mismatch":
            label = ExceptionType.MERCHANT_MISMATCH.value
            pay_merchant = rng.choice([m for m in MERCHANTS if m != merchant])

        if emit_payment:
            payments.append({
                "transaction_id": txn, "order_id": payment_order_id,
                "merchant_id": pay_merchant, "amount": pay_amount / scale,
                "fee": fee / scale, "currency": "INR",
                "payment_date": pay_ts.isoformat(sep=" "), "status": pay_status,
                "narration": f"PAY-{payment_order_id}-{rng.choice(GATEWAYS)}",
            })
            if emit_duplicate:
                # Same transaction id, submitted twice. Real, and expensive.
                payments.append({
                    "transaction_id": txn, "order_id": payment_order_id,
                    "merchant_id": pay_merchant, "amount": pay_amount / scale,
                    "fee": fee / scale, "currency": "INR",
                    "payment_date": (pay_ts + timedelta(seconds=90)).isoformat(sep=" "),
                    "status": pay_status,
                    "narration": f"PAY-{payment_order_id}-{rng.choice(GATEWAYS)}",
                })

        if emit_payment and emit_settlement:
            settlements.append({
                "utr": txn, "order_id": payment_order_id, "merchant_id": pay_merchant,
                "settlement_amount": settle_amount / scale, "commission": fee / scale,
                "currency": "INR", "settlement_date": settle_ts.isoformat(sep=" "),
                "status": "SETTLED",
                "settlement_reference": f"STL-{payment_order_id}",
            })

        truth.append({
            "order_id": oid, "txn_id": txn, "expected_label": label,
            "expected_payment": emit_payment, "expected_settlement": emit_settlement,
        })

    truth.extend(orphan_truth)

    # A few settlements with no payment behind them at all.
    for j in range(max(1, int(n_orders * 0.002))):
        settlements.append({
            "utr": f"TXNORPH{j}", "order_id": f"ORDORPH{j}",
            "merchant_id": rng.choice(MERCHANTS),
            "settlement_amount": rng.randint(100, 5000),
            "commission": 0, "currency": "INR",
            "settlement_date": (start + timedelta(days=rng.randint(1, 30))).isoformat(sep=" "),
            "status": "SETTLED", "settlement_reference": f"STL-ORPH-{j}",
        })
        truth.append({
            "order_id": f"ORDORPH{j}", "txn_id": f"TXNORPH{j}",
            "expected_label": ExceptionType.ORPHAN_SETTLEMENT.value,
            "expected_payment": False, "expected_settlement": True,
        })

    ds = GeneratedDataset(
        dataset_id=dataset_id,
        orders=pl.DataFrame(orders),
        payments=pl.DataFrame(payments),
        settlements=pl.DataFrame(settlements),
        ground_truth=pl.DataFrame(truth),
        stats={
            "orders": len(orders), "payments": len(payments),
            "settlements": len(settlements), "seed": seed,
            "anomaly_mix": mix.as_dict(),
            "guarantee_coverage": guarantee_coverage,
            "injected": {
                k: sum(1 for x in kinds if x == k) for k in ANOMALY_KINDS
            },
        },
    )
    return ds


def persist(ds: GeneratedDataset) -> Path:
    root = settings.dataset_dir(ds.dataset_id)
    root.mkdir(parents=True, exist_ok=True)
    ds.orders.write_parquet(root / "orders.parquet")
    ds.payments.write_parquet(root / "payments.parquet")
    ds.settlements.write_parquet(root / "settlements.parquet")
    ds.ground_truth.write_parquet(root / "ground_truth.parquet")
    return root
