# AI Finance Controller

A high-throughput reconciliation engine with an AI exception controller.

The design principle is one sentence:

> **Deterministic SQL closes the books at scale; the AI investigates only what the
> rules cannot, and it never closes a case on its own.**

On a 1M-order dataset (≈3M records across orders, payments and settlements) the
engine reconciles end to end in **~20 seconds at ~146,000 records/second**, with
**precision 0.999 / recall 1.000** measured against injected anomalies whose truth
was known before the engine saw the data. The AI layer is asked about **~5%** of
cases. The rest never leave SQL.

---

## How this answers Track 04

> *Build an agent that closes one finance-ops loop across a 50+ record batch of
> synthetic data, reporting its match rate and the exceptions it could not resolve.*

**No spreadsheet is required, and none should be uploaded.** The brief asks for
*synthetic* data, and the system generates its own — with the anomalies labelled
before the engine ever sees them. That is a stronger position than supplying a
sheet: a sheet you bring has no ground truth, so nobody can check whether a match
was correct. Ours can be checked, which is the only way to answer "measured
accuracy" honestly.

If a judge wants to bring their own file, `POST /api/datasets/upload` takes three
CSVs and auto-detects the columns. It just cannot report precision or recall on
that data, because there is nothing to score against — and the UI says so rather
than inventing a number.

### The finance-ops loop this closes

```
three sources → normalize → match → classify → adjudicate → human queue → decision
     ↑                                                                        │
     └──────────────── written back to the reconciliation ────────────────────┘
```

Order-to-payment-to-settlement reconciliation, end to end, with the loop actually
closing: a human decision in the exception queue is written back into the run's
artifact and recorded in the audit trail.

### The bar, item by item

| The bar | Where it is met | On a 50-record batch |
|---|---|---|
| **Throughput** | Benchmark screen and `make bench`, swept 50 → 1M records | 1,907 rec/s (small batches are dominated by fixed startup cost; the curve reaches ~146,000/s) |
| **Measured accuracy** | Scored against retained ground truth, not eyeballed | Precision 1.000 · Recall 1.000 · Label accuracy 1.000 |
| **Honest exception list** | Every unresolved case typed, costed, and queued with a reason | 17 exceptions across 11 distinct types |
| **Not one cherry-picked match** | A size sweep plus a confusion matrix, both reproducible | Every exception type present, not just the easy ones |

### Two example directions, not one

- **Multi-source reconciliation** — the core engine (orders × payments × settlements).
- **Settlement Q&A agent** — the Finance Chat screen answers questions over a
  completed run, with the exact model context inspectable from the same page.

### Why a small batch still exercises everything

At the natural anomaly rates, a 50-record batch would contain zero duplicates and
zero fee variances — most exception types simply would not appear, and the
"exception list" would be a thin, unconvincing thing. So the generator runs a
**top-up pass on small batches**: after the probabilistic assignment, any anomaly
type with zero occurrences is forced into one still-clean record.

This is disclosed rather than hidden, for two reasons. It raises the anomaly rate
on a small batch above what production looks like (~31% versus ~9%), and it does
nothing at all on a large batch, where every type already appears — so the 1M-row
figures in the table above are untouched by it. The injected counts are recorded
in each dataset's manifest.

### Suggested demo, five minutes

1. **50 records.** Run it. Point at the exception list: 11 types, each with the
   arithmetic behind it. This is the "honest exception list" bar, and it fits on
   one screen.
2. **Open one exception.** Show the declared-fee-versus-contracted-fee reasoning,
   the AI's explanation, and — most importantly — the validation gate line that
   says whether the rules *accepted* that explanation.
3. **Ask the chat** why settlements are lower than payments. Then hit "show the
   exact context the model receives" to prove the answer is grounded.
4. **Benchmark screen, 1K → 100K.** Same engine, same accuracy, 100,000+ records/s.
5. **Close on the failure list.** The known-limits section below is deliberate:
   ~0.15% of fuzzy matches are wrong at the tail, and they are visible in the
   confusion matrix rather than hidden.

