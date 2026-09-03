"""Benchmark harness.

Runs the full pipeline across escalating dataset sizes and records throughput
alongside accuracy. One cherry-picked match proves nothing; a curve does.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import polars as pl

from app.bench.metrics import evaluate
from app.config import settings
from app.data import generator
from app.services.pipeline import ReconciliationPipeline

log = logging.getLogger(__name__)


@dataclass
class BenchResult:
    dataset_size: int
    records_total: int
    duration_seconds: float
    throughput_per_second: float
    matched: int
    exceptions: int
    match_rate: float
    auto_resolved: int
    ai_calls: int
    ai_coverage: float
    precision: float
    recall: float
    f1: float
    label_accuracy: float
    detail: dict[str, Any] = field(default_factory=dict)


def run_benchmark(
    sizes: list[int] | None = None,
    seed: int = 42,
    use_ai: bool = False,
) -> list[BenchResult]:
    """Sweep dataset sizes.

    `use_ai` defaults off: the benchmark's job is to characterise the
    deterministic engine's throughput and accuracy. AI adds network latency
    that would make the throughput numbers meaningless.
    """
    sizes = sizes or settings.bench_size_list
    results: list[BenchResult] = []

    for size in sizes:
        dataset_id = f"bench-{size}-{seed}"
        ds = generator.generate(size, dataset_id, seed=seed)
        generator.persist(ds)

        run_id = f"bench-{uuid.uuid4().hex[:10]}"
        pipeline = ReconciliationPipeline(run_id=run_id)

        started = time.perf_counter()
        outcome = pipeline.run_sync(
            orders=ds.orders, payments=ds.payments, settlements=ds.settlements,
            source_names={"ORDER": "bench_orders", "PAYMENT": "bench_payments",
                          "SETTLEMENT": "bench_settlements"},
        )
        elapsed = time.perf_counter() - started

        recon = pl.read_parquet(outcome["recon_path"])
        accuracy = evaluate(recon, ds.ground_truth)
        summary = outcome["summary"]
        total_records = ds.orders.height + ds.payments.height + ds.settlements.height

        results.append(BenchResult(
            dataset_size=size,
            records_total=total_records,
            duration_seconds=round(elapsed, 3),
            throughput_per_second=round(total_records / elapsed, 1) if elapsed else 0.0,
            matched=summary["matched"],
            exceptions=summary["exceptions"],
            match_rate=round(summary["matched"] / max(summary["total_cases"], 1), 4),
            auto_resolved=summary["auto_resolved"],
            ai_calls=0 if not use_ai else outcome.get("ai", {}).get("ai_calls", 0),
            # The headline efficiency metric: what fraction of records the LLM
            # never had to look at.
            ai_coverage=round(summary["pending_ai"] / max(summary["total_cases"], 1), 4),
            precision=accuracy.precision,
            recall=accuracy.recall,
            f1=accuracy.f1,
            label_accuracy=accuracy.label_accuracy,
            detail={"accuracy": accuracy.as_dict(), "summary": summary},
        ))
        log.info("bench size=%d elapsed=%.2fs throughput=%.0f/s",
                 size, elapsed, total_records / elapsed if elapsed else 0)

    return results


def to_dicts(results: list[BenchResult]) -> list[dict[str, Any]]:
    return [asdict(r) for r in results]
