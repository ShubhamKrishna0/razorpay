"""Parquet-backed run storage.

CSV is an interchange format, not an internal one. Everything the engine touches
is Parquet: columnar, compressed, and cheap to re-scan when a run resumes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from app.config import settings


def ensure_run_dirs(run_id: str) -> Path:
    root = settings.run_dir(run_id)
    (root / "canonical").mkdir(parents=True, exist_ok=True)
    return root


def canonical_path(run_id: str, source_kind: str) -> Path:
    return settings.run_dir(run_id) / "canonical" / f"{source_kind.lower()}.parquet"


def artifact_path(run_id: str, name: str) -> Path:
    return settings.run_dir(run_id) / f"{name}.parquet"


def write_parquet(df: pl.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression="zstd")
    return path


def read_parquet(path: Path) -> pl.DataFrame:
    return pl.read_parquet(path)


def write_manifest(run_id: str, manifest: dict[str, Any]) -> None:
    path = settings.run_dir(run_id) / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, default=str))


def read_manifest(run_id: str) -> dict[str, Any]:
    path = settings.run_dir(run_id) / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def checkpoint_path(run_id: str) -> Path:
    return settings.run_dir(run_id) / "checkpoint.json"


def save_checkpoint(run_id: str, state: dict[str, Any]) -> None:
    """Restartability: a crashed run resumes from the last completed stage
    instead of re-reconciling from record zero."""
    p = checkpoint_path(run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, default=str))


def load_checkpoint(run_id: str) -> dict[str, Any]:
    p = checkpoint_path(run_id)
    return json.loads(p.read_text()) if p.exists() else {}