---

## Table of contents

- [How this answers Track 04](#how-this-answers-track-04)
- [Why it is built this way](#why-it-is-built-this-way)
- [Architecture](#architecture)
- [The matching cascade](#the-matching-cascade)
- [The exception state machine](#the-exception-state-machine)
- [How the AI is constrained](#how-the-ai-is-constrained)
- [Measured results](#measured-results)
- [Project layout](#project-layout)
- [Running it locally](#running-it-locally)
- [Configuration](#configuration)
- [Deploying to Render](#deploying-to-render)
- [API reference](#api-reference)
- [Testing](#testing)
- [Known limits](#known-limits)

---

## Why it is built this way

The obvious version of this project sends the data to a model and asks it to find
the matches. That demos well and collapses immediately: it is expensive, slow,
non-reproducible, and impossible to benchmark. It also puts a probabilistic system
in charge of a ledger.

So the pipeline inverts the usual shape:

```
        3,000,000 records
                │
                ▼
    ┌───────────────────────┐
    │ DETERMINISTIC CASCADE │   exact ids → amounts → windows → blocked fuzzy
    └───────────┬───────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
     MATCHED         EXCEPTIONS          (~9% of cases)
    (~91%)               │
                         ▼
              ┌──────────────────┐
              │  AI CONTROLLER   │       (~5% of cases, batched & cached)
              └────────┬─────────┘
                       │
              ┌────────┴─────────┐
              ▼                  ▼
        VALIDATION GATE     UNEXPLAINED
        (rules re-derive         │
         the arithmetic)         │
              │                  │
              ▼                  ▼
        AI_RESOLVED        HUMAN REVIEW QUEUE
```

Three consequences fall out of that ordering, and they are the whole pitch:

1. **Throughput** comes from SQL, not from a model.
2. **Accuracy is measurable**, because the deterministic path is reproducible and
   the dataset generator retains ground truth.
3. **Failures are honest.** A case the system cannot fully explain goes to a
   human, and the UI says exactly how much is unexplained and why.

---

## Architecture

| Layer | Technology | Role |
|---|---|---|
| Ingestion | Polars | Read CSV / Parquet / JSON, auto-detect columns |
| Normalization | Polars | One canonical schema; money → integer minor units |
| Storage | Parquet (zstd) | Columnar internal format; CSV is interchange only |
| Matching | DuckDB | Embedded analytical SQL; hash joins over blocked keys |
| Classification | DuckDB | Typed exception state machine |
| AI | Claude or Gemini, behind one interface | Structured-output adjudication of exceptions only |
| State | SQLAlchemy → SQLite / Postgres | Runs, audit trail, human decisions |
| API | FastAPI | Async, background runs, idempotency |
| Dashboard | React + Vite + Recharts | Four screens, light and dark |

**Money is never a float.** Every amount is normalized once, at ingestion, into
integer minor units (paise). Every comparison downstream is integer arithmetic.

---

## The matching cascade

Each level runs only against records the level above it left unmatched, and a
pair is only accepted when it is the best candidate for *both* sides.

| Level | Rule | What it proves |
|---|---|---|
| L1 | Exact transaction id | Certain |
| L2 | Reference digits + amount; order id inside a reference string | Strong |
| L3 | Order id + exact amount | Strong |
| L4 | Order id within a time window | Good |
| L5 | Blocked fuzzy: merchant + currency + amount bucket + day (±1) | Candidate |
| L6 | AI adjudication | Ambiguous only |

**Blocking is what makes this scale.** Comparing 1M payments to 1M orders naively
is 10¹² comparisons. Blocking on `merchant + currency + amount bucket + day`
keeps every block small no matter how large the dataset is.

Two performance details are load-bearing and were found by measurement:

- **The unmatched sets are materialized before the join, not filtered after it.**
  Leaving the anti-join above the join let one rule with no equality predicate
  degrade into a cross product. Fixing this took the match stage on 300K records
  from **45.7s to 0.38s**.
- **The day term is part of the blocking key, swept across offsets.** Without it,
  a large merchant's entire history is one block.

---

## The exception state machine

`MATCHED` / `NOT_MATCHED` tells a finance team nothing. Every unmatched record
gets a type and a computed delta:

`MATCHED` · `PARTIAL_PAYMENT` · `OVERPAYMENT` · `AMOUNT_MISMATCH` · `DUPLICATE` ·
`MISSING_PAYMENT` · `MISSING_SETTLEMENT` · `ORPHAN_PAYMENT` · `ORPHAN_SETTLEMENT` ·
`SETTLEMENT_SHORTFALL` · `FEE_VARIANCE` · `TIMING_MISMATCH` · `REFUND` ·
`CURRENCY_MISMATCH` · `MERCHANT_MISMATCH` · `UNKNOWN`

The distinction that matters most in practice is between two fees:

- **declared fee** — what the gateway says it charged
- **configured fee** — what the contract says it should have charged

A settlement short by exactly the declared fee is *arithmetic*, and is `MATCHED`.
A settlement short by more than the declared fee is a `SETTLEMENT_SHORTFALL` — real
money is missing. A declared fee that disagrees with the contract is a
`FEE_VARIANCE` — explainable, but somebody should know.

---

## How the AI is constrained

The AI layer is deliberately boxed in. Six constraints, all enforced in code:

1. **It only sees exceptions.** Never the dataset, never a raw source row.
2. **It only sees the decision-relevant fields** — amounts, deltas, fees, time
   gaps. Smaller context means lower cost, lower latency, and a much smaller
   surface to hallucinate against.
3. **Structured output only.** Responses are validated against a Pydantic schema
   at the API layer, so a malformed verdict is a retry, not a corrupt ledger row.
4. **A deterministic gate sits in front of every recommendation.**
   `validate_verdict()` re-derives the arithmetic from the case itself. A verdict
   of "just the gateway fee" at 0.99 confidence is *rejected* if the numbers do
   not actually add up — and there is a test for exactly that.
5. **Categories representing unexplained money are never auto-closeable**, at any
   confidence. `SETTLEMENT_SHORTFALL`, `PARTIAL_PAYMENT`, `ORPHAN_PAYMENT` and
   `MISSING_PAYMENT` always require a human.
6. **Degradation is never silent.** No API key, a refusal, a timeout, a dropped
   verdict, or a blown budget all route the case to `HUMAN_REVIEW` with the
   reason recorded. The system never reports a case closed that it did not close.

Cost control, since it is the other half of using a model responsibly:

- **Batching** — exceptions are bundled (default 12 per request) and requests run
  concurrently under a semaphore.
- **Prompt caching** — the system prompt is sent as a cacheable block, so after
  the first request the prefix bills at cache-read rates.
- **Fingerprint caching** — verdicts are keyed by a hash of the decision-relevant
  fields (not ids), so a recurring exception shape is never re-reasoned. Redis if
  configured; a bounded in-process LRU otherwise.
- **A hard per-run budget** — `AI_MAX_EXCEPTIONS_PER_RUN`. When it is hit, the
  overflow goes to humans and the API reports the count as
  `skipped_over_budget`. Truncation is stated, never implied.
- **Message Batches API** (`app/ai/batch_api.py`) for scheduled, non-interactive
  runs at half the token price.

---

## Measured results

Reproduce with `make bench` or `python -m app.cli benchmark --sizes 1000,10000,100000,1000000`.

| Orders | Records | Time | Throughput | Match rate | Precision | Recall | Label acc. | AI coverage |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 | 150 | 0.08s | 1,907/s | 69.09% | 1.0000 | 1.0000 | 100.00% | 16.36% |
| 1,000 | 2,978 | 0.10s | 29,625/s | 92.18% | 1.0000 | 1.0000 | 100.00% | 4.26% |
| 10,000 | 29,852 | 0.29s | 102,193/s | 91.44% | 0.9991 | 1.0000 | 99.76% | 4.84% |
| 100,000 | 298,194 | 2.41s | 123,876/s | 91.52% | 0.9994 | 1.0000 | 99.23% | 4.93% |
| 1,000,000 | 2,982,244 | 20.44s | 145,874/s | 91.90% | 0.9994 | 1.0000 | 98.25% | 4.96% |

*Measured on an 8-core laptop, single process, AI layer excluded (network latency
to a model would make throughput figures meaningless).*

**What the columns mean.** "Positive" is defined as *the engine declared this case
clean* — so a **false positive is a real break we wrongly closed**, which is the
expensive error in a finance system. Precision measures exactly that. `Label
accuracy` is stricter still: the predicted exception *type* must match the
injected one, not merely "flagged vs not".

Ground truth is real: `app/data/generator.py` builds a three-way-consistent
dataset, injects labelled anomalies at configured rates, and retains the truth in
a separate file the engine never reads.

---

## Project layout

```
ai-finance-controller/
├── render.yaml                  Render blueprint (backend + frontend + Postgres)
├── Makefile                     install / backend / frontend / test / bench
│
├── backend/
│   ├── .env.example             Every setting, documented
│   ├── requirements.txt
│   └── app/
│       ├── config.py            All tunables, one place
│       ├── main.py              FastAPI app
│       ├── cli.py               demo / benchmark / reconcile
│       │
│       ├── core/
│       │   ├── enums.py         Exception types, resolutions, cascade stages
│       │   └── canonical.py     Canonical schema + column aliases
│       │
│       ├── data/
│       │   ├── normalizer.py    Source → canonical
│       │   ├── generator.py     Ground-truth synthetic data
│       │   └── storage.py       Parquet artifacts + checkpoints
│       │
│       ├── engine/
│       │   ├── duck.py          DuckDB connection factory
│       │   ├── rules.py         The cascade, declared as data
│       │   ├── matcher.py       Cascade executor, duplicates, candidates
│       │   ├── classifier.py    Exception state machine
│       │   └── confidence.py    Additive evidence scoring
│       │
│       ├── ai/
│       │   ├── client.py        Anthropic wrapper: caching, refusals, usage
│       │   ├── schemas.py       Structured-output contracts
│       │   ├── prompts.py       Stable (cached) + volatile prompt halves
│       │   ├── analyzer.py      Batching, budget, the validation gate
│       │   ├── cache.py         Fingerprint cache (Redis or in-process)
│       │   ├── chat.py          Finance Q&A over aggregates
│       │   └── batch_api.py     Message Batches path for offline runs
│       │
│       ├── bench/
│       │   ├── metrics.py       Precision / recall / F1 / confusion matrix
│       │   └── harness.py       Size sweep
│       │
│       ├── services/
│       │   ├── pipeline.py      Ingest → match → classify → AI
│       │   ├── run_manager.py   Lifecycle, idempotency, background execution
│       │   └── audit.py         Decision trail
│       │
│       ├── store/               SQLAlchemy models + session management
│       └── api/                 Route modules, one per screen
│
└── frontend/
    ├── .env.example
    └── src/
        ├── api/                 Typed client + wire types
        ├── lib/                 Formatting, theme tokens
        ├── components/          Primitives, layout, charts
        └── pages/               Control Tower · Exceptions · Chat · Benchmark
```

---

## Running it locally

Requires Python 3.11+ and Node 18+.

```bash
make install          # venv + deps + .env files for both sides

make backend          # API on http://localhost:8000  (docs at /docs)
make frontend         # dashboard on http://localhost:5173
```

Then open the dashboard, pick a dataset size, and hit **Run reconciliation**.

To add the AI layer, put **one** provider key in `backend/.env`:

```bash
# Either
ANTHROPIC_API_KEY=sk-ant-...
AI_MODEL=claude-opus-5

# or
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-pro
```

`AI_PROVIDER=auto` (the default) picks whichever key is present — Anthropic first
if both are. Pin it to `anthropic` or `gemini` to be explicit.

Without a key everything still works end to end — exceptions simply route to the
human queue instead of the AI lane, and the UI says so.

### Swapping the model provider

Both providers live behind `BaseProvider` in `app/ai/client.py` and expose one
method, `structured(system, user, output_model)`. The analyzer, the validation
gate, and the chat endpoint never learn which model answered. Adding a third
provider is a subclass in that file and nothing else.

Two behavioural differences worth knowing:

| | Anthropic | Gemini |
|---|---|---|
| Structured output | `output_format=` (schema-constrained) | `response_schema=` + `response_mime_type` |
| Reasoning control | `effort` (`low`…`max`) | `thinking_level` — our effort maps onto it |
| Prompt caching | Explicit `cache_control` on the system block, ~90% off | Implicit; our system prompt is likely below the explicit-cache minimum, so expect a smaller discount |
| Refusals | `stop_reason == "refusal"` | `finish_reason` in `SAFETY` / `PROHIBITED_CONTENT` / … , or `prompt_feedback.block_reason` |
| Message Batches | Supported (`app/ai/batch_api.py`) | Not wired up — that module raises rather than silently changing behaviour |

Both map onto the same `Usage` shape, so the cost figures on `/api/config` read
identically either way.

### Without the browser

```bash
cd backend
.venv/bin/python -m app.cli demo --size 25000 --ai
.venv/bin/python -m app.cli benchmark --sizes 1000,10000,100000
.venv/bin/python -m app.cli reconcile \
    --orders orders.csv --payments payments.csv --settlements settlements.csv
```

### Your own data

`POST /api/datasets/upload` accepts three CSV / Parquet / JSON files. Column
names are auto-detected against the alias table in `app/core/canonical.py` — add
to that table rather than writing a bespoke normalizer per source.

---

## Configuration

Everything lives in `backend/.env` (see `.env.example` for the full annotated
list). The values that change behaviour most:

| Variable | Default | Effect |
|---|---|---|
| `AMOUNT_TOLERANCE_MINOR` | `100` | ₹1 of rounding noise is not a break |
| `FEE_TOLERANCE_MINOR` | `50` | Slack around a declared fee |
| `DEFAULT_FEE_BPS` | `200` | Contracted gateway rate (2.00%) |
| `TIME_WINDOW_HOURS` | `48` | Order → payment acceptable lag |
| `SETTLEMENT_WINDOW_DAYS` | `7` | Payment → settlement acceptable lag |
| `AUTO_RESOLVE_THRESHOLD` | `0.95` | Above this, and the rules agree, a case closes |
| `AI_INVESTIGATE_THRESHOLD` | `0.80` | Below this, straight to a human |
| `AI_MAX_EXCEPTIONS_PER_RUN` | `500` | Hard ceiling on model calls per run |
| `AI_PROVIDER` | `auto` | `auto` / `anthropic` / `gemini` |
| `DUCKDB_THREADS` | `4` | Raise on a bigger box |

The live values are served at `GET /api/config` — deliberately, so an audience can
read the thresholds instead of taking them on trust.

---

## Deploying to Render

1. Push this repo to GitHub.
2. Render → **New → Blueprint** → select the repo. `render.yaml` provisions the
   API, the static dashboard, and a Postgres instance.
3. After the first deploy, set the two cross-references Render prompts for:
   - backend `CORS_ORIGINS` → the frontend URL (e.g. `https://finance-controller-web.onrender.com`)
   - frontend `VITE_API_BASE_URL` → the backend URL (e.g. `https://finance-controller-api.onrender.com`)
4. Set `ANTHROPIC_API_KEY` on the backend service if you want the AI lane.
5. Redeploy the frontend so the API URL is compiled into the bundle.

**Free-tier caveats worth knowing before the demo:**

- Free services **sleep after inactivity**; the first request takes ~30s to wake.
  Hit `/api/health` a minute before presenting.
- `DATA_DIR` is ephemeral on the free plan, so past runs disappear on redeploy.
  Datasets regenerate in seconds, so this only matters if you need history — for
  that, upgrade the plan and attach a disk at `/var/data` (the config is in
  `render.yaml`, commented, ready to uncomment).
- Free instances have ~512MB RAM, hence `DUCKDB_MEMORY_LIMIT=400MB` and
  `BENCH_SIZES` capped at 100K. **Do not run the 1M sweep on free tier** — run it
  locally, where the numbers in this README came from.

---

## API reference

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness |
| `GET` | `/api/config` | Live thresholds, AI status, token usage |
| `POST` | `/api/datasets` | Generate a ground-truth dataset |
| `POST` | `/api/datasets/upload` | Upload three source files |
| `GET` | `/api/datasets` | List datasets |
| `POST` | `/api/runs` | Start a run (accepts `idempotency_key`) |
| `GET` | `/api/runs` | List runs |
| `GET` | `/api/runs/{id}` | Run detail + full manifest |
| `GET` | `/api/runs/{id}/breakdown` | Exception mix and money totals |
| `GET` | `/api/runs/{id}/cascade` | Matches per cascade level, stage timings |
| `GET` | `/api/runs/{id}/exceptions` | Paged, filterable queue |
| `GET` | `/api/runs/{id}/exceptions/{case}` | One case |
| `POST` | `/api/runs/{id}/exceptions/{case}/investigate` | Ask the model about one case |
| `POST` | `/api/runs/{id}/exceptions/{case}/review` | Record a human decision |
| `POST` | `/api/finance/chat` | Natural-language question over a run |
| `GET` | `/api/finance/context/{id}` | The exact context the chat model receives |
| `POST` | `/api/benchmark` | Run a sweep |
| `GET` | `/api/benchmark` | Last sweep |

Interactive docs at `/docs`.

**Idempotency:** `POST /api/runs` with a repeated `idempotency_key` returns the
original run instead of reprocessing. Double-processing a settlement file is the
one bug you cannot ship in finance.

---

## Testing

```bash
make test        # 44 tests
```

Four suites, each pinning a different property:

- **`test_normalizer.py`** — messy inputs: `₹1,250.00`, `(500.50)`, six date
  formats, refunds signalled by sign *or* status, failed transactions dropped.
- **`test_adversarial.py`** — 18 cases the system must get right, including the
  ones that make a naive matcher look correct: near-duplicates, off-by-one-rupee
  noise, fee-vs-shortfall, same-ids-different-merchant, and a pair that must
  **not** match.
- **`test_ai_validation.py`** — the safety gate. A confident-but-wrong model
  verdict is rejected; unexplained money is never auto-closed; an unconfigured
  AI routes to humans rather than looking like a resolution.
- **`test_pipeline_e2e.py`** — the accuracy claim itself is asserted, so a
  regression fails the build rather than the demo. Also pins reproducibility and
  the AI-coverage ceiling.

---

## Known limits

Stated plainly, because a system that hides its failure modes is not one you
should trust with a ledger.

- **~0.15% of fuzzy matches are wrong at the tail.** At L5 the engine can pair a
  partial payment with a similar refund from the same merchant on the same day.
  These land in the human queue and appear in the benchmark's confusion matrix —
  they are visible rather than hidden.
- **Single process.** DuckDB is embedded, so a run is bounded by one machine.
  Merchant partitions are independent, so horizontal sharding is the natural next
  step; it is not implemented.
- **Fee configuration is global.** `DEFAULT_FEE_BPS` is one rate. Real deployments
  need per-merchant, per-gateway fee schedules; the classifier already reads a
  declared fee per row, so this is a lookup table, not a redesign.
- **Multi-currency is detected, not converted.** `CURRENCY_MISMATCH` is raised;
  no FX conversion is attempted.
- **The AI chat is read-only** and answers strictly over pre-aggregated context.
  It cannot query the dataset, by design.
