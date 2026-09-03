"""Provider selection.

The engine must behave identically whichever model answers — and identically
again when none does. These pin the routing, not the model.
"""

from __future__ import annotations

import pytest

from app.ai import client as client_mod
from app.ai.client import AnthropicProvider, BaseProvider, GeminiProvider, get_ai_client
from app.config import settings


@pytest.fixture(autouse=True)
def _restore():
    """Provider choice is process-wide; put it back after every test."""
    saved = (settings.ai_provider, settings.anthropic_api_key,
             settings.gemini_api_key, settings.ai_enabled)
    client_mod.reset_ai_client()
    yield
    (settings.ai_provider, settings.anthropic_api_key,
     settings.gemini_api_key, settings.ai_enabled) = saved
    client_mod.reset_ai_client()


def _select(provider: str, anthropic: str | None, gemini: str | None) -> BaseProvider:
    settings.ai_provider = provider
    settings.anthropic_api_key = anthropic
    settings.gemini_api_key = gemini
    settings.ai_enabled = True
    client_mod.reset_ai_client()
    return get_ai_client()


def test_auto_picks_gemini_when_only_a_gemini_key_is_present():
    c = _select("auto", None, "test-gemini-key")
    assert isinstance(c, GeminiProvider)
    assert c.name == "gemini"
    assert c.available


def test_auto_picks_anthropic_when_only_an_anthropic_key_is_present():
    c = _select("auto", "sk-ant-test", None)
    assert isinstance(c, AnthropicProvider)
    assert c.available


def test_auto_prefers_anthropic_when_both_keys_are_set():
    c = _select("auto", "sk-ant-test", "test-gemini-key")
    assert c.name == "anthropic"


def test_an_explicit_setting_overrides_key_presence():
    """Both keys set, but AI_PROVIDER=gemini must win."""
    c = _select("gemini", "sk-ant-test", "test-gemini-key")
    assert c.name == "gemini"


def test_no_keys_means_no_provider_not_a_crash():
    c = _select("auto", None, None)
    assert not c.available
    assert c.name == "none"


def test_ai_disabled_short_circuits_even_with_a_key():
    settings.ai_provider = "auto"
    settings.anthropic_api_key = "sk-ant-test"
    settings.ai_enabled = False
    client_mod.reset_ai_client()
    assert not get_ai_client().available


def test_every_provider_reports_usage_in_the_same_shape():
    """The dashboard and the manifest read one usage shape regardless of who answered."""
    expected = {
        "calls", "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_write_tokens", "thinking_tokens", "refusals", "errors",
    }
    for c in (BaseProvider(), AnthropicProvider(), GeminiProvider()):
        assert set(c.usage.as_dict()) == expected


@pytest.mark.parametrize("effort,expected", [
    ("low", "LOW"), ("medium", "MEDIUM"), ("high", "HIGH"),
    ("xhigh", "HIGH"), ("max", "HIGH"),
])
def test_effort_maps_onto_geminis_thinking_levels(effort: str, expected: str):
    """Gemini has no `effort`; thinking level is the nearest equivalent knob."""
    from app.ai.client import _GEMINI_THINKING

    assert _GEMINI_THINKING[effort] == expected
