/** Screen 3 — Finance Chat.
 *
 * The model answers over aggregates the API assembles, never over the raw
 * dataset. That context is inspectable from this page on purpose: if the model
 * can only see this, anyone can check the answers are grounded.
 */

import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { RunPicker } from "../components/RunPicker";
import { Button, Card, ErrorNote, Spinner } from "../components/primitives";
import { money } from "../lib/format";
import type { ChatResponse } from "../api/types";

const SUGGESTIONS = [
  "Why is today's settlement lower than what we were paid?",
  "Which merchants account for most of the unreconciled money?",
  "What still needs a human, and how much is at stake?",
  "Break down the settlement gap by exception type.",
];

interface Turn {
  question: string;
  answer: ChatResponse | null;
  error?: string;
}

export function Chat() {
  const [runId, setRunId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [showContext, setShowContext] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const runs = useAsync(() => api.listRuns(20), []);
  useEffect(() => {
    if (!runId && runs.data?.length) {
      const done = runs.data.find((r) => r.status === "COMPLETED");
      if (done) setRunId(done.run_id);
    }
  }, [runs.data, runId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  async function ask(q: string) {
    if (!runId || !q.trim() || busy) return;
    setBusy(true);
    setQuestion("");
    setTurns((t) => [...t, { question: q, answer: null }]);
    try {
      const answer = await api.chat(runId, q);
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer } : turn)));
    } catch (e) {
      const msg = (e as Error).message;
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: msg } : turn)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <RunPicker value={runId} onChange={setRunId} />
          <button
            type="button"
            onClick={() => setShowContext((v) => !v)}
            className="text-[11px] underline underline-offset-2 text-ink-2 hover:text-ink"
          >
            {showContext ? "Hide" : "Show"} the exact context the model receives
          </button>
        </div>
        {showContext && runId && <ContextPreview runId={runId} />}
      </Card>

      <Card
        title="Finance control assistant"
        subtitle="Answers are grounded in this run's aggregates. Nothing is inferred from outside them."
      >
        <div className="min-h-[240px] space-y-4">
          {turns.length === 0 && (
            <div className="space-y-3 py-4">
              <p className="text-xs text-ink-2">Ask about this run, for example:</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s} type="button" onClick={() => ask(s)} disabled={!runId}
                    className="rounded-full border px-3 py-1.5 text-left text-[11px] text-ink-2 transition-colors hover:text-ink disabled:opacity-45"
                    style={{ borderColor: "var(--border-hairline)" }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn, i) => (
            <div key={i} className="space-y-2">
              <p className="text-xs font-medium text-ink">{turn.question}</p>
              {turn.error && <ErrorNote message={turn.error} />}
              {!turn.answer && !turn.error && <Spinner label="Thinking" />}
              {turn.answer && <AnswerBlock answer={turn.answer} onFollowup={ask} />}
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <form
          className="mt-4 flex gap-2 border-t pt-4"
          style={{ borderColor: "var(--border-hairline)" }}
          onSubmit={(e) => { e.preventDefault(); ask(question); }}
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={runId ? "Ask about this run…" : "Select a completed run first"}
            disabled={!runId || busy}
            className="flex-1 rounded-md border bg-surface px-3 py-2 text-xs text-ink placeholder:text-muted"
            style={{ borderColor: "var(--border-hairline)" }}
          />
          <Button type="submit" disabled={!runId || busy || !question.trim()}>Ask</Button>
        </form>
      </Card>
    </div>
  );
}

function AnswerBlock({
  answer, onFollowup,
}: {
  answer: ChatResponse;
  onFollowup: (q: string) => void;
}) {
  return (
    <div
      className="rounded-md border p-3"
      style={{
        borderColor: answer.degraded ? "var(--status-warning)" : "var(--border-hairline)",
      }}
    >
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink">{answer.answer}</p>

      {answer.breakdown.length > 0 && (
        <ul className="tnum mt-3 space-y-1 border-t pt-2"
            style={{ borderColor: "var(--border-hairline)" }}>
          {answer.breakdown.map((line, i) => (
            <li key={i} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-ink-2">{line.label}</span>
              <span className="text-ink">
                {money(line.amount_minor)}
                {line.count > 0 && <span className="ml-2 text-muted">{line.count} cases</span>}
              </span>
            </li>
          ))}
        </ul>
      )}

      {answer.used_figures.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-[11px] text-muted">
            Figures quoted from the run context
          </summary>
          <ul className="mt-1 space-y-0.5">
            {answer.used_figures.map((f, i) => (
              <li key={i} className="text-[11px] text-ink-2">· {f}</li>
            ))}
          </ul>
        </details>
      )}

      {answer.followups.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {answer.followups.map((f) => (
            <button
              key={f} type="button" onClick={() => onFollowup(f)}
              className="rounded-full border px-2.5 py-1 text-[11px] text-ink-2 hover:text-ink"
              style={{ borderColor: "var(--border-hairline)" }}
            >
              {f}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ContextPreview({ runId }: { runId: string }) {
  const { data, loading, error } = useAsync(
    () =>
      fetch(
        `${(import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "")}/api/finance/context/${runId}`,
      ).then((r) => r.json()),
    [runId],
  );
  if (loading) return <Spinner label="Loading context" />;
  if (error) return <ErrorNote message={error} />;
  return (
    <pre
      className="scroll-x mt-3 max-h-72 overflow-y-auto rounded-md border p-3 text-[10px] leading-relaxed text-ink-2"
      style={{ borderColor: "var(--border-hairline)" }}
    >
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
