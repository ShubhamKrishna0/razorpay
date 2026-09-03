"""Vocabulary shared by the engine, the AI layer, and the API."""

from __future__ import annotations

from enum import Enum


class SourceKind(str, Enum):
    """Which leg of the three-way reconciliation a record belongs to."""

    ORDER = "ORDER"
    PAYMENT = "PAYMENT"
    SETTLEMENT = "SETTLEMENT"


class ExceptionType(str, Enum):
    """The exception state machine. `MATCHED` is the only terminal-clean state."""

    MATCHED = "MATCHED"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    OVERPAYMENT = "OVERPAYMENT"
    DUPLICATE = "DUPLICATE"
    MISSING_PAYMENT = "MISSING_PAYMENT"
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    ORPHAN_PAYMENT = "ORPHAN_PAYMENT"
    ORPHAN_SETTLEMENT = "ORPHAN_SETTLEMENT"
    TIMING_MISMATCH = "TIMING_MISMATCH"
    REFUND = "REFUND"
    FEE_VARIANCE = "FEE_VARIANCE"
    SETTLEMENT_SHORTFALL = "SETTLEMENT_SHORTFALL"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    MERCHANT_MISMATCH = "MERCHANT_MISMATCH"
    UNKNOWN = "UNKNOWN"


#: Exceptions the deterministic engine can close on its own, given the rules pass.
DETERMINISTICALLY_RESOLVABLE = {
    ExceptionType.FEE_VARIANCE,
    ExceptionType.TIMING_MISMATCH,
    ExceptionType.REFUND,
}

#: Exceptions worth spending an LLM call on. Everything else is either clean
#: or so obviously structural (missing record) that reasoning adds nothing.
AI_ELIGIBLE = {
    ExceptionType.AMOUNT_MISMATCH,
    ExceptionType.FEE_VARIANCE,
    ExceptionType.PARTIAL_MATCH,
    ExceptionType.PARTIAL_PAYMENT,
    ExceptionType.OVERPAYMENT,
    ExceptionType.SETTLEMENT_SHORTFALL,
    ExceptionType.ORPHAN_PAYMENT,
    ExceptionType.ORPHAN_SETTLEMENT,
    ExceptionType.MERCHANT_MISMATCH,
    ExceptionType.DUPLICATE,
    ExceptionType.UNKNOWN,
}


class Resolution(str, Enum):
    """Where a record ended up after the full pipeline."""

    AUTO_RESOLVED = "AUTO_RESOLVED"      # deterministic rules closed it
    AI_RESOLVED = "AI_RESOLVED"          # AI explained it, rules validated it
    HUMAN_REVIEW = "HUMAN_REVIEW"        # queued for a person
    HUMAN_RESOLVED = "HUMAN_RESOLVED"    # a person closed it
    UNRESOLVED = "UNRESOLVED"            # not yet processed


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    NORMALIZING = "NORMALIZING"
    MATCHING = "MATCHING"
    CLASSIFYING = "CLASSIFYING"
    AI_ANALYZING = "AI_ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MatchStage(str, Enum):
    """The cascade. Ordered cheapest/most-certain first."""

    L1_TXN_ID = "L1_TXN_ID"
    L2_REFERENCE_ID = "L2_REFERENCE_ID"
    L3_ORDER_ID_AMOUNT = "L3_ORDER_ID_AMOUNT"
    L4_ORDER_ID_WINDOW = "L4_ORDER_ID_WINDOW"
    L5_FUZZY_BLOCKED = "L5_FUZZY_BLOCKED"
    L6_AI = "L6_AI"
