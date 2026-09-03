"""Accuracy metrics against ground truth.

Match rate alone is a vanity metric — a system that matches everything to
anything scores 100%. Precision and recall are what tell you whether the
matches are real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

from app.core.enums import ExceptionType

#: When one order yields several cases, report the *cause*, not the symptom.
#: A duplicate payment produces a missing-settlement side effect; the finding a
#: controller needs is "duplicate", so causes rank first.
SEVERITY_ORDER = [
    ExceptionType.DUPLICATE.value,
    ExceptionType.ORPHAN_PAYMENT.value,
    ExceptionType.ORPHAN_SETTLEMENT.value,
    ExceptionType.MISSING_PAYMENT.value,
    ExceptionType.MERCHANT_MISMATCH.value,
    ExceptionType.CURRENCY_MISMATCH.value,
    ExceptionType.PARTIAL_PAYMENT.value,
    ExceptionType.OVERPAYMENT.value,
    ExceptionType.AMOUNT_MISMATCH.value,
    ExceptionType.SETTLEMENT_SHORTFALL.value,
    ExceptionType.REFUND.value,
    ExceptionType.FEE_VARIANCE.value,
    ExceptionType.MISSING_SETTLEMENT.value,
    ExceptionType.TIMING_MISMATCH.value,
    ExceptionType.UNKNOWN.value,
    ExceptionType.MATCHED.value,
]
_RANK = {label: i for i, label in enumerate(SEVERITY_ORDER)}


@dataclass
class AccuracyReport:
    total: int = 0
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    true_negative: int = 0
    label_correct: int = 0
    per_label: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def precision(self) -> float:
        d = self.true_positive + self.false_positive
        return self.true_positive / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.true_positive + self.false_negative
        return self.true_positive / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def label_accuracy(self) -> float:
        return self.label_correct / self.total if self.total else 0.0

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "true_negative": self.true_negative,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "label_accuracy": round(self.label_accuracy, 4),
            "per_label": self.per_label,
        }


def evaluate(predictions: pl.DataFrame, ground_truth: pl.DataFrame) -> AccuracyReport:
    """Compare predicted exception labels to injected truth.

    "Positive" here means *the engine declared this record clean*. That framing
    makes a false positive a break we wrongly closed — the expensive error in a
    finance system — so precision measures exactly the thing that matters.
    """
    matched_label = ExceptionType.MATCHED.value

    # One order can produce several cases — a clean payment plus a duplicate,
    # for example. The question the benchmark asks is "did the engine flag this
    # order at all", so a non-MATCHED case anywhere wins over a MATCHED one.
    pred = (
        predictions.select([
            pl.col("order_id").cast(pl.Utf8),
            pl.col("exception_type").cast(pl.Utf8).alias("predicted_label"),
        ])
        .filter(pl.col("order_id").is_not_null())
        .with_columns(
            pl.col("predicted_label")
            .replace_strict(_RANK, default=len(_RANK))
            .alias("_rank")
        )
        .sort("_rank")
        .unique(subset=["order_id"], keep="first")
        .drop("_rank")
    )

    truth = ground_truth.select([
        pl.col("order_id").cast(pl.Utf8),
        pl.col("expected_label").cast(pl.Utf8),
    ]).unique(subset=["order_id"], keep="first")

    joined = truth.join(pred, on="order_id", how="left").with_columns(
        pl.col("predicted_label").fill_null("MISSING_FROM_OUTPUT")
    )

    report = AccuracyReport(total=joined.height)
    pred_clean = pl.col("predicted_label") == matched_label
    true_clean = pl.col("expected_label") == matched_label

    report.true_positive = joined.filter(pred_clean & true_clean).height
    report.false_positive = joined.filter(pred_clean & ~true_clean).height
    report.false_negative = joined.filter(~pred_clean & true_clean).height
    report.true_negative = joined.filter(~pred_clean & ~true_clean).height
    report.label_correct = joined.filter(
        pl.col("predicted_label") == pl.col("expected_label")
    ).height

    for row in joined.group_by(["expected_label", "predicted_label"]).len().iter_rows(named=True):
        exp = row["expected_label"]
        bucket = report.per_label.setdefault(exp, {})
        bucket[row["predicted_label"]] = int(row["len"])

    return report
