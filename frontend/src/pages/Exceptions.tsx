/** Screen 2 — the exception queue.
 *
 * Ordered by money at risk, because that is the order a controller works in.
 * Every row can be drilled into for the arithmetic, the AI's reasoning, and the
 * validation rule that either accepted or rejected that reasoning.
 */

import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { RunPicker } from "../components/RunPicker";
import {
  Badge, Button, Card, EmptyState, ErrorNote, Spinner,
} from "../components/primitives";
import { count, money, pct, titleize } from "../lib/format";
import { exceptionLabel, exceptionMeaning } from "../lib/glossary";
import type { ExceptionRow } from "../api/types";

const TYPES = [
  "", "AMOUNT_MISMATCH", "PARTIAL_PAYMENT", "OVERPAYMENT", "DUPLICATE",
  "MISSING_PAYMENT", "MISSING_SETTLEMENT", "ORPHAN_PAYMENT", "ORPHAN_SETTLEMENT",
  "SETTLEMENT_SHORTFALL", "FEE_VARIANCE", "TIMING_MISMATCH", "MERCHANT_MISMATCH", "REFUND",
];
const RESOLUTIONS = ["", "HUMAN_REVIEW", "AI_RESOLVED", "AUTO_RESOLVED", "HUMAN_RESOLVED"];
const PAGE = 25;

