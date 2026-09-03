/** Shared chart chrome: title, optional table-view toggle, and the plot area.
 *
 * The table toggle is not a nicety. Two series colours in light mode sit below
 * 3:1 against the surface, and the palette rule for that is "relief required":
 * ship visible labels or a table view. We ship both.
 */

import { useState, type ReactNode } from "react";

export function ChartFrame({
  title, caption, table, children, height = 260,
}: {
  title: string;
  caption?: string;
  table?: ReactNode;
  children: ReactNode;
  height?: number;
}) {
  const [showTable, setShowTable] = useState(false);

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {caption && <p className="mt-0.5 text-xs text-ink-2">{caption}</p>}
        </div>
        {table && (
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            className="shrink-0 text-[11px] underline underline-offset-2 text-ink-2 hover:text-ink"
            aria-expanded={showTable}
          >
            {showTable ? "Show chart" : "Show table"}
          </button>
        )}
      </div>
      {showTable && table ? (
        <div className="scroll-x">{table}</div>
      ) : (
        <div style={{ height }}>{children}</div>
      )}
    </div>
  );
}

/** Tooltip surface shared by every chart, so hover looks identical everywhere. */
export function TooltipBox({ children }: { children: ReactNode }) {
  return (
    <div
      className="rounded-md border px-2.5 py-2 text-xs shadow-sm"
      style={{
        background: "var(--surface-1)",
        borderColor: "var(--border-hairline)",
        color: "var(--text-primary)",
      }}
    >
      {children}
    </div>
  );
}

export const AXIS = {
  tick: { fill: "var(--text-muted)", fontSize: 11 },
  line: { stroke: "var(--axis-line)" },
} as const;
