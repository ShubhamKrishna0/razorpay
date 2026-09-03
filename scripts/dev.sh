#!/usr/bin/env bash
# Run both halves locally with one command. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

(cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000) &
BACK=$!
(cd frontend && npm run dev) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null' EXIT INT TERM
wait
