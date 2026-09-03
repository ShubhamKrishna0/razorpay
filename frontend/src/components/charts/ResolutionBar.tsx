/** How every case was closed — one 100% stacked bar.
 *
 * Three lanes, so a legend is present AND each segment is direct-labelled;
 * identity is never carried by colour alone. Segments are separated by a 2px
 * surface gap so adjacent fills never touch.
 */

import { count, pct } from "../../lib/format";

interface Lane {
  key: string;
  label: string;
  value: number;
  color: string;
}

export function ResolutionBar({
  autoResolved, aiResolved, humanReview, total,
}: {
  autoResolved: number;
  aiResolved: number;
  humanReview: number;
  total: number;
}) {
  const lanes: Lane[] = [
    { key: "auto", label: "Closed by rules — no one needs to look", value: autoResolved, color: "var(--series-1)" },
    { key: "ai", label: "Closed by AI — arithmetic re-checked", value: aiResolved, color: "var(--series-3)" },
    { key: "human", label: "Needs a person to decide", value: humanReview, color: "var(--series-2)" },
  ];
  const denom = Math.max(total, 1);
  const visible = lanes.filter((l) => l.value > 0);

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-ink">Who closed what</h3>
        <span className="tnum text-xs text-ink-2">{count(total)} cases</span>
      </div>

      <div className="flex h-6 w-full gap-[2px] overflow-hidden rounded" role="img"
           aria-label={visible.map((l) => `${l.label}: ${pct(l.value / denom, 1)}`).join(", ")}>
        {visible.map((lane) => (
          <div
            key={lane.key}
            style={{ background: lane.color, width: `${(lane.value / denom) * 100}%` }}
            title={`${lane.label}: ${count(lane.value)} (${pct(lane.value / denom, 1)})`}
          />
        ))}
      </div>

      {(() => {
        const machineClosed = autoResolved + aiResolved;
        const pctClosed = machineClosed / denom;
        return (
          <p className="mt-3 text-xs leading-relaxed text-ink">
            Without this system, a person would review all{" "}
            <span className="tnum font-semibold">{count(total)}</span> cases. Now they review{" "}
            <span className="tnum font-semibold">{count(humanReview)}</span> —{" "}
            <span className="font-semibold" style={{ color: "var(--success-text, var(--status-good))" }}>
              {pct(pctClosed, 1)} of the review workload eliminated
            </span>
            , and every remaining case arrives with the arithmetic done and an action suggested.
          </p>
        );
      })()}

      <ul className="mt-3 space-y-1.5">
        {lanes.map((lane) => (
          <li key={lane.key} className="flex items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-2 text-ink-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: lane.color }}
                    aria-hidden />
              {lane.label}
            </span>
            <span className="tnum shrink-0 text-ink">
              {count(lane.value)}
              <span className="ml-1.5 text-muted">{pct(lane.value / denom, 1)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
