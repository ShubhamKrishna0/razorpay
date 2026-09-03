"""The reconciliation pipeline.

Ingest → normalize → cascade match → classify → (only then) AI. Each stage
checkpoints, so a crashed run resumes at the last completed stage rather than
re-reconciling from record zero.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import polars as pl

from app.ai.analyzer import ExceptionAnalyzer
from app.core.enums import Resolution, RunStatus, SourceKind
from app.data import storage
from app.data.normalizer import load_any, normalize_frame
from app.engine import classifier, matcher
from app.engine.duck import duck_connection
from app.engine.rules import order_payment_rules, payment_settlement_rules
from app.services.audit import AuditTrail

log = logging.getLogger(__name__)

ENGINE_VERSION = "1.0.0"


class ReconciliationPipeline:
    def __init__(self, run_id: str, on_progress=None) -> None:
        self.run_id = run_id
        self.on_progress = on_progress or (lambda **_: None)
        self.audit = AuditTrail(run_id)
        storage.ensure_run_dirs(run_id)

    # -- stages ------------------------------------------------------------

    def normalize(
        self,
        sources: dict[SourceKind, pl.DataFrame | Path],
        source_names: dict[str, str] | None = None,
        mappings: dict[str, dict[str, str]] | None = None,
    ) -> dict[SourceKind, Path]:
        names = source_names or {}
        mappings = mappings or {}
        paths: dict[SourceKind, Path] = {}

        for kind, src in sources.items():
            df = load_any(src) if isinstance(src, Path) else src
            canonical = normalize_frame(
                df, kind,
                source_name=names.get(kind.value, kind.value.lower()),
                mapping=mappings.get(kind.value),
            )
            path = storage.canonical_path(self.run_id, kind.value)
            storage.write_parquet(canonical, path)
            paths[kind] = path
            log.info("normalized %s: %d rows -> %s", kind.value, canonical.height, path)

        storage.save_checkpoint(self.run_id, {"stage": RunStatus.NORMALIZING.value,
                                              "paths": {k.value: str(v) for k, v in paths.items()}})
        return paths

    def run_sync(
        self,
        orders: pl.DataFrame | Path,
        payments: pl.DataFrame | Path,
        settlements: pl.DataFrame | Path,
        source_names: dict[str, str] | None = None,
        mappings: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """The deterministic half. No network calls, no model, fully reproducible."""
        t0 = time.perf_counter()
        self.on_progress(status=RunStatus.NORMALIZING.value)

        paths = self.normalize(
            {SourceKind.ORDER: orders, SourceKind.PAYMENT: payments,
             SourceKind.SETTLEMENT: settlements},
            source_names, mappings,
        )
        t_normalize = time.perf_counter() - t0

        self.on_progress(status=RunStatus.MATCHING.value)
        with duck_connection() as con:
            for kind, path in paths.items():
                con.execute(
                    f"CREATE OR REPLACE TABLE {kind.value.lower()}s AS "
                    "SELECT * FROM read_parquet(?)", [str(path)]
                )

            counts = {
                t: int(con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
                for t in ("orders", "payments", "settlements")
            }

            dupes = matcher.detect_duplicates(con, "payments", "payment_dupes")

            t1 = time.perf_counter()
            op_stats = matcher.run_cascade(
                con, "orders", "payments", "op_links", order_payment_rules()
            )
            ps_stats = matcher.run_cascade(
                con, "payments", "settlements", "ps_links", payment_settlement_rules(),
                window_sec=7 * 86400,
                # A duplicate payment must not claim the settlement that belongs
                # to the original it duplicates.
                exclude_left="payment_dupes",
            )
            t_match = time.perf_counter() - t1

            # Candidates the cascade couldn't close, ranked — this is the only
            # thing the AI layer is ever allowed to see beyond the case itself.
            candidates = matcher.generate_ai_candidates(
                con, "orders", "payments", "op_links", "ai_candidates"
            )

            self.on_progress(status=RunStatus.CLASSIFYING.value)
            t2 = time.perf_counter()
            classifier.build_reconciliation(con)
            t_classify = time.perf_counter() - t2

            summary = classifier.summarize(con)
            breakdown = classifier.breakdown(con)

            recon_path = storage.artifact_path(self.run_id, "recon")
            con.execute(
                "COPY (SELECT * FROM recon) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(recon_path)],
            )
            exc_path = storage.artifact_path(self.run_id, "exceptions")
            con.execute(
                "COPY (SELECT * FROM recon WHERE exception_type <> 'MATCHED') "
                "TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(exc_path)],
            )
            links_path = storage.artifact_path(self.run_id, "links")
            con.execute(
                "COPY (SELECT 'ORDER_PAYMENT' AS leg, * FROM op_links "
                " UNION ALL SELECT 'PAYMENT_SETTLEMENT', * FROM ps_links) "
                "TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(links_path)],
            )

        elapsed = time.perf_counter() - t0
        total_records = sum(counts.values())

        outcome = {
            "run_id": self.run_id,
            "engine_version": ENGINE_VERSION,
            "counts": counts,
            "duplicates": dupes,
            "ai_candidate_pairs": candidates,
            "summary": summary,
            "breakdown": breakdown,
            "cascade": {
                "order_payment": [s.__dict__ for s in op_stats],
                "payment_settlement": [s.__dict__ for s in ps_stats],
            },
            "timings": {
                "normalize_seconds": round(t_normalize, 3),
                "match_seconds": round(t_match, 3),
                "classify_seconds": round(t_classify, 3),
                "total_seconds": round(elapsed, 3),
            },
            "throughput_per_second": round(total_records / elapsed, 1) if elapsed else 0.0,
            "recon_path": str(recon_path),
            "exceptions_path": str(exc_path),
            "links_path": str(links_path),
        }

        self.audit.record_engine_pass(outcome)
        storage.write_manifest(self.run_id, outcome)
        storage.save_checkpoint(self.run_id, {"stage": RunStatus.CLASSIFYING.value,
                                              "completed": True})
        return outcome

    async def run_ai_stage(self, outcome: dict[str, Any]) -> dict[str, Any]:
        """Adjudicate only what the engine left open."""
        self.on_progress(status=RunStatus.AI_ANALYZING.value)
        recon_path = Path(outcome["recon_path"])
        recon = pl.read_parquet(recon_path)

        pending = recon.filter(pl.col("resolution") == Resolution.UNRESOLVED.value)
        if pending.height == 0:
            outcome["ai"] = {"analyzed": 0, "note": "engine closed every case"}
            return outcome

        analyzer = ExceptionAnalyzer()
        result = await analyzer.analyze(pending.to_dicts())

        verdicts = pl.DataFrame(
            list(result.verdicts.values()),
            schema={
                "case_id": pl.Utf8, "ai_classification": pl.Utf8,
                "ai_confidence": pl.Float64, "ai_explanation": pl.Utf8,
                "ai_evidence": pl.List(pl.Utf8), "suggested_action": pl.Utf8,
                "resolution": pl.Utf8, "validation_reason": pl.Utf8,
                "from_cache": pl.Boolean,
            },
        ) if result.verdicts else pl.DataFrame(schema={"case_id": pl.Utf8})

        merged = recon.join(
            verdicts.rename({"resolution": "ai_resolution"}), on="case_id", how="left"
        ).with_columns(
            pl.coalesce([pl.col("ai_resolution"), pl.col("resolution")]).alias("resolution")
        ).drop("ai_resolution")

        storage.write_parquet(merged, recon_path)
        storage.write_parquet(
            merged.filter(pl.col("exception_type") != "MATCHED"),
            Path(outcome["exceptions_path"]),
        )

        stats = {
            "analyzed": pending.height,
            "ai_calls": result.ai_calls,
            "cache_hits": result.cache_hits,
            "refused": result.refused,
            "failed": result.failed,
            "skipped_over_budget": result.skipped_over_budget,
            "ai_resolved": int(
                merged.filter(pl.col("resolution") == Resolution.AI_RESOLVED.value).height
            ),
            "human_review": int(
                merged.filter(pl.col("resolution") == Resolution.HUMAN_REVIEW.value).height
            ),
            "usage": analyzer.client.usage.as_dict(),
        }
        outcome["ai"] = stats
        outcome["summary"] = _recount(merged)
        self.audit.record_ai_pass(stats)
        storage.write_manifest(self.run_id, outcome)
        return outcome


def _recount(recon: pl.DataFrame) -> dict[str, int]:
    def n(expr) -> int:
        return int(recon.filter(expr).height)

    return {
        "total_cases": recon.height,
        "matched": n(pl.col("exception_type") == "MATCHED"),
        "exceptions": n(pl.col("exception_type") != "MATCHED"),
        "auto_resolved": n(pl.col("resolution") == Resolution.AUTO_RESOLVED.value),
        "ai_resolved": n(pl.col("resolution") == Resolution.AI_RESOLVED.value),
        "pending_ai": n(pl.col("resolution") == Resolution.UNRESOLVED.value),
        "human_review": n(pl.col("resolution") == Resolution.HUMAN_REVIEW.value),
        "gross_order_minor": int(recon["order_amount_minor"].fill_null(0).sum()),
        "gross_payment_minor": int(recon["payment_amount_minor"].fill_null(0).sum()),
        "gross_settlement_minor": int(recon["settlement_amount_minor"].fill_null(0).sum()),
    }
