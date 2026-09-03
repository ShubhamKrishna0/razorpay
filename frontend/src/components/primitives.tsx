/** Small shared UI pieces. Kept in one file so the pages stay readable. */

import type { ReactNode } from "react";

import { LANE_GLOSSARY } from "../lib/glossary";

export function Card({
  title, subtitle, actions, children, className = "",
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border bg-surface ${className}`}
      style={{ borderColor: "var(--border-hairline)" }}
    >
      {(title || actions) && (
        <header
          className="flex items-start justify-between gap-4 border-b px-4 py-3"
          style={{ borderColor: "var(--border-hairline)" }}
        >
          <div>
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-2">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function StatTile({
  label, value, sub, tone = "neutral", hint,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "good" | "warning" | "critical";
  hint?: string;
}) {
  // Status colour never carries the meaning alone — it sits beside a label.
  const toneVar =
    tone === "good" ? "var(--status-good)"
    : tone === "warning" ? "var(--status-warning)"
    : tone === "critical" ? "var(--status-critical)"
    : "var(--text-primary)";

  return (
    <div
      className="rounded-lg border bg-surface px-4 py-3"
      style={{ borderColor: "var(--border-hairline)" }}
      title={hint}
    >
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className="tnum mt-1 text-2xl font-semibold leading-tight" style={{ color: toneVar }}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-ink-2">{sub}</div>}
    </div>
  );
}

const BADGE_TONES: Record<string, string> = {
  AUTO_RESOLVED: "var(--status-good)",
  AI_RESOLVED: "var(--series-1)",
  HUMAN_RESOLVED: "var(--status-good)",
  HUMAN_REVIEW: "var(--status-warning)",
  UNRESOLVED: "var(--text-muted)",
  COMPLETED: "var(--status-good)",
  FAILED: "var(--status-critical)",
  QUEUED: "var(--text-muted)",
};

export function Badge({ value, tone }: { value: string; tone?: string }) {
  const color = tone ?? BADGE_TONES[value] ?? "var(--text-secondary)";
  const glossary = LANE_GLOSSARY[value];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium"
      style={{ borderColor: color, color }}
      title={glossary?.meaning}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} aria-hidden />
      {glossary?.label ?? value.replace(/_/g, " ").toLowerCase()}
    </span>
  );
}

export function Button({
  children, onClick, variant = "primary", disabled, type = "button", title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
}) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium " +
    "transition-colors disabled:cursor-not-allowed disabled:opacity-45";
  const styles =
    variant === "primary"
      ? { background: "var(--series-1)", color: "#ffffff", border: "1px solid var(--series-1)" }
      : variant === "danger"
        ? { background: "transparent", color: "var(--status-critical)",
            border: "1px solid var(--status-critical)" }
        : { background: "transparent", color: "var(--text-secondary)",
            border: "1px solid var(--border-hairline)" };

  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title}
            className={base} style={styles}>
      {children}
    </button>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-xs text-ink-2">
      <span
        className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-transparent"
        style={{ borderTopColor: "var(--series-1)", borderRightColor: "var(--series-1)" }}
        aria-hidden
      />
      {label}…
    </div>
  );
}

export function EmptyState({ title, body, action }: {
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {body && <p className="max-w-md text-xs text-ink-2">{body}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div
      className="rounded-md border px-3 py-2 text-xs"
      style={{ borderColor: "var(--status-critical)", color: "var(--status-critical)" }}
      role="alert"
    >
      <strong className="font-semibold">Error</strong> — {message}
    </div>
  );
}
