"""Model provider layer.

Everything the rest of the app knows about a language model lives behind this
module: structured output, prompt caching, refusal handling, retries, and usage
accounting. Swapping providers is a change here and nowhere else — the analyzer,
the chat endpoint, and the validation gate never learn which model answered.

Two providers ship: Anthropic (Claude) and Google (Gemini). Which one runs is
decided by whichever API key is present, or pinned explicitly with AI_PROVIDER.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AIUnavailable(RuntimeError):
    """No API key, or the SDK is not installed. Callers degrade gracefully."""


class AIRefusal(RuntimeError):
    """Safety filters declined the request. Route the case to a human."""


@dataclass
class Usage:
    """Per-run token accounting. Without this, every cost claim is a guess.

    The field names are provider-neutral; each provider maps its own response
    shape onto them.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    thinking_tokens: int = 0
    calls: int = 0
    refusals: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "thinking_tokens": self.thinking_tokens,
            "refusals": self.refusals,
            "errors": self.errors,
        }


#: Statuses that mean "this request is wrong", not "try again shortly".
_RETRYABLE_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 529}


def _is_terminal(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and 400 <= status < 500:
        return status not in _RETRYABLE_STATUSES
    return False


@dataclass
class BaseProvider:
    """The contract every provider implements."""

    usage: Usage = field(default_factory=Usage)

    #: Shown in /api/config and on the dashboard.
    name: str = "none"
    model: str = ""

    @property
    def available(self) -> bool:
        return False

    async def structured(
        self, *, system: str, user: str, output_model: type[T], max_retries: int = 2
    ) -> T:
        raise AIUnavailable("no model provider configured")

    async def _with_retries(self, attempt_fn, max_retries: int, output_model: type[T]) -> T:
        """Shared retry loop.

        A refusal is terminal. A client error (bad key, missing header, malformed
        request) is also terminal — it will fail identically every time, so
        retrying it just burns latency and hides the real message.
        """
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await attempt_fn()
            except AIRefusal:
                raise
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                log.warning(
                    "%s: structured output failed validation (attempt %d): %s",
                    self.name, attempt + 1, exc,
                )
            except Exception as exc:
                last_error = exc
                if _is_terminal(exc):
                    self.usage.errors += 1
                    log.error("%s: request rejected, not retrying: %s", self.name, exc)
                    raise RuntimeError(f"{self.name} request rejected: {exc}") from exc
                log.warning("%s call failed (attempt %d): %s", self.name, attempt + 1, exc)
                await asyncio.sleep(min(2**attempt, 8))

        self.usage.errors += 1
        raise RuntimeError(
            f"{self.name} call failed after {max_retries + 1} attempts: {last_error}"
        )


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


@dataclass
class AnthropicProvider(BaseProvider):
    name: str = "anthropic"

    def __post_init__(self) -> None:
        self.model = settings.ai_model
        self._client = None
        if not settings.anthropic_api_key:
            return
        try:
            from anthropic import AsyncAnthropic

            # Identity-linked keys are rejected without a workspace id.
            headers = (
                {"anthropic-workspace-id": settings.anthropic_workspace_id}
                if settings.anthropic_workspace_id
                else None
            )
            self._client = AsyncAnthropic(
                api_key=settings.anthropic_api_key, default_headers=headers
            )
        except ImportError:  # pragma: no cover
            log.warning("anthropic SDK not installed")

    @property
    def available(self) -> bool:
        return self._client is not None

    async def structured(
        self, *, system: str, user: str, output_model: type[T], max_retries: int = 2
    ) -> T:
        if self._client is None:
            raise AIUnavailable("anthropic provider is not configured")

        # The system prompt is byte-identical on every call in a run, so marking
        # it cacheable makes the whole prefix bill at cache-read rates after the
        # first request.
        system_blocks = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]

        async def attempt() -> T:
            response = await self._client.messages.parse(
                model=self.model,
                max_tokens=settings.ai_max_tokens,
                output_config={"effort": settings.ai_effort},
                system=system_blocks,
                messages=[{"role": "user", "content": user}],
                output_format=output_model,
            )
            self._record(response.usage)

            # Check the stop reason before touching content: a refusal returns
            # HTTP 200 with empty or partial content.
            if getattr(response, "stop_reason", None) == "refusal":
                self.usage.refusals += 1
                raise AIRefusal("model declined the request")

            parsed = getattr(response, "parsed_output", None)
            if parsed is not None:
                return parsed

            text = next(
                (b.text for b in response.content if getattr(b, "type", "") == "text"), ""
            )
            return output_model.model_validate(json.loads(text))

        return await self._with_retries(attempt, max_retries, output_model)

    def _record(self, usage: Any) -> None:
        self.usage.calls += 1
        self.usage.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.usage.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.usage.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.usage.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

#: Gemini has no `effort` concept, and the nearest knob changed between model
#: generations — measured against the live API:
#:   Gemini 3.x  accepts `thinking_level` (and `thinking_budget`)
#:   Gemini 2.5  rejects `thinking_level` with a 400; only `thinking_budget`
#: So the config is chosen from the model name rather than assumed.
_GEMINI_THINKING = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
    "xhigh": "HIGH",
    "max": "HIGH",
}

_GEMINI_BUDGET = {
    "low": 512,
    "medium": 2048,
    "high": 8192,
    "xhigh": 16384,
    "max": 24576,
}


def _gemini_supports_thinking_level(model: str) -> bool:
    """Gemini 3 and later. Anything older takes a token budget instead."""
    name = model.lower().removeprefix("models/")
    if not name.startswith("gemini-"):
        return False
    major = name.removeprefix("gemini-").split(".")[0].split("-")[0]
    return major.isdigit() and int(major) >= 3

