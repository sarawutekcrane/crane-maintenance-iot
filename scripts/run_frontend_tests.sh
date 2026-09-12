#!/usr/bin/env bash
# Run frontend tests (Vitest).
set -euo pipefail
cd "$(dirname "$0")/../frontend"

if [ ! -d node_modules ]; then
  npm install
fi

exec npm run test
