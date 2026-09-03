"""Command line entry point.

Useful for demos and CI: the whole pipeline runs without the API or the browser,
which also makes it the fastest way to prove a claim on someone else's machine.

    python -m app.cli demo --size 25000
    python -m app.cli benchmark --sizes 1000,10000,100000
    python -m app.cli reconcile --orders a.csv --payments b.csv --settlements c.csv
    python -m app.cli export --run latest --out ./exported
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

import polars as pl

from app.bench.harness import run_benchmark, to_dicts
from app.bench.metrics import evaluate
from app.config import settings
from app.data import generator
from app.logging_setup import configure_logging
from app.services.pipeline import ReconciliationPipeline
from app.store.db import init_db

BAR = "─" * 78


def _print_summary(outcome: dict) -> None:
    s = outcome["summary"]
    t = outcome["timings"]
    total = max(s["total_cases"], 1)
    print(BAR)
    print(f"  Records in       {sum(outcome['counts'].values()):>12,}   "
          f"({', '.join(f'{k} {v:,}' for k, v in outcome['counts'].items())})")
    print(f"  Cases            {s['total_cases']:>12,}")
    print(f"  Matched clean    {s['matched']:>12,}   {s['matched'] / total:>7.2%}")
    print(f"  Exceptions       {s['exceptions']:>12,}   {s['exceptions'] / total:>7.2%}")
    print(f"  Auto-resolved    {s['auto_resolved']:>12,}")
    print(f"  For the AI       {s['pending_ai']:>12,}   {s['pending_ai'] / total:>7.2%}"
          "   <- everything else never leaves SQL")
    print(f"  Human review     {s['human_review']:>12,}")
    print(BAR)
    print(f"  Normalize {t['normalize_seconds']:>7.2f}s   Match {t['match_seconds']:>7.2f}s   "
          f"Classify {t['classify_seconds']:>7.2f}s   Total {t['total_seconds']:>7.2f}s")
    print(f"  Throughput       {outcome['throughput_per_second']:>12,.0f} records/sec")
    print(BAR)


def cmd_demo(args: argparse.Namespace) -> int:
    ds = generator.generate(args.size, f"cli-{args.size}", seed=args.seed)
    generator.persist(ds)
    run_id = f"CLI_{uuid.uuid4().hex[:10].upper()}"

    print(f"\nDataset: {args.size:,} orders  ·  run {run_id}\n")
    pipeline = ReconciliationPipeline(run_id)
    outcome = pipeline.run_sync(ds.orders, ds.payments, ds.settlements)
    _print_summary(outcome)

    if args.ai:
        outcome = asyncio.run(pipeline.run_ai_stage(outcome))
        print("  AI stage:", json.dumps(outcome["ai"], indent=None))
        print(BAR)

    recon = pl.read_parquet(outcome["recon_path"])
    report = evaluate(recon, ds.ground_truth)
    print(f"  Precision {report.precision:>7.4f}   Recall {report.recall:>7.4f}   "
          f"F1 {report.f1:>7.4f}   Label accuracy {report.label_accuracy:>7.4f}")
    print(BAR)
    print("\n  Exception mix")
    for row in (
        recon.group_by("exception_type").len().sort("len", descending=True).iter_rows(named=True)
    ):
        print(f"    {row['exception_type']:<24} {row['len']:>8,}")
    print(f"\n  Artifacts: {settings.run_dir(run_id)}\n")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    sizes = [int(s) for s in args.sizes.split(",")]
    results = to_dicts(run_benchmark(sizes, seed=args.seed))

    header = (f"{'orders':>10} {'records':>11} {'time':>9} {'thru/s':>12} "
              f"{'match':>8} {'prec':>8} {'recall':>8} {'F1':>8} {'ai_cov':>8}")
    print("\n" + header)
    print("─" * len(header))
    for r in results:
        print(f"{r['dataset_size']:>10,} {r['records_total']:>11,} "
              f"{r['duration_seconds']:>8.2f}s {r['throughput_per_second']:>12,.0f} "
              f"{r['match_rate']:>8.4f} {r['precision']:>8.4f} {r['recall']:>8.4f} "
              f"{r['f1']:>8.4f} {r['ai_coverage']:>8.4f}")
    print()

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
        print(f"  Written to {args.json}\n")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    run_id = args.run_id or f"CLI_{uuid.uuid4().hex[:10].upper()}"
    pipeline = ReconciliationPipeline(run_id)
    outcome = pipeline.run_sync(
        Path(args.orders), Path(args.payments), Path(args.settlements)
    )
    _print_summary(outcome)
    if args.ai:
        outcome = asyncio.run(pipeline.run_ai_stage(outcome))
        print("  AI stage:", json.dumps(outcome["ai"]))
    print(f"\n  Artifacts: {settings.run_dir(run_id)}\n")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Dump a run's Parquet artifacts (and its source dataset) to CSV.

    Parquet is the right internal format and the wrong format for a human who
    wants to open the data in a spreadsheet, so this bridges the two.
    """
    runs_root = settings.data_dir / "runs"
    if args.run == "latest":
        candidates = sorted(runs_root.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print(f"No runs found under {runs_root}")
            return 1
        run_dir = candidates[0]
    else:
        run_dir = runs_root / args.run
        if not run_dir.exists():
            print(f"No such run: {run_dir}")
            return 1

    out = Path(args.out) / run_dir.name
    out.mkdir(parents=True, exist_ok=True)

    def flatten(df: pl.DataFrame) -> pl.DataFrame:
        """CSV has no nested types. Join list columns into a readable string
        and serialize anything else structured as JSON."""
        casts = []
        for name, dtype in df.schema.items():
            if isinstance(dtype, pl.List):
                casts.append(
                    pl.col(name).cast(pl.List(pl.Utf8)).list.join(" | ").alias(name)
                )
            elif isinstance(dtype, (pl.Struct, pl.Object)):
                casts.append(pl.col(name).cast(pl.Utf8).alias(name))
        return df.with_columns(casts) if casts else df

    written: list[tuple[str, int]] = []
    for parquet in sorted(run_dir.rglob("*.parquet")):
        name = parquet.stem if parquet.parent.name != "canonical" else f"canonical_{parquet.stem}"
        df = flatten(pl.read_parquet(parquet))
        target = out / f"{name}.csv"
        df.write_csv(target)
        written.append((target.name, df.height))

    manifest = run_dir / "manifest.json"
    if manifest.exists():
        (out / "manifest.json").write_text(manifest.read_text())
        written.append(("manifest.json", 0))

    # The dataset the run consumed, so the raw inputs travel with the output.
    if args.with_dataset:
        label = json.loads(manifest.read_text()).get("run_id") if manifest.exists() else None
        ds_root = settings.data_dir / "datasets"
        newest = sorted(ds_root.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if newest:
            ds_out = out / "source_dataset"
            ds_out.mkdir(exist_ok=True)
            for parquet in sorted(newest[0].glob("*.parquet")):
                df = flatten(pl.read_parquet(parquet))
                df.write_csv(ds_out / f"{parquet.stem}.csv")
                written.append((f"source_dataset/{parquet.stem}.csv", df.height))
            _ = label

    print(f"\n  Exported {run_dir.name} -> {out}\n")
    for name, rows in written:
        print(f"    {name:<34} {rows:>8,} rows" if rows else f"    {name}")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    init_db()

    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("demo", help="generate ground-truth data and reconcile it")
    d.add_argument("--size", type=int, default=25_000)
    d.add_argument("--seed", type=int, default=42)
    d.add_argument("--ai", action="store_true", help="also run the AI exception controller")
    d.set_defaults(func=cmd_demo)

    b = sub.add_parser("benchmark", help="sweep dataset sizes and score against ground truth")
    b.add_argument("--sizes", default="1000,10000,100000")
    b.add_argument("--seed", type=int, default=42)
    b.add_argument("--json", help="write the results to this path")
    b.set_defaults(func=cmd_benchmark)

    r = sub.add_parser("reconcile", help="reconcile three real files")
    r.add_argument("--orders", required=True)
    r.add_argument("--payments", required=True)
    r.add_argument("--settlements", required=True)
    r.add_argument("--run-id")
    r.add_argument("--ai", action="store_true")
    r.set_defaults(func=cmd_reconcile)

    e = sub.add_parser("export", help="write a run's artifacts out as CSV")
    e.add_argument("--run", default="latest", help="run id, or 'latest'")
    e.add_argument("--out", default="./exported")
    e.add_argument("--with-dataset", action="store_true",
                   help="also export the most recent source dataset")
    e.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
