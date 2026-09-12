#!/usr/bin/env bash
# Run the Playwright responsive/mobile-viewport end-to-end tests.
# Playwright's own webServer config starts the backend + frontend dev
# server automatically (see frontend/playwright.config.ts).
set -euo pipefail
cd "$(dirname "$0")/../frontend"

if [ ! -d node_modules ]; then
  npm install
fi

exec npx playwright test "$@"
