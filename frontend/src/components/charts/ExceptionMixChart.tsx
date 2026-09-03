/** Exception mix — magnitude by category.
 *
 * Horizontal bars: the category labels are words, and words read horizontally.
 * One series, so no legend — the title names it. Values are direct-labelled on
 * every bar because there are few enough for that to stay readable.
 */

import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

import { count, money } from "../../lib/format";
import { exceptionLabel } from "../../lib/glossary";
import { AXIS, ChartFrame, TooltipBox } from "./ChartFrame";
import type { BreakdownBucket } from "../../api/types";

interface Row {
  label: string;
  raw: string;
  count: number;
  impact_minor: number;
  clean: boolean;
}

function toRows(buckets: BreakdownBucket[]): Row[] {
  const merged = new Map<string, Row>();
  for (const b of buckets) {
    const existing = merged.get(b.exception_type);
    if (existing) {
      existing.count += b.count;
      existing.impact_minor += b.impact_minor;
    } else {
      merged.set(b.exception_type, {
        label: exceptionLabel(b.exception_type),
        raw: b.exception_type,
        count: b.count,
        impact_minor: b.impact_minor,
        clean: b.exception_type === "MATCHED",
      });
    }
  }
  return [...merged.values()]
    .filter((r) => !r.clean)
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);
}

export function ExceptionMixChart({ buckets }: { buckets: BreakdownBucket[] }) {
  const rows = toRows(buckets);

  if (rows.length === 0) {
    return (
      <ChartFrame title="Exception mix" caption="Every case reconciled cleanly.">
        <p className="py-10 text-center text-xs text-ink-2">No exceptions in this run.</p>
      </ChartFrame>
    );
  }

  const table = (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-muted">
          <th className="py-1 pr-4 font-medium">Exception</th>
          <th className="py-1 pr-4 text-right font-medium">Cases</th>
          <th className="py-1 text-right font-medium">Exposure</th>
        </tr>
      </thead>
      <tbody className="tnum">
        {rows.map((r) => (
          <tr key={r.raw} className="border-t" style={{ borderColor: "var(--border-hairline)" }}>
            <td className="py-1 pr-4 text-ink">{r.label}</td>
            <td className="py-1 pr-4 text-right text-ink-2">{count(r.count)}</td>
            <td className="py-1 text-right text-ink-2">{money(r.impact_minor)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <ChartFrame
      title="Exception mix"
      caption="What went wrong, in plain terms — hover a bar for the money involved."
      height={Math.max(200, rows.length * 30 + 32)}
      table={table}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 8 }}>
          <CartesianGrid horizontal={false} stroke="var(--gridline)" strokeWidth={1} />
          <XAxis type="number" tick={AXIS.tick} axisLine={AXIS.line} tickLine={false} />
          <YAxis
            type="category" dataKey="label" width={150}
            tick={AXIS.tick} axisLine={false} tickLine={false}
          />
          <Tooltip
            cursor={{ fill: "var(--gridline)", opacity: 0.4 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const r = payload[0].payload as Row;
              return (
                <TooltipBox>
                  <div className="font-medium">{r.label}</div>
                  <div className="tnum mt-1 text-ink-2">{count(r.count)} cases</div>
                  <div className="tnum text-ink-2">{money(r.impact_minor)} exposure</div>
                </TooltipBox>
              );
            }}
          />
          {/* Rounded data-end anchored to the baseline; thin bars. */}
          <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={16} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.raw} fill="var(--series-1)" />
            ))}
            <LabelList
              dataKey="count"
              position="right"
              formatter={(v: number) => count(v)}
              style={{ fill: "var(--text-secondary)", fontSize: 11 }}
              className="tnum"
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
