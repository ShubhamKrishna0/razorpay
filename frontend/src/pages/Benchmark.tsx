/** Screen 4 — Benchmark.
 *
 * The point of this screen is falsifiability. Every number here comes from a
 * sweep the visitor can re-run, measured against injected anomalies whose truth
 * was known before the engine saw the data.
 */

import { useState } from "react";

import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { AccuracyChart, ThroughputChart } from "../components/charts/BenchmarkCharts";
import { Button, Card, EmptyState, ErrorNote, Spinner, StatTile } from "../components/primitives";
import { count, duration, pct, rate } from "../lib/format";

const PRESETS: { label: string; sizes: number[]; note: string }[] = [
  { label: "Quick (1K → 10K)", sizes: [1_000, 10_000], note: "~2 seconds" },
  { label: "Standard (1K → 100K)", sizes: [1_000, 10_000, 100_000], note: "~10 seconds" },
  { label: "Full (1K → 1M)", sizes: [1_000, 10_000, 100_000, 1_000_000], note: "~45 seconds" },
];

export function Benchmark() {
  const [preset, setPreset] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cached = useAsync(() => api.getBenchmark(), []);
  const [rows, setRows] = useState(cached.data?.results ?? []);

  const results = rows.length ? rows : (cached.data?.results ?? []);
  const largest = results.length ? results[results.length - 1] : null;

  async function run() {
    setBusy(true); setError(null);
    try {
      const res = await api.runBenchmark(PRESETS[preset].sizes);
      setRows(res.results);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card
        title="Run the benchmark"
        subtitle="Generates fresh ground-truth data at each size, reconciles it, and scores the output against the injected truth."
      >
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor="preset" className="block text-[11px] font-medium text-muted">
              Sweep
            </label>
            <select
              id="preset" value={preset} onChange={(e) => setPreset(Number(e.target.value))}
              className="mt-1 rounded-md border bg-surface px-2 py-1.5 text-xs text-ink"
              style={{ borderColor: "var(--border-hairline)" }}
            >
              {PRESETS.map((p, i) => (
                <option key={p.label} value={i}>{p.label} — {p.note}</option>
              ))}
            </select>
          </div>
          <Button onClick={run} disabled={busy}>
            {busy ? "Running sweep…" : "Run benchmark"}
          </Button>
          {busy && <Spinner label="Reconciling" />}
        </div>
        {error && <div className="mt-3"><ErrorNote message={error} /></div>}
        <p className="mt-3 text-[11px] leading-relaxed text-muted">
          The AI layer is deliberately excluded from this sweep. Network latency to a model would
          make the throughput figures meaningless — what is measured here is the deterministic
          engine that handles the overwhelming majority of records.
        </p>
      </Card>

      {results.length === 0 && !busy && (
        <Card>
          <EmptyState
            title="No benchmark results yet"
            body="Run a sweep to measure throughput and accuracy across dataset sizes."
          />
        </Card>
      )}

      {largest && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Largest run" value={count(largest.records_total)}
            sub={`${count(largest.dataset_size)} orders, three sources`}
          />
          <StatTile
            label="Throughput" value={rate(largest.throughput_per_second)}
            sub={`closed in ${duration(largest.duration_seconds)}`}
          />
          <StatTile
            label="Precision" value={pct(largest.precision)}
            sub="of cases called clean, how many were"
            tone={largest.precision >= 0.99 ? "good" : "warning"}
          />
          <StatTile
            label="Recall" value={pct(largest.recall)}
            sub="of truly clean cases, how many we found"
            tone={largest.recall >= 0.99 ? "good" : "warning"}
          />
        </div>
      )}

      {results.length > 0 && (
        <>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card><ThroughputChart rows={results} /></Card>
            <Card><AccuracyChart rows={results} /></Card>
          </div>

          <Card
            title="Full results"
            subtitle="Every figure on this page, in one table."
          >
            <div className="scroll-x">
              <table className="w-full min-w-[760px] text-xs">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="py-2 pr-4 font-medium">Orders</th>
                    <th className="py-2 pr-4 text-right font-medium">Records</th>
                    <th className="py-2 pr-4 text-right font-medium">Time</th>
                    <th className="py-2 pr-4 text-right font-medium">Throughput</th>
                    <th className="py-2 pr-4 text-right font-medium">Match rate</th>
                    <th className="py-2 pr-4 text-right font-medium">Precision</th>
                    <th className="py-2 pr-4 text-right font-medium">Recall</th>
                    <th className="py-2 pr-4 text-right font-medium">F1</th>
                    <th className="py-2 text-right font-medium">AI coverage</th>
                  </tr>
                </thead>
                <tbody className="tnum">
                  {results.map((r) => (
                    <tr key={r.dataset_size} className="border-t"
                        style={{ borderColor: "var(--border-hairline)" }}>
                      <td className="py-2 pr-4 text-ink">{count(r.dataset_size)}</td>
                      <td className="py-2 pr-4 text-right text-ink-2">{count(r.records_total)}</td>
                      <td className="py-2 pr-4 text-right text-ink-2">
                        {duration(r.duration_seconds)}
                      </td>
                      <td className="py-2 pr-4 text-right text-ink-2">
                        {rate(r.throughput_per_second)}
                      </td>
                      <td className="py-2 pr-4 text-right text-ink-2">{pct(r.match_rate)}</td>
                      <td className="py-2 pr-4 text-right text-ink-2">{pct(r.precision)}</td>
                      <td className="py-2 pr-4 text-right text-ink-2">{pct(r.recall)}</td>
                      <td className="py-2 pr-4 text-right text-ink-2">{pct(r.f1)}</td>
                      <td className="py-2 text-right text-ink-2">{pct(r.ai_coverage)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-muted">
              <span className="font-medium">AI coverage</span> is the share of cases the engine
              could not close on its own. It is the fraction a model would need to look at — the
              rest never leaves SQL.
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
