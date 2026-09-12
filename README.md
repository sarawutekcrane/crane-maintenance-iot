# Crane Maintenance IoT

Fleet Maintenance, Crane IoT Monitoring and Equipment Management System.

## Project Components

- `backend/` - Backend API (FastAPI) and business logic
- `frontend/` - Thai Web Application (React + TypeScript + Vite)
- `firmware/` - ESP32 firmware (added in later phases)
- `docs/` - Requirements, contracts, Claude Code prompts and phase results
- `scripts/` - Local development startup/test scripts

## Prototype Architecture

```
Thai Web Application
  -> Backend API
  -> Domain / Service Layer
  -> Repository Interface
  -> Google Sheets
```

## Production Architecture

```
Thai Web Application
  -> Backend API
  -> Domain / Service Layer
  -> Repository Interface
  -> PostgreSQL
```

See `docs/architecture/API_CONVENTIONS.md` for the frozen API/versioning
conventions and the repository/storage abstraction that keeps the Google
Sheets -> PostgreSQL swap safe, and `docs/architecture/RESPONSIVE_UI.md`
for the mobile-first UI foundation (breakpoints, reusable card/table/form/
dialog patterns, mobile navigation).

## Development

Development begins locally. **A production server is not required** during
the initial phases (see
`docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`).

All user-facing Web pages must be in Thai.

### Prerequisites

- Python 3.11+
- Node.js 20+ / npm

### 1. Configure environment

```bash
cp .env.example .env
```

The defaults run entirely offline with `DATA_REPOSITORY=mock` — no Google
credentials are required to start developing.

### 2. Run backend + frontend

Using the helper scripts (each creates its own virtualenv / installs
node_modules on first run):

```bash
./scripts/run_backend.sh    # http://127.0.0.1:8000
./scripts/run_frontend.sh   # http://127.0.0.1:5173
```

or run both together:

```bash
./scripts/run_dev.sh
```

Open http://127.0.0.1:5173 — the "สถานะระบบ" (System Status) page calls
the backend's `/api/v1/health` and `/api/v1/readiness` through the Vite
dev proxy (`/api` -> local backend), proving the frontend can reach the
API without the browser ever touching Google Sheets directly.

Starting Phase 2, "ยานพาหนะ" (Vehicles) and "เครื่องมือ" (Equipment) list
pages are also available, and every vehicle/equipment has a stable QR
entry point at `/vehicle/{vehicle_id}` / `/equipment/{equipment_id}` (see
`docs/phase-results/web-phase-02-result.md`). To try the QR flow on a
phone on the same Wi-Fi, see
`docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`
section 10 — e.g. `http://192.168.1.100:5173/vehicle/VEH-1046`.

### 3. Run tests

```bash
./scripts/run_backend_tests.sh
./scripts/run_frontend_tests.sh
./scripts/run_e2e_tests.sh    # Playwright: smartphone/tablet/desktop viewport checks
```

### API docs

With the backend running, interactive OpenAPI docs are available at
http://127.0.0.1:8000/docs.

### Repository modes

Set `DATA_REPOSITORY` in `.env`:

- `mock` (default) — in-memory, works fully offline.
- `google_sheets` — prototype storage; requires `GOOGLE_SHEET_ID` and
  `GOOGLE_APPLICATION_CREDENTIALS` (see the local-development doc for
  setup steps). Never commit the credential JSON.
- `postgresql` — production storage, added in a later phase.

## Phase Results

Each implementation phase produces a report under `docs/phase-results/`.
See `docs/phase-results/web-phase-01-result.md` and
`docs/phase-results/web-phase-02-result.md` for the current status.