export function Exceptions() {
  const [runId, setRunId] = useState<string | null>(null);
  const [type, setType] = useState("");
  const [resolution, setResolution] = useState("HUMAN_REVIEW");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<ExceptionRow | null>(null);

  const runs = useAsync(() => api.listRuns(20), []);
  useEffect(() => {
    if (!runId && runs.data?.length) {
      const done = runs.data.find((r) => r.status === "COMPLETED");
      if (done) setRunId(done.run_id);
    }
  }, [runs.data, runId]);

  const page = useAsync(
    () =>
      runId
        ? api.listExceptions(runId, {
            exception_type: type || undefined,
            resolution: resolution || undefined,
            offset, limit: PAGE,
          })
        : Promise.resolve(null),
    [runId, type, resolution, offset],
  );

  useEffect(() => setOffset(0), [type, resolution, runId]);

  return (
    <div className="space-y-4">
      {/* Filters in one row above the content. */}
      <Card>
        <div className="flex flex-wrap items-end gap-4">
          <RunPicker value={runId} onChange={setRunId} />
          <div>
            <label htmlFor="f-type" className="block text-[11px] font-medium text-muted">
              Exception type
            </label>
            <select
              id="f-type" value={type} onChange={(e) => setType(e.target.value)}
              className="mt-1 rounded-md border bg-surface px-2 py-1.5 text-xs text-ink"
              style={{ borderColor: "var(--border-hairline)" }}
            >
              {TYPES.map((t) => (
                <option key={t || "all"} value={t}>{t ? exceptionLabel(t) : "All types"}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="f-res" className="block text-[11px] font-medium text-muted">
              Lane
            </label>
            <select
              id="f-res" value={resolution} onChange={(e) => setResolution(e.target.value)}
              className="mt-1 rounded-md border bg-surface px-2 py-1.5 text-xs text-ink"
              style={{ borderColor: "var(--border-hairline)" }}
            >
              {RESOLUTIONS.map((r) => (
                <option key={r || "all"} value={r}>{r ? titleize(r) : "All lanes"}</option>
              ))}
            </select>
          </div>
          {page.data && (
            <span className="pb-1.5 text-xs text-ink-2">
              {count(page.data.total)} matching cases
            </span>
          )}
        </div>
      </Card>

      {page.error && <ErrorNote message={page.error} />}
      {page.loading && <Card><Spinner label="Loading exceptions" /></Card>}

      {page.data && page.data.items.length === 0 && (
        <Card>
          <EmptyState
            title="Nothing in this lane"
            body="Either the engine closed everything here, or the filters are too narrow."
          />
        </Card>
      )}

      {page.data && page.data.items.length > 0 && (
        <Card
          title="Exception queue"
          subtitle="Ordered by money at risk."
          actions={
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => setOffset(Math.max(0, offset - PAGE))}
                      disabled={offset === 0}>
                Previous
              </Button>
              <span className="tnum text-[11px] text-muted">
                {offset + 1}–{Math.min(offset + PAGE, page.data.total)}
              </span>
              <Button variant="ghost" onClick={() => setOffset(offset + PAGE)}
                      disabled={offset + PAGE >= page.data.total}>
                Next
              </Button>
            </div>
          }
        >
          <div className="scroll-x">
            <table className="w-full min-w-[820px] text-xs">
              <thead>
                <tr className="text-left text-muted">
                  <th className="py-2 pr-3 font-medium">Case</th>
                  <th className="py-2 pr-3 font-medium">Type</th>
                  <th className="py-2 pr-3 font-medium">Merchant</th>
                  <th className="py-2 pr-3 text-right font-medium">Ordered</th>
                  <th className="py-2 pr-3 text-right font-medium">Paid</th>
                  <th className="py-2 pr-3 text-right font-medium">Settled</th>
                  <th className="py-2 pr-3 font-medium">Lane</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody className="tnum">
                {page.data.items.map((row) => (
                  <tr
                    key={row.case_id}
                    className="border-t transition-colors hover:bg-[var(--gridline)]"
                    style={{ borderColor: "var(--border-hairline)" }}
                  >
                    <td className="py-2 pr-3 font-mono text-[11px] text-ink">{row.case_id}</td>
                    <td className="py-2 pr-3 text-ink-2"
                        title={exceptionMeaning(row.exception_type)?.meaning}>
                      {exceptionLabel(row.exception_type)}
                    </td>
                    <td className="py-2 pr-3 text-ink-2">{row.merchant_id ?? "—"}</td>
                    <td className="py-2 pr-3 text-right text-ink-2">
                      {money(row.order_amount_minor)}
                    </td>
                    <td className="py-2 pr-3 text-right text-ink-2">
                      {money(row.payment_amount_minor)}
                    </td>
                    <td className="py-2 pr-3 text-right text-ink-2">
                      {money(row.settlement_amount_minor)}
                    </td>
                    <td className="py-2 pr-3"><Badge value={row.resolution} /></td>
                    <td className="py-2 text-right">
                      <Button variant="ghost" onClick={() => setSelected(row)}>Inspect</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {selected && runId && (
        <CaseDrawer
          runId={runId}
          row={selected}
          onClose={() => setSelected(null)}
          onChanged={() => { page.refresh(); setSelected(null); }}
        />
      )}
    </div>
  );
}

function CaseDrawer({
  runId, row, onClose, onChanged,
}: {
  runId: string;
  row: ExceptionRow;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [current, setCurrent] = useState(row);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function investigate() {
    setBusy("Asking the model"); setError(null);
    try {
      await api.investigate(runId, current.case_id);
      setCurrent(await api.getException(runId, current.case_id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function decide(decision: string) {
    setBusy("Recording decision"); setError(null);
    try {
      await api.review(runId, current.case_id, decision);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  // When nothing settled, there is no fee to net off — the gateway never
  // charged one. Subtracting it anyway under-reports the exposure, which is
  // the wrong direction for a finance tool to be wrong in.
  const settled = current.settlement_amount_minor !== null;
  const unexplained = settled
    ? (current.settlement_delta_minor ?? 0) - (current.expected_fee_minor ?? 0)
    : (current.payment_amount_minor ?? 0);

  return (
    <div
      className="fixed inset-0 z-30 flex justify-end bg-black/40"
      role="dialog" aria-modal="true" aria-label={`Case ${current.case_id}`}
      onClick={onClose}
    >
      <div
        className="h-full w-full max-w-lg overflow-y-auto border-l bg-surface p-5"
        style={{ borderColor: "var(--border-hairline)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="font-mono text-sm font-semibold text-ink">{current.case_id}</h2>
            <p className="mt-1 text-xs text-ink-2">
              {exceptionLabel(current.exception_type)} · {current.merchant_id ?? "unknown merchant"}
            </p>
          </div>
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>

        {(() => {
          const g = exceptionMeaning(current.exception_type);
          return g ? (
            <div className="mt-4 rounded-md border p-3"
                 style={{ borderColor: "var(--border-hairline)" }}>
              <p className="text-xs leading-relaxed text-ink">{g.meaning}</p>
              <p className="mt-1.5 text-[11px] leading-relaxed text-ink-2">
                <span className="font-semibold">What to do:</span> {g.action}
              </p>
            </div>
          ) : null;
        })()}

        <dl className="tnum mt-5 space-y-2 text-xs">
          <Row label="Order amount" value={money(current.order_amount_minor)} />
          <Row label="Payment amount" value={money(current.payment_amount_minor)} />
          <Row label="Settlement amount" value={money(current.settlement_amount_minor)} />
          <Row label="Declared fee" value={money(current.expected_fee_minor)} />
          <Row label="Payment vs order" value={money(current.payment_delta_minor)} />
          <Row
            label="Payment vs settlement"
            value={settled ? money(current.settlement_delta_minor) : "no settlement"}
          />
          <Row
            label={settled ? "Unexplained after fee" : "Outstanding — never settled"}
            value={money(unexplained)}
            emphasis={Math.abs(unexplained) > 100}
          />
          <Row
            label="Match confidence"
            value={
              current.confidence && current.confidence > 0
                ? pct(current.confidence, 1)
                : "no link — record stands alone"
            }
          />
        </dl>

        <div className="mt-5 rounded-md border p-3" style={{ borderColor: "var(--border-hairline)" }}>
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-ink">AI analysis</h3>
            <Badge value={current.resolution} />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-2">
            {current.ai_explanation
              ? current.ai_explanation
              : current.ai_eligible
                ? "Queued for analysis — not sent to the model yet."
                : "Not sent to the model. A record that simply is not there needs "
                  + "a person to go find it, not an explanation of the arithmetic."}
          </p>
          {current.ai_evidence?.length > 0 && (
            <ul className="mt-2 space-y-1">
              {current.ai_evidence.map((ev, i) => (
                <li key={i} className="flex gap-1.5 text-[11px] text-ink-2">
                  <span style={{ color: "var(--status-good)" }} aria-hidden>✓</span>
                  {ev}
                </li>
              ))}
            </ul>
          )}
          {current.ai_confidence !== null && current.ai_confidence > 0 && (
            <p className="tnum mt-2 text-[11px] text-muted">
              Model confidence {pct(current.ai_confidence, 0)}
            </p>
          )}
          {current.validation_reason && (
            <p className="mt-2 border-t pt-2 text-[11px] text-muted"
               style={{ borderColor: "var(--border-hairline)" }}>
              <span className="font-medium">Validation gate:</span> {current.validation_reason}
            </p>
          )}
          {current.suggested_action && (
            <p className="mt-2 text-[11px] text-ink-2">
              <span className="font-medium">Suggested:</span> {current.suggested_action}
            </p>
          )}
        </div>

        {error && <div className="mt-3"><ErrorNote message={error} /></div>}

        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="ghost" onClick={investigate} disabled={busy !== null}
                  title="Send this one case to the AI for an explanation. Its answer is a recommendation — it cannot close the case by itself.">
            {busy === "Asking the model" ? "Asking…" : "Ask the AI to explain"}
          </Button>
          <Button onClick={() => decide("RESOLVED")} disabled={busy !== null}
                  title="You have verified this case. It will be marked closed under your name in the audit trail.">
            Mark resolved
          </Button>
          <Button variant="ghost" onClick={() => decide("ESCALATED")} disabled={busy !== null}
                  title="Keep it open and flag it for a senior review.">
            Escalate
          </Button>
          <Button variant="danger" onClick={() => decide("REJECTED")} disabled={busy !== null}
                  title="The AI's suggestion is wrong. Keeps the case open and records your disagreement.">
            Reject suggestion
          </Button>
        </div>

        <p className="mt-4 text-[11px] leading-relaxed text-muted">
          Every decision here is recorded under your name in the audit trail and written back to
          the books. The AI can suggest — only rules-checked arithmetic or a person can close.
        </p>
      </div>
    </div>
  );
}

function Row({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-ink-2">{label}</dt>
      <dd
        className="font-medium"
        style={{ color: emphasis ? "var(--status-critical)" : "var(--text-primary)" }}
      >
        {value}
      </dd>
    </div>
  );
}
