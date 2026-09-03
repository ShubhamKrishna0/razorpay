/** Screen 1 — Control Tower.
 *
 * One question, answered above the fold: did today's books close, and what is
 * left for a human? Everything else on the page supports that answer.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAsync, usePolling } from "../hooks/useAsync";
import { ExceptionMixChart } from "../components/charts/ExceptionMixChart";
import { ResolutionBar } from "../components/charts/ResolutionBar";
import {
  Badge, Button, Card, EmptyState, ErrorNote, Spinner, StatTile,
} from "../components/primitives";
import { count, duration, money, moneyShort, pct, rate, relativeTime } from "../lib/format";
import type { RunSummary } from "../api/types";

// 50 is the smallest batch the brief calls for; small batches top up their
// anomaly mix so every exception type still appears. Larger sizes are there to
// show the same engine does not change shape as the data grows.
const SIZES = [
  { n: 50, note: "smallest honest batch — every exception type present" },
  { n: 500, note: "" },
  { n: 10_000, note: "" },
  { n: 100_000, note: "" },
  { n: 1_000_000, note: "local only — needs more than free-tier RAM" },
];

export function ControlTower() {
  const [size, setSize] = useState(500);
  const [useAi, setUseAi] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [lastSeed, setLastSeed] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  const runs = useAsync(() => api.listRuns(10), []);
  const latest: RunSummary | undefined =
    runs.data?.find((r) => r.run_id === activeRunId) ?? runs.data?.[0];
  const runId = latest?.run_id ?? null;
  const inFlight = latest ? !["COMPLETED", "FAILED"].includes(latest.status) : false;

  const detail = useAsync(
    () => (runId ? api.getRun(runId) : Promise.resolve(null)),
    [runId, latest?.status],
  );
  const breakdown = useAsync(
    () => (runId && latest?.status === "COMPLETED"
      ? api.getBreakdown(runId)
      : Promise.resolve(null)),
    [runId, latest?.status],
  );

  // Poll only while something is actually running.
  usePolling(() => runs.refresh(), 1200, inFlight);
  useEffect(() => {
    if (!inFlight) detail.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inFlight]);

  async function launch() {
    setError(null);
    setBusy("Generating dataset…");
    try {
      // A fresh seed per run, so every run is genuinely different data rather
      // than the same fixture replayed. The seed is surfaced below, so any run
      // can still be reproduced exactly.
      const seed = Math.floor(Math.random() * 1_000_000);
      setLastSeed(seed);
      const ds = await api.generateDataset(size, seed, `${count(size)} orders, seed ${seed}`);
      setBusy("Starting reconciliation…");
      const run = await api.startRun(ds.id, useAi, `Reconcile ${ds.label}`);
      setActiveRunId(run.run_id);
      runs.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const totals = breakdown.data?.totals;
  const cases = latest ? latest.matched + latest.exceptions : 0;

  return (
    <div className="space-y-5">
      <Card
        title="Run a reconciliation"
        subtitle="Generate a ground-truth dataset and close the books against it."
        actions={
          latest && (
            <div className="flex items-center gap-2 text-xs text-ink-2">
              <Badge value={latest.status} />
              <span>{relativeTime(latest.created_at)}</span>
            </div>
          )
        }
      >
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor="size" className="block text-[11px] font-medium text-muted">
              Dataset size (orders)
            </label>
            <select
              id="size" value={size} onChange={(e) => setSize(Number(e.target.value))}
              className="mt-1 rounded-md border bg-surface px-2 py-1.5 text-xs text-ink"
              style={{ borderColor: "var(--border-hairline)" }}
            >
              {SIZES.map((s) => (
                <option key={s.n} value={s.n}>
                  {count(s.n)}{s.note ? ` — ${s.note}` : ""}
                </option>
              ))}
            </select>
          </div>

          <label className="flex items-center gap-2 pb-1.5 text-xs text-ink-2">
            <input
              type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)}
              className="h-3.5 w-3.5 accent-[var(--series-1)]"
            />
            Run the AI exception controller
          </label>

          <Button onClick={launch} disabled={busy !== null || inFlight}>
            {busy ?? (inFlight ? "Running…" : "Run reconciliation")}
          </Button>

          {inFlight && <Spinner label={latest?.status ?? "Working"} />}
        </div>

        {lastSeed !== null && (
          <p className="mt-3 text-[11px] text-muted">
            Data generated with seed <span className="tnum font-medium">{lastSeed}</span>. Each
            run draws a new seed, so the figures move; re-run the CLI with{" "}
            <code className="rounded px-1" style={{ background: "var(--gridline)" }}>
              --seed {lastSeed}
            </code>{" "}
            to reproduce this run exactly.
          </p>
        )}

        {error && <div className="mt-3"><ErrorNote message={error} /></div>}
        {latest?.error && <div className="mt-3"><ErrorNote message={latest.error} /></div>}
      </Card>

      {!latest && !runs.loading && (
        <Card>
          <EmptyState
            title="No runs yet"
            body="Generate a dataset above and close the books against it. The engine matches deterministically first, and the AI only sees what the rules could not resolve."
          />
        </Card>
      )}

      {latest && latest.status === "COMPLETED" && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              label="Records processed" value={count(latest.records_total)}
              sub={`${count(cases)} reconciliation cases`}
            />
            <StatTile
              label="Books closed cleanly" value={pct(latest.match_rate)}
              sub={`${count(latest.matched)} cases needed no one`}
              tone={latest.match_rate > 0.9 ? "good" : "warning"}
            />
            <StatTile
              label="Throughput" value={rate(latest.throughput_per_second)}
              sub={`closed in ${duration(latest.duration_seconds)}`}
            />
            <StatTile
              label="Sent to AI" value={pct(latest.ai_coverage, 2)}
              sub={`${count(latest.ai_calls)} model calls — the rest never left our rules`}
              hint="Share of records the AI had to look at. Lower is better — it means the deterministic rules did the work."
            />
          </div>

          {totals && (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile label="Gross ordered" value={moneyShort(totals.gross_order_minor)}
                        sub={money(totals.gross_order_minor)} />
              <StatTile label="Gross paid" value={moneyShort(totals.gross_payment_minor)}
                        sub={money(totals.gross_payment_minor)} />
              <StatTile label="Gross settled" value={moneyShort(totals.gross_settlement_minor)}
                        sub={money(totals.gross_settlement_minor)} />
              <StatTile
                label="Settlement gap" value={moneyShort(totals.settlement_gap_minor)}
                sub="money paid in but not yet deposited — mostly gateway fees"
                tone={totals.settlement_gap_minor > 0 ? "warning" : "neutral"}
              />
            </div>
          )}

          <div className="grid gap-5 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              {breakdown.loading && <Spinner />}
              {breakdown.data && <ExceptionMixChart buckets={breakdown.data.buckets} />}
            </Card>

            <div className="space-y-5">
              <Card>
                <ResolutionBar
                  autoResolved={latest.auto_resolved}
                  aiResolved={latest.ai_resolved}
                  humanReview={latest.human_review}
                  total={cases}
                />
                <div className="mt-4 border-t pt-3" style={{ borderColor: "var(--border-hairline)" }}>
                  <Link
                    to="/exceptions"
                    className="text-xs font-medium underline underline-offset-2"
                    style={{ color: "var(--series-1)" }}
                  >
                    Work the exception queue →
                  </Link>
                </div>
              </Card>

              {detail.data && <CascadePanel manifest={detail.data.manifest} />}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** Where the work actually happened — the cascade's own numbers. */
