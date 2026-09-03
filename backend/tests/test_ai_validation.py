"""The AI is a recommender, not a writer.

These tests pin the property the whole safety story rests on: a confident model
verdict cannot close a case unless the arithmetic independently agrees.
"""

from __future__ import annotations

import pytest

from app.ai.analyzer import ExceptionAnalyzer, validate_verdict
from app.ai.cache import fingerprint
from app.ai.schemas import ExceptionVerdict
from app.core.enums import ExceptionType, Resolution


def _verdict(cls, resolution="RESOLVED", confidence=0.99):
    return ExceptionVerdict(
        case_id="C1", classification=cls, resolution=resolution,
        confidence=confidence, explanation="test", evidence=[],
    )


def test_fee_variance_closes_when_arithmetic_agrees():
    case = {"settlement_delta_minor": 7500, "expected_fee_minor": 7500}
    res, _ = validate_verdict(case, _verdict(ExceptionType.FEE_VARIANCE))
    assert res is Resolution.AI_RESOLVED


def test_confident_but_wrong_fee_verdict_is_rejected():
    """The model says 'just the fee' at 0.99. It is short by ₹265 more."""
    case = {"settlement_delta_minor": 34000, "expected_fee_minor": 7500}
    res, reason = validate_verdict(case, _verdict(ExceptionType.FEE_VARIANCE))
    assert res is Resolution.HUMAN_REVIEW
    assert "unexplained" in reason


def test_low_confidence_never_auto_closes():
    case = {"settlement_delta_minor": 7500, "expected_fee_minor": 7500}
    res, reason = validate_verdict(case, _verdict(ExceptionType.FEE_VARIANCE, confidence=0.90))
    assert res is Resolution.HUMAN_REVIEW
    assert "threshold" in reason


def test_model_deferral_is_honoured():
    case = {"settlement_delta_minor": 7500, "expected_fee_minor": 7500}
    res, _ = validate_verdict(case, _verdict(ExceptionType.FEE_VARIANCE, resolution="NEEDS_HUMAN"))
    assert res is Resolution.HUMAN_REVIEW


@pytest.mark.parametrize("cls", [
    ExceptionType.SETTLEMENT_SHORTFALL,
    ExceptionType.PARTIAL_PAYMENT,
    ExceptionType.ORPHAN_PAYMENT,
    ExceptionType.MISSING_PAYMENT,
])
def test_unexplained_money_is_never_auto_closed(cls):
    """No explanation makes missing money safe to close automatically."""
    case = {"settlement_delta_minor": 0, "expected_fee_minor": 0, "payment_delta_minor": 0}
    res, reason = validate_verdict(case, _verdict(cls))
    assert res is Resolution.HUMAN_REVIEW
    assert "policy" in reason


def test_duplicate_claim_requires_engine_corroboration():
    case = {"is_duplicate": False}
    res, reason = validate_verdict(case, _verdict(ExceptionType.DUPLICATE))
    assert res is Resolution.HUMAN_REVIEW
    assert "no duplicate key" in reason

    case = {"is_duplicate": True}
    res, _ = validate_verdict(case, _verdict(ExceptionType.DUPLICATE))
    assert res is Resolution.AI_RESOLVED


def test_matched_claim_requires_amounts_to_agree():
    res, _ = validate_verdict({"payment_delta_minor": 50000}, _verdict(ExceptionType.MATCHED))
    assert res is Resolution.HUMAN_REVIEW
    res, _ = validate_verdict({"payment_delta_minor": 0}, _verdict(ExceptionType.MATCHED))
    assert res is Resolution.AI_RESOLVED


def test_fingerprint_ignores_identifiers_but_not_amounts():
    """Structurally identical breaks share a cache entry; different money does not."""
    a = {"case_id": "A", "exception_type": "FEE_VARIANCE", "settlement_delta_minor": 100}
    b = {"case_id": "B", "exception_type": "FEE_VARIANCE", "settlement_delta_minor": 100}
    c = {"case_id": "C", "exception_type": "FEE_VARIANCE", "settlement_delta_minor": 999}
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint(c)


@pytest.mark.asyncio_compatible
def test_unconfigured_ai_routes_everything_to_humans():
    """Must hold regardless of whether a key happens to be in the developer's
    .env, so the provider is explicitly torn down rather than assumed absent."""
    import asyncio

    from app.ai import client as client_mod
    from app.config import settings

    saved = (settings.ai_enabled, settings.anthropic_api_key, settings.gemini_api_key)
    settings.ai_enabled = False
    settings.anthropic_api_key = None
    settings.gemini_api_key = None
    client_mod.reset_ai_client()
    try:
        rows = [{"case_id": "C1", "exception_type": "AMOUNT_MISMATCH"}]
        result = asyncio.run(ExceptionAnalyzer().analyze(rows))
    finally:
        (settings.ai_enabled, settings.anthropic_api_key,
         settings.gemini_api_key) = saved
        client_mod.reset_ai_client()

    verdict = result.verdicts["C1"]
    # Degradation must never look like a resolution.
    assert verdict["resolution"] == Resolution.HUMAN_REVIEW.value
    assert verdict["ai_confidence"] == 0.0


def test_matched_claim_must_also_explain_the_settlement_side():
    """Gate hole found during live testing: a MATCHED verdict used to be
    validated on the payment side only, so money withheld beyond the declared
    fee could be closed as 'matched'. Both sides must reconcile."""
    ok = {"payment_delta_minor": 0, "has_settlement": True,
          "settlement_delta_minor": 7500, "expected_fee_minor": 7500}
    res, _ = validate_verdict(ok, _verdict(ExceptionType.MATCHED))
    assert res is Resolution.AI_RESOLVED

    short = {"payment_delta_minor": 0, "has_settlement": True,
             "settlement_delta_minor": 34000, "expected_fee_minor": 7500}
    res, reason = validate_verdict(short, _verdict(ExceptionType.MATCHED))
    assert res is Resolution.HUMAN_REVIEW
    assert "unexplained" in reason
