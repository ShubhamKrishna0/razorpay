"""Finance control chat.

Answers questions over a *completed* run using aggregates only. The model never
queries the dataset — the API assembles a bounded context, which keeps the
answer grounded and the token cost flat regardless of dataset size.
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.client import AIRefusal, AIUnavailable, get_ai_client
from app.ai.prompts import FINANCE_CHAT_SYSTEM, chat_prompt
from app.ai.schemas import ChatAnswer

log = logging.getLogger(__name__)


async def answer_question(question: str, context: dict[str, Any]) -> dict[str, Any]:
    client = get_ai_client()
    if not client.available:
        return {
            "answer": (
                "The AI layer is not configured, so I can't answer in natural "
                "language. The run's figures are still available on the dashboard "
                "and through the metrics endpoint."
            ),
            "breakdown": [],
            "followups": [],
            "used_figures": [],
            "degraded": True,
        }
    try:
        parsed = await client.structured(
            system=FINANCE_CHAT_SYSTEM,
            user=chat_prompt(question, context),
            output_model=ChatAnswer,
        )
        payload = parsed.model_dump(mode="json")
        payload["degraded"] = False
        return payload
    except AIRefusal:
        return {
            "answer": "I can't answer that question.",
            "breakdown": [], "followups": [], "used_figures": [], "degraded": True,
        }
    except (AIUnavailable, Exception) as exc:  # noqa: BLE001
        log.warning("chat failed: %s", exc)
        return {
            "answer": f"I couldn't complete that request ({exc}).",
            "breakdown": [], "followups": [], "used_figures": [], "degraded": True,
        }
