#!/usr/bin/env bash
# Run backend + frontend together for local development. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

./run_backend.sh &
BACKEND_PID=$!

./run_frontend.sh &
FRONTEND_PID=$!

trap 'kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null' EXIT INT TERM

wait
