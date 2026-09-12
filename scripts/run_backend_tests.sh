#!/usr/bin/env bash
# Run backend tests (pytest) with no external services required.
set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --quiet -r requirements.txt

export DATA_REPOSITORY=mock
export DEV_AUTH_MODE=true
export APP_ENV=development

exec python -m pytest "$@"
