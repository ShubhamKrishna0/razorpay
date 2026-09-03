/** Benchmark charts.
 *
 * Throughput and accuracy are measures of completely different scale, so they
 * get two charts. Putting them on one plot with two y-axes would be the single
 * most common charting mistake there is.
 */

import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { count, duration, pct, rate } from "../../lib/format";
import { AXIS, ChartFrame, TooltipBox } from "./ChartFrame";
import type { BenchmarkRow } from "../../api/types";

const sizeLabel = (n: number) =>
  n >= 1_000_000 ? `${n / 1_000_000}M` : n >= 1_000 ? `${n / 1_000}K` : String(n);

export function ThroughputChart({ rows }: { rows: BenchmarkRow[] }) {
  const data = rows.map((r) => ({ ...r, x: sizeLabel(r.dataset_size) }));

  const table = (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-muted">
          <th className="py-1 pr-4 font-medium">Orders</th>
          <th className="py-1 pr-4 text-right font-medium">Records</th>
          <th className="py-1 pr-4 text-right font-medium">Time</th>
          <th className="py-1 text-right font-medium">Throughput</th>
        </tr>
      </thead>
      <tbody className="tnum">
        {rows.map((r) => (
          <tr key={r.dataset_size} className="border-t"
              style={{ borderColor: "var(--border-hairline)" }}>
            <td className="py-1 pr-4 text-ink">{count(r.dataset_size)}</td>
            <td className="py-1 pr-4 text-right text-ink-2">{count(r.records_total)}</td>
            <td className="py-1 pr-4 text-right text-ink-2">{duration(r.duration_seconds)}</td>
            <td className="py-1 text-right text-ink-2">{rate(r.throughput_per_second)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <ChartFrame
      title="Throughput by dataset size"
      caption="Records reconciled per second, end to end. One series — no legend needed."
      table={table}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid stroke="var(--gridline)" vertical={false} />
          <XAxis dataKey="x" tick={AXIS.tick} axisLine={AXIS.line} tickLine={false} />
          <YAxis
            tick={AXIS.tick} axisLine={false} tickLine={false} width={56}
            tickFormatter={(v: number) => (v >= 1000 ? `${Math.round(v / 1000)}K` : String(v))}
          />
          <Tooltip
            cursor={{ stroke: "var(--axis-line)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const r = payload[0].payload as BenchmarkRow;
              return (
                <TooltipBox>
                  <div className="font-medium">{count(r.dataset_size)} orders</div>
                  <div className="tnum mt-1 text-ink-2">{count(r.records_total)} records</div>
                  <div className="tnum text-ink-2">{duration(r.duration_seconds)}</div>
                  <div className="tnum text-ink-2">{rate(r.throughput_per_second)}</div>
                </TooltipBox>
              );
            }}
          />
          <Line
            type="monotone" dataKey="throughput_per_second"
            stroke="var(--series-1)" strokeWidth={2}
            dot={{ r: 4, strokeWidth: 2, fill: "var(--surface-1)", stroke: "var(--series-1)" }}
            activeDot={{ r: 6 }} isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

export function AccuracyChart({ rows }: { rows: BenchmarkRow[] }) {
  const data = rows.map((r) => ({ ...r, x: sizeLabel(r.dataset_size) }));
  const series = [
    { key: "precision", label: "Precision", color: "var(--series-1)" },
    { key: "recall", label: "Recall", color: "var(--series-3)" },
    { key: "label_accuracy", label: "Label accuracy", color: "var(--series-2)" },
  ] as const;

  const table = (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-muted">
          <th className="py-1 pr-4 font-medium">Orders</th>
          <th className="py-1 pr-4 text-right font-medium">Precision</th>
          <th className="py-1 pr-4 text-right font-medium">Recall</th>
          <th className="py-1 pr-4 text-right font-medium">F1</th>
          <th className="py-1 text-right font-medium">Label accuracy</th>
        </tr>
      </thead>
      <tbody className="tnum">
        {rows.map((r) => (
          <tr key={r.dataset_size} className="border-t"
              style={{ borderColor: "var(--border-hairline)" }}>
            <td className="py-1 pr-4 text-ink">{count(r.dataset_size)}</td>
            <td className="py-1 pr-4 text-right text-ink-2">{pct(r.precision)}</td>
            <td className="py-1 pr-4 text-right text-ink-2">{pct(r.recall)}</td>
            <td className="py-1 pr-4 text-right text-ink-2">{pct(r.f1)}</td>
            <td className="py-1 text-right text-ink-2">{pct(r.label_accuracy)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <ChartFrame
      title="Accuracy against ground truth"
      caption="Measured against injected anomalies whose truth is known in advance."
      table={table}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid stroke="var(--gridline)" vertical={false} />
          <XAxis dataKey="x" tick={AXIS.tick} axisLine={AXIS.line} tickLine={false} />
          <YAxis
            domain={[0.9, 1]} tick={AXIS.tick} axisLine={false} tickLine={false} width={48}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
          />
          <Tooltip
            cursor={{ stroke: "var(--axis-line)", strokeWidth: 1 }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              return (
                <TooltipBox>
                  <div className="font-medium">{label} orders</div>
                  {series.map((s) => {
                    const p = payload.find((x) => x.dataKey === s.key);
                    return p ? (
                      <div key={s.key} className="tnum mt-0.5 flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-sm" style={{ background: s.color }}
                              aria-hidden />
                        <span className="text-ink-2">{s.label}</span>
                        <span className="ml-auto">{pct(p.value as number)}</span>
                      </div>
                    ) : null;
                  })}
                </TooltipBox>
              );
            }}
          />
          {series.map((s) => (
            <Line
              key={s.key} type="monotone" dataKey={s.key} name={s.label}
              stroke={s.color} strokeWidth={2}
              dot={{ r: 4, strokeWidth: 2, fill: "var(--surface-1)", stroke: s.color }}
              activeDot={{ r: 6 }} isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      {/* Legend lives outside the plot so it never overlaps a mark. */}
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {series.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5 text-xs text-ink-2">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} aria-hidden />
            {s.label}
          </li>
        ))}
      </ul>
    </ChartFrame>
  );
}
