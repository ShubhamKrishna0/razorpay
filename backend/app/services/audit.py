"""Audit trail.

Every decision the system makes is recorded with the rule that produced it, the
confidence behind it, and the engine version that ran it. A reconciliation you
cannot explain six months later is not a reconciliation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.store.db import session_scope
from app.store.models import AuditEntry

log = logging.getLogger(__name__)


class AuditTrail:
    def __init__(self, run_id: str, engine_version: str = "1.0.0") -> None:
        self.run_id = run_id
        self.engine_version = engine_version

    def _write(self, **kwargs: Any) -> None:
        try:
            with session_scope() as s:
                s.add(AuditEntry(run_id=self.run_id, engine_version=self.engine_version, **kwargs))
        except Exception as exc:  # noqa: BLE001 - auditing must never fail a run
            log.warning("audit write failed: %s", exc)

    def record_engine_pass(self, outcome: dict[str, Any]) -> None:
        self._write(
            event="ENGINE_PASS", actor="engine", rule="deterministic_cascade",
            detail={
                "counts": outcome.get("counts"),
                "summary": outcome.get("summary"),
                "cascade": outcome.get("cascade"),
                "timings": outcome.get("timings"),
            },
        )

    def record_ai_pass(self, stats: dict[str, Any]) -> None:
        self._write(
            event="AI_PASS", actor="ai_controller", rule="exception_analyzer",
            detail=stats,
        )

    def record_decision(
        self, case_id: str, decision: str, reviewer: str, note: str | None = None
    ) -> None:
        self._write(
            event="HUMAN_DECISION", actor=reviewer, case_id=case_id, rule=decision,
            detail={"note": note},
        )
