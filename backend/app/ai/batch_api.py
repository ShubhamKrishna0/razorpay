"""Offline adjudication via the Message Batches API.

For a run with hundreds of thousands of exceptions, latency stops mattering and
cost starts to. Batches run asynchronously at 50% of standard token prices; this
is the path you take when a reconciliation is scheduled rather than interactive.

Anthropic-only. Gemini has its own batch surface with a different shape, so this
module raises rather than silently doing something else when Gemini is selected.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.analyzer import slim_case
from app.ai.prompts import EXCEPTION_ANALYST_SYSTEM, exception_batch_prompt
from app.ai.schemas import BatchVerdict
from app.config import settings

log = logging.getLogger(__name__)


def _client():
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "The Message Batches path is Anthropic-only. Set ANTHROPIC_API_KEY, "
            "or use the interactive analyzer, which supports both providers."
        )
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


def submit(rows: list[dict[str, Any]]) -> str:
    """Queue every exception as batch requests. Returns the batch id."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    cases = [slim_case(r) for r in rows]
    size = settings.ai_batch_size
    chunks = [cases[i : i + size] for i in range(0, len(cases), size)]

    requests = [
        Request(
            custom_id=f"chunk-{i}",
            params=MessageCreateParamsNonStreaming(
                model=settings.ai_model,
                max_tokens=settings.ai_max_tokens,
                system=[{
                    "type": "text",
                    "text": EXCEPTION_ANALYST_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": exception_batch_prompt(chunk)}],
                output_config={
                    "effort": settings.ai_effort,
                    "format": {
                        "type": "json_schema",
                        "schema": BatchVerdict.model_json_schema(),
                    },
                },
            ),
        )
        for i, chunk in enumerate(chunks)
    ]
    batch = _client().messages.batches.create(requests=requests)
    log.info("submitted batch %s with %d requests", batch.id, len(requests))
    return batch.id


def poll(batch_id: str) -> str:
    return _client().messages.batches.retrieve(batch_id).processing_status


def collect(batch_id: str) -> list[dict[str, Any]]:
    """Drain a finished batch. Results arrive in arbitrary order, so we key by
    the verdict's own case_id rather than by position."""
    verdicts: list[dict[str, Any]] = []
    for result in _client().messages.batches.results(batch_id):
        if result.result.type != "succeeded":
            log.warning("batch item %s: %s", result.custom_id, result.result.type)
            continue
        text = next(
            (b.text for b in result.result.message.content if b.type == "text"), ""
        )
        try:
            parsed = BatchVerdict.model_validate(json.loads(text))
            verdicts.extend(v.model_dump(mode="json") for v in parsed.verdicts)
        except Exception as exc:  # noqa: BLE001
            log.warning("unparseable batch result %s: %s", result.custom_id, exc)
    return verdicts
