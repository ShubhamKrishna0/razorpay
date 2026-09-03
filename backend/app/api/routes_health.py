"""Liveness and capability reporting."""

from __future__ import annotations

from fastapi import APIRouter

from app.ai.cache import get_cache
from app.ai.client import get_ai_client
from app.config import settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.env}


@router.get("/config")
def config() -> dict:
    """What the engine is actually configured to do.

    Exposed so a demo audience can see the thresholds rather than take them on
    trust. No secrets are returned — only whether a key is present.
    """
    ai = get_ai_client()
    return {
        "app": settings.app_name,
        "env": settings.env,
        "engine": {
            "amount_tolerance_minor": settings.amount_tolerance_minor,
            "fee_tolerance_minor": settings.fee_tolerance_minor,
            "default_fee_bps": settings.default_fee_bps,
            "time_window_hours": settings.time_window_hours,
            "settlement_window_days": settings.settlement_window_days,
            "auto_resolve_threshold": settings.auto_resolve_threshold,
            "ai_investigate_threshold": settings.ai_investigate_threshold,
            "duckdb_threads": settings.duckdb_threads,
        },
        "ai": {
            "enabled": settings.ai_enabled,
            "configured": ai.available,
            "provider": ai.name,
            "model": ai.model,
            "provider_setting": settings.ai_provider,
            "effort": settings.ai_effort,
            "batch_size": settings.ai_batch_size,
            "max_concurrency": settings.ai_max_concurrency,
            "max_exceptions_per_run": settings.ai_max_exceptions_per_run,
            "usage": ai.usage.as_dict(),
        },
        "cache": get_cache().stats(),
    }
