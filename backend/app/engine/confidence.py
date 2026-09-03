"""Confidence scoring.

"AI confidence" is not a number you can defend to an auditor. This is: every
match carries a score assembled from named, additive evidence components, so
any row in the ledger can be traced back to *why* the engine believed it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings

#: Evidence weights. They sum to 1.00 when every signal fires.
WEIGHTS: dict[str, float] = {
    "exact_txn_id": 0.40,
    "exact_order_id": 0.25,
    "exact_amount": 0.20,
    "reference_digits": 0.05,
    "same_merchant": 0.05,
    "within_window": 0.05,
}


@dataclass(frozen=True)
class Band:
    name: str
    low: float
    high: float


def band_for(score: float) -> str:
    """Which lane a score routes into. These thresholds are the safety policy."""
    if score >= settings.auto_resolve_threshold:
        return "AUTO"
    if score >= settings.ai_investigate_threshold:
        return "AI"
    return "HUMAN"


def sql_score_expression(components: list[str], window_sec: int | None = None) -> str:
    """Render an additive SQL score from the components a rule can guarantee.

    Components that are *conditionally* true (amount matched, within window)
    are emitted as CASE expressions so the score reflects the actual row, not
    the rule's optimistic assumption.
    """
    parts: list[str] = []
    tol = settings.amount_tolerance_minor
    window_sec = window_sec or settings.time_window_hours * 3600

    for c in components:
        w = WEIGHTS[c]
        if c == "exact_amount":
            parts.append(f"CASE WHEN abs(l.amount_minor - r.amount_minor) <= {tol} THEN {w} ELSE 0 END")
        elif c == "same_merchant":
            parts.append(f"CASE WHEN l.merchant_id = r.merchant_id THEN {w} ELSE 0 END")
        elif c == "within_window":
            parts.append(
                "CASE WHEN l.txn_ts IS NOT NULL AND r.txn_ts IS NOT NULL "
                f"AND abs(date_diff('second', l.txn_ts, r.txn_ts)) <= {window_sec} THEN {w} ELSE 0 END"
            )
        elif c == "reference_digits":
            parts.append(
                "CASE WHEN length(l.ref_digits) > 3 AND l.ref_digits = r.ref_digits "
                f"THEN {w} ELSE 0 END"
            )
        else:
            # Unconditional: the rule's own join predicate already proved it.
            parts.append(str(w))
    return " + ".join(parts) if parts else "0"


def score_components(
    *,
    txn_id_match: bool,
    order_id_match: bool,
    amount_match: bool,
    reference_match: bool,
    merchant_match: bool,
    within_window: bool,
) -> tuple[float, list[str]]:
    """Python-side scorer, used by the AI validation path where we re-derive a
    score from the evidence the model claims rather than trusting its number."""
    fired = []
    if txn_id_match:
        fired.append("exact_txn_id")
    if order_id_match:
        fired.append("exact_order_id")
    if amount_match:
        fired.append("exact_amount")
    if reference_match:
        fired.append("reference_digits")
    if merchant_match:
        fired.append("same_merchant")
    if within_window:
        fired.append("within_window")
    return round(sum(WEIGHTS[c] for c in fired), 4), fired