#: Finish reasons that mean "the model was stopped by a filter", not "it answered".
_GEMINI_REFUSALS = {
    "SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY",
}


@dataclass
class GeminiProvider(BaseProvider):
    name: str = "gemini"

    def __post_init__(self) -> None:
        self.model = settings.gemini_model
        self._client = None
        self._types = None
        if not settings.gemini_api_key:
            return
        try:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=settings.gemini_api_key,
                # Without an explicit timeout a slow or capacity-starved model
                # hangs the request forever, and the run never finishes.
                http_options=types.HttpOptions(timeout=settings.ai_timeout_seconds * 1000),
            )
            self._types = types
        except ImportError:  # pragma: no cover
            log.warning("google-genai SDK not installed (pip install google-genai)")

    @property
    def available(self) -> bool:
        return self._client is not None

    async def structured(
        self, *, system: str, user: str, output_model: type[T], max_retries: int = 2
    ) -> T:
        if self._client is None or self._types is None:
            raise AIUnavailable("gemini provider is not configured")

        types = self._types
        config = types.GenerateContentConfig(
            system_instruction=system,
            # Constrains the response to the schema, so a malformed verdict is a
            # retry rather than a corrupt ledger row — same guarantee we get
            # from Anthropic's structured outputs.
            response_mime_type="application/json",
            response_schema=output_model,
            max_output_tokens=self._output_ceiling(),
            thinking_config=self._thinking_config(types),
            # We pass no tools, so the SDK's function-calling machinery is dead
            # weight — and it logs a warning on every call if left on.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        async def attempt() -> T:
            response = await self._client.aio.models.generate_content(
                model=self.model, contents=user, config=config
            )
            self._record(response.usage_metadata)

            # Gemini signals a block two ways: on the prompt, or on the candidate.
            feedback = getattr(response, "prompt_feedback", None)
            if feedback is not None and getattr(feedback, "block_reason", None):
                self.usage.refusals += 1
                raise AIRefusal(f"prompt blocked: {feedback.block_reason}")

            candidates = response.candidates or []
            if candidates:
                reason = str(getattr(candidates[0], "finish_reason", "") or "")
                # The enum stringifies as e.g. "FinishReason.SAFETY".
                short = reason.rsplit(".", 1)[-1]
                if short in _GEMINI_REFUSALS:
                    self.usage.refusals += 1
                    raise AIRefusal(f"response blocked: {reason}")
                if short == "MAX_TOKENS":
                    # Retrying with the same ceiling fails identically, so this
                    # is terminal and says what to change.
                    raise RuntimeError(
                        "gemini hit max_output_tokens before finishing the JSON "
                        f"(ceiling {self._output_ceiling()}, of which "
                        f"{self._thinking_budget()} is the thinking allowance). "
                        "Raise AI_MAX_TOKENS, lower AI_EFFORT, or lower AI_BATCH_SIZE."
                    )

            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, output_model):
                return parsed

            # Schema-constrained JSON that the SDK did not attach for us.
            text = (response.text or "").strip()
            if not text:
                raise RuntimeError("empty response from gemini")
            return output_model.model_validate(json.loads(text))

        return await self._with_retries(attempt, max_retries, output_model)

    def _thinking_budget(self) -> int:
        return _GEMINI_BUDGET.get(settings.ai_effort, 2048)

    def _thinking_config(self, types: Any) -> Any:
        if _gemini_supports_thinking_level(self.model):
            return types.ThinkingConfig(
                thinking_level=_GEMINI_THINKING.get(settings.ai_effort, "MEDIUM")
            )
        return types.ThinkingConfig(thinking_budget=self._thinking_budget())

    def _output_ceiling(self) -> int:
        """Gemini counts thinking against `max_output_tokens`; Anthropic does not.

        Sizing the ceiling to the answer alone truncates the JSON mid-string as
        soon as the model thinks at all — which is exactly what happened: 82% of
        output tokens were thinking, and every batch of 12 came back unparseable.
        So the ceiling is the answer budget PLUS the thinking allowance.
        """
        return settings.ai_max_tokens + self._thinking_budget()

    def _record(self, usage: Any) -> None:
        self.usage.calls += 1
        if usage is None:
            return
        # Gemini counts thinking separately; it bills as output, so it is added
        # there as well as tracked on its own.
        thoughts = getattr(usage, "thoughts_token_count", 0) or 0
        self.usage.input_tokens += getattr(usage, "prompt_token_count", 0) or 0
        self.usage.output_tokens += (getattr(usage, "candidates_token_count", 0) or 0) + thoughts
        self.usage.thinking_tokens += thoughts
        self.usage.cache_read_tokens += getattr(usage, "cached_content_token_count", 0) or 0


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _build_provider() -> BaseProvider:
    if not settings.ai_enabled:
        return BaseProvider()

    choice = settings.ai_provider.lower().strip()

    if choice == "anthropic":
        return AnthropicProvider()
    if choice == "gemini":
        return GeminiProvider()

    # "auto": whichever key is present wins; Anthropic first if both are set.
    if settings.anthropic_api_key:
        return AnthropicProvider()
    if settings.gemini_api_key:
        return GeminiProvider()
    return BaseProvider()


_client: BaseProvider | None = None


def get_ai_client() -> BaseProvider:
    global _client
    if _client is None:
        _client = _build_provider()
        if _client.available:
            log.info("AI provider: %s (%s)", _client.name, _client.model)
        else:
            log.info("AI provider: none configured — exceptions route to human review")
    return _client


def reset_ai_client() -> None:
    """Used by tests and by config reloads."""
    global _client
    _client = None


#: Backwards-compatible alias. The analyzer type-hints against this.
AIClient = BaseProvider
