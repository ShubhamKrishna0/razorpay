#!/usr/bin/env bash
# Render build step for the static frontend.
# Requires VITE_API_BASE_URL in the environment — it is baked into the bundle,
# so a missing value means every API call silently targets the wrong host.
set -euo pipefail

if [ -z "${VITE_API_BASE_URL:-}" ]; then
  echo "ERROR: VITE_API_BASE_URL is not set." >&2
  echo "Set it to the backend URL, e.g. https://finance-controller-api.onrender.com" >&2
  exit 1
fi

echo "==> Installing frontend dependencies"
npm ci

echo "==> Building (API base: $VITE_API_BASE_URL)"
npm run build

echo "==> Verifying the API URL is actually in the bundle"
grep -q "$VITE_API_BASE_URL" dist/assets/*.js \
  || { echo "ERROR: built bundle does not contain VITE_API_BASE_URL" >&2; exit 1; }
echo "ok"
