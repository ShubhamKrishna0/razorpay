# Backend — reconciliation engine and API

FastAPI + DuckDB + Polars. See the [root README](../README.md) for the design
rationale and measured results; this file covers running and extending the
service itself.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Docs at http://localhost:8000/docs.

## CLI

```bash
.venv/bin/python -m app.cli demo --size 25000 [--ai]
.venv/bin/python -m app.cli benchmark --sizes 1000,10000,100000 [--json out.json]
.venv/bin/python -m app.cli reconcile --orders a.csv --payments b.csv --settlements c.csv
```

## Where things live

| Question | File |
|---|---|
| How is a source file mapped onto the canonical schema? | `app/core/canonical.py` (aliases), `app/data/normalizer.py` |
| What are the matching rules? | `app/engine/rules.py` |
| How does a rule get executed? | `app/engine/matcher.py` |
| How is an exception typed? | `app/engine/classifier.py` |
| How is confidence computed? | `app/engine/confidence.py` |
| What is the model allowed to decide? | `app/ai/analyzer.py` → `validate_verdict` |
| What does the model actually see? | `app/ai/analyzer.py` → `slim_case`, `app/ai/prompts.py` |
| How is accuracy measured? | `app/bench/metrics.py` |

## Extending it

**A new source system** — add its column names to `COLUMN_ALIASES` in
`app/core/canonical.py`. No new code path.

**A new matching rule** — append a `MatchRule` to `app/engine/rules.py`. Rules are
declarative data; the executor is generic. Put it at the position in the list
that matches its certainty, since order *is* the cascade.

**A new exception type** — add it to `ExceptionType`, add a `WHEN` clause in
`build_reconciliation`, and decide two things: is it AI-eligible (`AI_ELIGIBLE`),
and can a validated AI verdict close it (`AI_CLOSEABLE` in `app/ai/analyzer.py`)?
If it represents unexplained money, the answer to the second is no.

**Different fee handling** — `expected_fee_minor` (declared) and
`configured_fee_minor` (contracted) are computed in `classifier.py`. A per-merchant
fee schedule slots in as a join there.

## Tests

```bash
.venv/bin/python -m pytest          # 44 tests
.venv/bin/python -m pytest -k adversarial -v
```
