"""Benchmark endpoints — the throughput and accuracy evidence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter

from app.api.schemas import BenchmarkRequest, BenchmarkResponse
from app.bench.harness import run_benchmark, to_dicts
from app.config import settings

router = APIRouter(prefix="/benchmark", tags=["benchmark"])

_last: dict = {"results": [], "generated_at": None}


@router.post("", response_model=BenchmarkResponse)
async def execute_benchmark(req: BenchmarkRequest) -> BenchmarkResponse:
    """Sweep dataset sizes end to end and report throughput plus precision/recall.

    Runs off the event loop: a million-row sweep should not block the dashboard
    that is displaying its progress.
    """
    sizes = req.sizes or settings.bench_size_list
    results = await asyncio.to_thread(run_benchmark, sizes, req.seed, False)
    payload = to_dicts(results)
    _last["results"] = payload
    _last["generated_at"] = datetime.now(timezone.utc)
    return BenchmarkResponse(results=payload, generated_at=_last["generated_at"])


@router.get("", response_model=BenchmarkResponse)
def last_benchmark() -> BenchmarkResponse:
    return BenchmarkResponse(
        results=_last["results"],
        generated_at=_last["generated_at"] or datetime.now(timezone.utc),
    )