function CascadePanel({ manifest }: { manifest: Record<string, unknown> }) {
  const cascade = (manifest.cascade ?? {}) as Record<
    string,
    { stage: string; rule: string; matched: number }[]
  >;
  const merged = new Map<string, number>();
  for (const stages of Object.values(cascade)) {
    for (const s of stages) merged.set(s.rule, (merged.get(s.rule) ?? 0) + s.matched);
  }
  const rows = [...merged.entries()].filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((sum, [, n]) => sum + n, 0);

  return (
    <Card
      title="Where the matches came from"
      subtitle="Each cascade level only ever sees what the level above it left behind."
    >
      {rows.length === 0 ? (
        <p className="text-xs text-ink-2">No links formed.</p>
      ) : (
        <ul className="space-y-2">
          {rows.map(([rule, matched]) => (
            <li key={rule}>
              <div className="flex items-baseline justify-between gap-2 text-xs">
                <span className="text-ink-2">{rule.replace(/_/g, " ")}</span>
                <span className="tnum text-ink">{count(matched)}</span>
              </div>
              <div className="mt-1 h-1 w-full rounded" style={{ background: "var(--gridline)" }}>
                <div
                  className="h-1 rounded"
                  style={{
                    background: "var(--series-1)",
                    width: `${(matched / Math.max(total, 1)) * 100}%`,
                  }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
