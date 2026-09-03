"""The matching cascade, declared as data.

Each level is strictly cheaper and more certain than the one below it. A record
matched at L1 never reaches L5, so the expensive fuzzy stage only ever sees the
residue — which is the entire reason this scales past a few hundred thousand rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import settings
from app.core.enums import MatchStage


@dataclass(frozen=True)
class MatchRule:
    stage: MatchStage
    name: str
    #: SQL join predicate. `l` is the left side, `r` the right.
    join_sql: str
    #: Extra WHERE conditions applied after the join.
    where_sql: str = "TRUE"
    #: Confidence components this rule's predicate can attest to.
    components: list[str] = field(default_factory=list)
    #: When true, the pair is emitted even if amounts disagree — the classifier
    #: downstream turns that disagreement into a typed exception.
    allow_amount_divergence: bool = False
    #: Day offsets to sweep for blocked rules. The executor runs the rule once
    #: per offset with `{day_offset}` substituted, turning what would be a range
    #: join across an entire merchant's history into a handful of hash joins.
    day_offsets: tuple[int, ...] = (0,)


#: Fuzzy matching is for records whose identifiers are missing or garbled.
#: When BOTH sides carry a transaction id and an order id and every one of them
#: disagrees, a coincidence of merchant + amount + day is not evidence — it is
#: how a stray settlement gets glued to an unrelated payment. Block it.
ID_CONTRADICTION_GUARD = (
    "NOT ("
    "  l.txn_id IS NOT NULL AND l.txn_id <> ''"
    "  AND r.txn_id IS NOT NULL AND r.txn_id <> ''"
    "  AND l.txn_id <> r.txn_id"
    "  AND l.order_id IS NOT NULL AND l.order_id <> ''"
    "  AND r.order_id IS NOT NULL AND r.order_id <> ''"
    "  AND l.order_id <> r.order_id"
    ")"
)


def _window_sec() -> int:
    return settings.time_window_hours * 3600


def _settlement_window_sec() -> int:
    return settings.settlement_window_days * 86400


def order_payment_rules() -> list[MatchRule]:
    tol = settings.amount_tolerance_minor
    return [
        MatchRule(
            stage=MatchStage.L1_TXN_ID,
            name="exact_transaction_id",
            join_sql="l.txn_id = r.txn_id AND l.txn_id IS NOT NULL AND l.txn_id <> ''",
            components=["exact_txn_id", "exact_amount", "same_merchant", "within_window"],
            allow_amount_divergence=True,
        ),
        MatchRule(
            stage=MatchStage.L3_ORDER_ID_AMOUNT,
            name="order_id_and_amount",
            join_sql=(
                "l.order_id = r.order_id AND l.order_id IS NOT NULL AND l.order_id <> ''"
                f" AND abs(l.amount_minor - r.amount_minor) <= {tol}"
            ),
            components=["exact_order_id", "exact_amount", "same_merchant", "within_window"],
        ),
        MatchRule(
            stage=MatchStage.L4_ORDER_ID_WINDOW,
            name="order_id_within_window",
            join_sql="l.order_id = r.order_id AND l.order_id IS NOT NULL AND l.order_id <> ''",
            where_sql=(
                "(l.txn_ts IS NULL OR r.txn_ts IS NULL OR "
                f"abs(date_diff('second', l.txn_ts, r.txn_ts)) <= {_window_sec()})"
            ),
            components=["exact_order_id", "exact_amount", "same_merchant", "within_window"],
            allow_amount_divergence=True,
        ),
        MatchRule(
            stage=MatchStage.L2_REFERENCE_ID,
            name="reference_digits_and_amount",
            join_sql=(
                "l.ref_digits = r.ref_digits AND length(l.ref_digits) >= 5"
                f" AND abs(l.amount_minor - r.amount_minor) <= {tol}"
            ),
            components=["reference_digits", "exact_amount", "same_merchant", "within_window"],
        ),
        MatchRule(
            stage=MatchStage.L2_REFERENCE_ID,
            name="order_id_inside_reference",
            join_sql=(
                "length(l.order_id) >= 5 AND r.ref_digits <> '' "
                "AND contains(l.order_id, r.ref_digits)"
            ),
            where_sql=(
                "(l.txn_ts IS NULL OR r.txn_ts IS NULL OR "
                f"abs(date_diff('second', l.txn_ts, r.txn_ts)) <= {_window_sec()})"
            ),
            components=["reference_digits", "exact_amount", "same_merchant", "within_window"],
            allow_amount_divergence=True,
        ),
        MatchRule(
            stage=MatchStage.L5_FUZZY_BLOCKED,
            name="blocked_merchant_amount_day",
            # Blocking: only rows sharing merchant + currency + amount bucket +
            # day are ever compared. Without the day term a large merchant's
            # whole history is one block and the join goes quadratic; with it,
            # blocks stay small no matter how big the dataset gets.
            join_sql=(
                "l.merchant_id = r.merchant_id AND l.currency = r.currency"
                f" AND (l.amount_minor / {settings.amount_bucket_minor})::BIGINT"
                f"   = (r.amount_minor / {settings.amount_bucket_minor})::BIGINT"
                " AND l.day_bucket = r.day_bucket + {day_offset}"
            ),
            where_sql=(
                f"abs(l.amount_minor - r.amount_minor) <= {settings.amount_bucket_minor} "
                "AND l.txn_ts IS NOT NULL AND r.txn_ts IS NOT NULL "
                f"AND abs(date_diff('second', l.txn_ts, r.txn_ts)) <= {_window_sec()} "
                f"AND {ID_CONTRADICTION_GUARD}"
            ),
            components=["exact_amount", "same_merchant", "within_window"],
            allow_amount_divergence=True,
            day_offsets=(0, -1, 1),
        ),
    ]


def payment_settlement_rules() -> list[MatchRule]:
    """Settlements net out fees, so amount equality is a weak signal here and
    the time window is days rather than hours."""
    tol = settings.amount_tolerance_minor
    return [
        MatchRule(
            stage=MatchStage.L1_TXN_ID,
            name="exact_transaction_id",
            join_sql="l.txn_id = r.txn_id AND l.txn_id IS NOT NULL AND l.txn_id <> ''",
            components=["exact_txn_id", "exact_amount", "same_merchant"],
            allow_amount_divergence=True,
        ),
        MatchRule(
            stage=MatchStage.L2_REFERENCE_ID,
            name="reference_digits",
            join_sql="l.ref_digits = r.ref_digits AND length(l.ref_digits) >= 5",
            components=["reference_digits", "exact_amount", "same_merchant"],
            allow_amount_divergence=True,
        ),
        MatchRule(
            stage=MatchStage.L3_ORDER_ID_AMOUNT,
            name="order_id",
            join_sql="l.order_id = r.order_id AND l.order_id IS NOT NULL AND l.order_id <> ''",
            components=["exact_order_id", "exact_amount", "same_merchant"],
            allow_amount_divergence=True,
        ),
        MatchRule(
            stage=MatchStage.L5_FUZZY_BLOCKED,
            name="blocked_merchant_net_of_fee",
            # Settlements land 0-7 days after the payment, so the day sweep runs
            # forward only. Same principle: keep every block small.
            join_sql=(
                "l.merchant_id = r.merchant_id AND l.currency = r.currency"
                " AND r.day_bucket = l.day_bucket + {day_offset}"
            ),
            where_sql=(
                # Settlement should be gross minus a plausible fee: never more
                # than the payment, never less than payment minus 10%.
                "r.amount_minor <= l.amount_minor + " + str(tol) + " "
                "AND r.amount_minor >= l.amount_minor - (l.amount_minor / 10) "
                "AND l.txn_ts IS NOT NULL AND r.txn_ts IS NOT NULL "
                f"AND date_diff('second', l.txn_ts, r.txn_ts) BETWEEN 0 AND {_settlement_window_sec()} "
                f"AND {ID_CONTRADICTION_GUARD}"
            ),
            components=["same_merchant", "within_window"],
            allow_amount_divergence=True,
            day_offsets=tuple(range(0, settings.settlement_window_days + 1)),
        ),
    ]
