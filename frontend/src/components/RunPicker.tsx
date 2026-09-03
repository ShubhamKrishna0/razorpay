import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { Badge } from "./primitives";
import { relativeTime } from "../lib/format";

export function RunPicker({
  value, onChange, className = "",
}: {
  value: string | null;
  onChange: (runId: string) => void;
  className?: string;
}) {
  const { data: runs } = useAsync(() => api.listRuns(30), []);
  const completed = runs?.filter((r) => r.status === "COMPLETED") ?? [];
  const current = runs?.find((r) => r.run_id === value);

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <label htmlFor="run-picker" className="text-xs text-ink-2">
        Run
      </label>
      <select
        id="run-picker"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border bg-surface px-2 py-1 text-xs text-ink"
        style={{ borderColor: "var(--border-hairline)" }}
      >
        <option value="" disabled>
          Select a completed run…
        </option>
        {completed.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {r.run_id} — {r.label ?? "run"} ({relativeTime(r.created_at)})
          </option>
        ))}
      </select>
      {current && <Badge value={current.status} />}
    </div>
  );
}
