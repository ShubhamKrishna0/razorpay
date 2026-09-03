"""Central configuration. Every tunable lives here and is overridable via .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- app -------------------------------------------------------------
    app_name: str = "AI Finance Controller"
    env: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # Comma-separated list, or "*" for all. Render frontend URL goes here.
    cors_origins: str = "*"

    # ---- storage ---------------------------------------------------------
    # Root for parquet artifacts. On Render, point this at a mounted disk.
    data_dir: Path = Path("./var/data")
    # SQLite locally; set DATABASE_URL to a Render Postgres URL in production.
    database_url: str = "sqlite:///./var/finance_controller.db"

    # ---- engine ----------------------------------------------------------
    duckdb_threads: int = 4
    duckdb_memory_limit: str = "2GB"
    # Amounts are held as integer minor units (paise/cents) to kill float drift.
    amount_scale: int = 100
    default_currency: str = "INR"

    # Matching tolerances
    time_window_hours: int = 48          # payment vs order acceptable lag
    settlement_window_days: int = 7      # payment vs settlement acceptable lag
    amount_tolerance_minor: int = 100    # ₹1.00 — rounding noise, not a mismatch
    fee_tolerance_minor: int = 50        # ₹0.50 around the configured fee
    default_fee_bps: int = 200           # 2.00% gateway fee when not supplied
    amount_bucket_minor: int = 10_000    # ₹100 blocking bucket for fuzzy stage

    # Confidence thresholds
    auto_resolve_threshold: float = 0.95
    ai_investigate_threshold: float = 0.80

    # ---- AI --------------------------------------------------------------
    # "auto" picks whichever key is present (Anthropic first if both are set).
    # Pin it to "anthropic" or "gemini" to be explicit.
    ai_provider: str = "auto"

    anthropic_api_key: str | None = None
    # Identity-linked keys must name the workspace they act in. Console →
    # Settings → Workspaces; the id looks like `wrkspc_01...`. Plain API keys
    # do not need this.
    anthropic_workspace_id: str | None = None
    ai_model: str = "claude-opus-5"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    ai_effort: str = "high"              # low | medium | high | xhigh | max
    ai_max_tokens: int = 8000
    # Per-request ceiling. A model that blows through this is reported as an
    # error and its cases go to a human, rather than stalling the run.
    ai_timeout_seconds: int = 90
    ai_batch_size: int = 12              # exceptions bundled into one request
    ai_max_concurrency: int = 4          # parallel in-flight requests
    ai_max_exceptions_per_run: int = 500 # hard cost ceiling per run
    ai_enabled: bool = True

    # ---- cache -----------------------------------------------------------
    # Optional. Falls back to an in-process LRU when unset.
    redis_url: str | None = None
    cache_ttl_seconds: int = 60 * 60 * 24 * 7

    # ---- benchmark -------------------------------------------------------
    bench_sizes: str = "1000,10000,100000"

    @property
    def cors_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        return ["*"] if raw == "*" else [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def bench_size_list(self) -> list[int]:
        return [int(s) for s in self.bench_sizes.split(",") if s.strip()]

    def run_dir(self, run_id: str) -> Path:
        return self.data_dir / "runs" / run_id

    def dataset_dir(self, dataset_id: str) -> Path:
        return self.data_dir / "datasets" / dataset_id


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
