#!/usr/bin/env bash
# Render build step for the backend service.
# Referenced from render.yaml; also runnable locally to mimic the deploy build.
set -euo pipefail

echo "==> Installing backend dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Sanity: app imports and settings resolve"
python -c "from app.main import app; from app.config import settings; print('ok:', settings.app_name)"
