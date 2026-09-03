"""The AI exception controller.

Deliberately narrow: the model never sees the dataset, only exceptions the
deterministic engine could not close, and its verdict is a *recommendation*
that must pass a deterministic validation rule before it can close a case.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.ai.cache import fingerprint, get_cache
from app.ai.client import AIClient, AIRefusal, AIUnavailable, get_ai_client
from app.ai.prompts import EXCEPTION_ANALYST_SYSTEM, exception_batch_prompt
from app.ai.schemas import BatchVerdict, ExceptionVerdict
from app.config import settings
from app.core.enums import ExceptionType, Resolution

log = logging.getLogger(__name__)

#: Classifications where an AI explanation, once validated, is sufficient to
#: close the case. Anything representing genuinely missing money is not here —
#: no amount of explanation makes an unexplained shortfall safe to auto-close.
AI_CLOSEABLE = {
    ExceptionType.MATCHED,
    ExceptionType.FEE_VARIANCE,
    ExceptionType.REFUND,
    ExceptionType.TIMING_MISMATCH,
    ExceptionType.DUPLICATE,
}


@dataclass
class AnalysisResult:
    verdicts: dict[str, dict[str, Any]] = field(default_factory=dict)
    cache_hits: int = 0
    ai_calls: int = 0
    refused: int = 0
    failed: int = 0
    skipped_over_budget: int = 0


def slim_case(row: dict[str, Any]) -> dict[str, Any]:
    """Minimum viable context for a verdict.

    Sending the full record would cost tokens, add latency, and widen the
    hallucination surface for no analytical gain.
    """
    return {
        "case_id": row.get("case_id"),
        "exception_type": row.get("exception_type"),
        "currency": row.get("currency"),
        "merchant_id": row.get("merchant_id"),
        "order_amount_minor": row.get("order_amount_minor"),
        "payment_amount_minor": row.get("payment_amount_minor"),
        "settlement_amount_minor": row.get("settlement_amount_minor"),
        "expected_fee_minor": row.get("expected_fee_minor"),
        "payment_delta_minor": row.get("payment_delta_minor"),
        "settlement_delta_minor": row.get("settlement_delta_minor"),
        "order_to_payment_seconds": row.get("op_time_delta_sec"),
        "payment_to_settlement_seconds": row.get("ps_time_delta_sec"),
        "has_order": row.get("order_uid") is not None,
        "has_payment": row.get("payment_uid") is not None,
        "has_settlement": row.get("settlement_uid") is not None,
        "is_duplicate": bool(row.get("is_duplicate")),
        "duplicate_reason": row.get("dupe_reason"),
        "engine_confidence": row.get("confidence"),
        "match_rule": row.get("op_rule"),
    }


def validate_verdict(case: dict[str, Any], verdict: ExceptionVerdict) -> tuple[Resolution, str]:
    """Deterministic gate in front of every AI recommendation.

    The AI can be confident and wrong. This re-derives the arithmetic from the
    case itself and only lets a case close when the numbers actually agree.
    """
    if verdict.resolution != "RESOLVED":
        return Resolution.HUMAN_REVIEW, "model deferred to a human"
    if verdict.confidence < settings.auto_resolve_threshold:
        return Resolution.HUMAN_REVIEW, (
            f"confidence {verdict.confidence:.2f} below auto-resolve threshold "
            f"{settings.auto_resolve_threshold:.2f}"
        )
    if verdict.classification not in AI_CLOSEABLE:
        return Resolution.HUMAN_REVIEW, (
            f"{verdict.classification.value} represents an unexplained balance; "
            "not auto-closeable by policy"
        )

    cls = verdict.classification
    settle_delta = case.get("settlement_delta_minor") or 0
    expected_fee = case.get("expected_fee_minor") or 0
    pay_delta = case.get("payment_delta_minor") or 0

    if cls is ExceptionType.FEE_VARIANCE:
        if abs(settle_delta - expected_fee) > settings.fee_tolerance_minor:
            return Resolution.HUMAN_REVIEW, (
                f"settlement short by {settle_delta} but configured fee is "
                f"{expected_fee}; {abs(settle_delta - expected_fee)} unexplained"
            )
    elif cls is ExceptionType.MATCHED:
        if abs(pay_delta) > settings.amount_tolerance_minor:
            return Resolution.HUMAN_REVIEW, f"payment differs from order by {pay_delta}"
        # A MATCHED claim must explain the settlement side too: money withheld
        # beyond the declared fee is not "matched", whatever the model thinks.
        if case.get("has_settlement") and abs(settle_delta - expected_fee) > settings.fee_tolerance_minor:
            return Resolution.HUMAN_REVIEW, (
                f"settlement short by {settle_delta} but declared fee is "
                f"{expected_fee}; {abs(settle_delta - expected_fee)} unexplained"
            )
    elif cls is ExceptionType.TIMING_MISMATCH:
        limit = settings.settlement_window_days * 86400 * 2
        if (case.get("payment_to_settlement_seconds") or 0) > limit:
            return Resolution.HUMAN_REVIEW, "settlement lag exceeds the acceptable window"
    elif cls is ExceptionType.DUPLICATE:
        if not case.get("is_duplicate"):
            return Resolution.HUMAN_REVIEW, "engine found no duplicate key for this case"

    return Resolution.AI_RESOLVED, "validated against deterministic rules"


class ExceptionAnalyzer:
    def __init__(self, client: AIClient | None = None) -> None:
        self.client = client or get_ai_client()
        self.cache = get_cache()

    async def analyze(self, rows: list[dict[str, Any]]) -> AnalysisResult:
        """Adjudicate a set of exceptions with caching, batching, and a budget."""
        result = AnalysisResult()
        cases = [slim_case(r) for r in rows]

        pending: list[dict[str, Any]] = []
        for case in cases:
            cached = self.cache.get(fingerprint(case))
            if cached is not None:
                # Re-validate even on a cache hit: the verdict is reused, the
                # authorization to close the case is always re-derived.
                verdict = ExceptionVerdict.model_validate(cached)
                result.verdicts[case["case_id"]] = self._finalize(case, verdict, cached_hit=True)
                result.cache_hits += 1
            else:
                pending.append(case)

        if not self.client.available:
            for case in pending:
                result.verdicts[case["case_id"]] = self._fallback(
                    case, "AI layer not configured"
                )
            return result

        budget = settings.ai_max_exceptions_per_run
        if len(pending) > budget:
            # Honest truncation: we say what we dropped rather than implying
            # full coverage.
            log.warning("AI budget: analyzing %d of %d exceptions", budget, len(pending))
            for case in pending[budget:]:
                result.verdicts[case["case_id"]] = self._fallback(
                    case, "exceeded per-run AI budget"
                )
            result.skipped_over_budget = len(pending) - budget
            pending = pending[:budget]

        size = settings.ai_batch_size
        batches = [pending[i : i + size] for i in range(0, len(pending), size)]
        sem = asyncio.Semaphore(settings.ai_max_concurrency)

        async def run_batch(batch: list[dict[str, Any]]) -> None:
            async with sem:
                await self._process_batch(batch, result)

        await asyncio.gather(*(run_batch(b) for b in batches))
        return result

    async def _process_batch(self, batch: list[dict[str, Any]], result: AnalysisResult) -> None:
        by_id = {c["case_id"]: c for c in batch}
        try:
            parsed = await self.client.structured(
                system=EXCEPTION_ANALYST_SYSTEM,
                user=exception_batch_prompt(batch),
                output_model=BatchVerdict,
            )
            result.ai_calls += 1
        except AIRefusal:
            result.refused += len(batch)
            for case in batch:
                result.verdicts[case["case_id"]] = self._fallback(case, "model declined")
            return
        except (AIUnavailable, Exception) as exc:  # noqa: BLE001 - degrade, never crash a run
            log.warning("batch analysis failed: %s", exc)
            result.failed += len(batch)
            for case in batch:
                result.verdicts[case["case_id"]] = self._fallback(case, f"AI error: {exc}")
            return

        seen: set[str] = set()
        for verdict in parsed.verdicts:
            case = by_id.get(verdict.case_id)
            if case is None:
                log.warning("model returned unknown case_id %s", verdict.case_id)
                continue
            seen.add(verdict.case_id)
            self.cache.set(fingerprint(case), verdict.model_dump(mode="json"))
            result.verdicts[verdict.case_id] = self._finalize(case, verdict)

        # A case the model silently dropped is a case a human must see.
        for case_id in by_id.keys() - seen:
            result.verdicts[case_id] = self._fallback(by_id[case_id], "no verdict returned")

    def _finalize(
        self, case: dict[str, Any], verdict: ExceptionVerdict, cached_hit: bool = False
    ) -> dict[str, Any]:
        resolution, reason = validate_verdict(case, verdict)
        return {
            "case_id": case["case_id"],
            "ai_classification": verdict.classification.value,
            "ai_confidence": verdict.confidence,
            "ai_explanation": verdict.explanation,
            "ai_evidence": verdict.evidence,
            "suggested_action": verdict.suggested_action,
            "resolution": resolution.value,
            "validation_reason": reason,
            "from_cache": cached_hit,
        }

    @staticmethod
    def _fallback(case: dict[str, Any], reason: str) -> dict[str, Any]:
        """Anything we could not adjudicate goes to a human. Never silently closed."""
        return {
            "case_id": case["case_id"],
            "ai_classification": case.get("exception_type"),
            "ai_confidence": 0.0,
            "ai_explanation": f"Not analyzed: {reason}.",
            "ai_evidence": [],
            "suggested_action": "Manual review required.",
            "resolution": Resolution.HUMAN_REVIEW.value,
            "validation_reason": reason,
            "from_cache": False,
        }
