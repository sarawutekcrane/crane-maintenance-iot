#!/usr/bin/env bash
# Run the local backend API (FastAPI + Uvicorn) with auto-reload.
set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --quiet -r requirements.txt

PORT="${BACKEND_PORT:-8000}"
exec uvicorn app.main:app --reload --host 127.0.0.1 --port "$PORT"
