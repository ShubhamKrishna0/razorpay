"""The AI batch path, exercised against a stub client.

Without this, everything between `analyze()` and the model is untested until a
real API key is present — which is exactly the code you do not want discovering
its bugs during a demo.
"""

from __future__ import annotations

import asyncio

import pytest

from app.ai.analyzer import ExceptionAnalyzer
from app.ai.cache import VerdictCache
from app.ai.client import AIRefusal, Usage
from app.ai.schemas import BatchVerdict, ExceptionVerdict
from app.core.enums import ExceptionType, Resolution


class StubClient:
    """Stands in for AIClient. Records calls and returns scripted verdicts."""

    available = True

    def __init__(self, responder) -> None:
        self.responder = responder
        self.usage = Usage()
        self.calls: list[str] = []

    async def structured(self, *, system, user, output_model, max_retries=2):
        self.calls.append(user)
        self.usage.calls += 1
        return self.responder(user)


def _cases(n: int) -> list[dict]:
    return [
        {
            "case_id": f"C{i}",
            "exception_type": ExceptionType.FEE_VARIANCE.value,
            "settlement_delta_minor": 7500,
            "expected_fee_minor": 7500,
            "payment_delta_minor": 0,
            "order_uid": "O", "payment_uid": "P", "settlement_uid": "S",
        }
        for i in range(n)
    ]


def _all_resolved(user: str) -> BatchVerdict:
    import json, re

    ids = re.findall(r'"case_id": "([^"]+)"', user)
    assert ids, f"no case ids found in prompt: {user[:200]}"
    return BatchVerdict(verdicts=[
        ExceptionVerdict(
            case_id=cid, classification=ExceptionType.FEE_VARIANCE,
            resolution="RESOLVED", confidence=0.98,
            explanation="Settlement is short by exactly the declared fee.",
            evidence=["settlement_delta 7500", "expected_fee 7500"],
        )
        for cid in ids
    ])


def _analyzer(responder) -> tuple[ExceptionAnalyzer, StubClient]:
    stub = StubClient(responder)
    analyzer = ExceptionAnalyzer(client=stub)  # type: ignore[arg-type]
    analyzer.cache = VerdictCache()  # isolated from the process-wide cache
    return analyzer, stub


def test_exceptions_are_batched_not_sent_one_by_one():
    """25 exceptions at a batch size of 12 must be 3 requests, not 25."""
    from app.config import settings

    analyzer, stub = _analyzer(_all_resolved)
    result = asyncio.run(analyzer.analyze(_cases(25)))

    expected_calls = -(-25 // settings.ai_batch_size)  # ceil
    assert len(stub.calls) == expected_calls
    assert len(result.verdicts) == 25
    assert all(v["resolution"] == Resolution.AI_RESOLVED.value for v in result.verdicts.values())


def test_identical_exceptions_hit_the_cache():
    """Structurally identical breaks must not be re-reasoned."""
    analyzer, stub = _analyzer(_all_resolved)

    asyncio.run(analyzer.analyze(_cases(3)))
    calls_after_first = len(stub.calls)

    asyncio.run(analyzer.analyze(_cases(3)))
    assert len(stub.calls) == calls_after_first, "second pass should be served from cache"


def test_a_dropped_verdict_becomes_a_human_review():
    """If the model silently omits a case, it must not vanish."""

    def drops_one(user: str) -> BatchVerdict:
        full = _all_resolved(user)
        return BatchVerdict(verdicts=full.verdicts[:-1])

    analyzer, _ = _analyzer(drops_one)
    result = asyncio.run(analyzer.analyze(_cases(4)))

    assert len(result.verdicts) == 4
    unanswered = [v for v in result.verdicts.values() if "no verdict returned" in v["validation_reason"]]
    assert len(unanswered) == 1
    assert unanswered[0]["resolution"] == Resolution.HUMAN_REVIEW.value


def test_a_refusal_routes_the_whole_batch_to_humans():
    def refuses(_user: str) -> BatchVerdict:
        raise AIRefusal("declined")

    analyzer, _ = _analyzer(refuses)
    result = asyncio.run(analyzer.analyze(_cases(5)))

    assert result.refused == 5
    assert all(v["resolution"] == Resolution.HUMAN_REVIEW.value for v in result.verdicts.values())


def test_a_transport_failure_never_crashes_the_run():
    def explodes(_user: str) -> BatchVerdict:
        raise RuntimeError("connection reset")

    analyzer, _ = _analyzer(explodes)
    result = asyncio.run(analyzer.analyze(_cases(5)))

    assert result.failed == 5
    assert all(v["resolution"] == Resolution.HUMAN_REVIEW.value for v in result.verdicts.values())
    assert all("AI error" in v["validation_reason"] for v in result.verdicts.values())


def test_the_budget_is_a_hard_ceiling_and_reports_what_it_dropped():
    from app.config import settings

    original = settings.ai_max_exceptions_per_run
    settings.ai_max_exceptions_per_run = 10
    try:
        analyzer, _ = _analyzer(_all_resolved)
        result = asyncio.run(analyzer.analyze(_cases(30)))
    finally:
        settings.ai_max_exceptions_per_run = original

    assert result.skipped_over_budget == 20
    over = [v for v in result.verdicts.values() if "budget" in v["validation_reason"]]
    assert len(over) == 20
    # Truncation is stated, never silently implied.
    assert all(v["resolution"] == Resolution.HUMAN_REVIEW.value for v in over)


def test_a_model_verdict_that_fails_the_gate_is_downgraded_even_in_a_batch():
    """End-to-end version of the validation gate: the model is confident, the
    arithmetic disagrees, and the case still lands with a human."""

    def wrong(user: str) -> BatchVerdict:
        import re

        ids = re.findall(r'"case_id": "([^"]+)"', user)
        return BatchVerdict(verdicts=[
            ExceptionVerdict(
                case_id=cid, classification=ExceptionType.FEE_VARIANCE,
                resolution="RESOLVED", confidence=0.99,
                explanation="Just the gateway fee.", evidence=[],
            )
            for cid in ids
        ])

    cases = _cases(3)
    for c in cases:
        c["settlement_delta_minor"] = 34000  # far more than the 7500 fee

    analyzer, _ = _analyzer(wrong)
    result = asyncio.run(analyzer.analyze(cases))

    assert all(v["resolution"] == Resolution.HUMAN_REVIEW.value for v in result.verdicts.values())
    assert all("unexplained" in v["validation_reason"] for v in result.verdicts.values())
