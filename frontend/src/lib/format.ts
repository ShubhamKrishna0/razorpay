/** Formatting helpers.
 *
 * Amounts cross the wire as integer minor units (paise). They are converted to
 * a display string exactly once, here — never parsed back into arithmetic.
 */

const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

export function money(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return "—";
  return INR.format(minor / 100);
}

/** Compact Indian-numbering form for headline figures. */
export function moneyShort(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return "—";
  const rupees = minor / 100;
  const abs = Math.abs(rupees);
  if (abs >= 1e7) return `₹${(rupees / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(rupees / 1e5).toFixed(2)} L`;
  if (abs >= 1e3) return `₹${(rupees / 1e3).toFixed(1)}K`;
  return INR.format(rupees);
}

export function count(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("en-IN").format(n);
}

export function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function rate(n: number | null | undefined): string {
  if (!n) return "—";
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M/s`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K/s`;
  return `${Math.round(n)}/s`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)} ms`;
  if (seconds < 60) return `${seconds.toFixed(2)} s`;
  const m = Math.floor(seconds / 60);
  return `${m}m ${(seconds % 60).toFixed(0)}s`;
}

export function titleize(s: string | null | undefined): string {
  if (!s) return "—";
  return s
    .split("_")
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(" ");
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}
