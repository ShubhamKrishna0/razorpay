#!/usr/bin/env bash
# Render start command for the backend service.
# $PORT is injected by Render. Single worker: DuckDB runs are process-local,
# and the free instance has one vCPU anyway.
set -euo pipefail

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
