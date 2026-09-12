PHASE: Web/API Phase 1 — Foundation, Local Development Stack, API Contracts, Repository Abstraction, and Thai UI Shell
STATUS: PASS

OBJECTIVE:
Create a local-development application (backend + frontend) that runs
immediately on the user's computer with no production server and no
Google credentials, and freeze the architecture boundaries (API
versioning, error envelope, repository/storage abstraction, environment
configuration, shared API client, date/time and ID conventions, Thai UI
shell, request/user context) so later phases can plug in without
redesign.

PREREQUISITE CHECK:
- 00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt — read in full.
- 00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt — read in full.
- 01_PHASE1_FOUNDATION_LOCAL_STACK_EN.txt — read in full.
- Repository inspected before coding: contained only
  `docs/claude-prompts/`, `.env.example`, `.gitignore`, `README.md`. No
  backend, frontend, or application code existed. No previous phase
  report existed. Result: repository is "empty" per the baseline's
  Section 2 rule, so the default stack (Python/FastAPI/Pydantic/Uvicorn +
  React/TypeScript/Vite) was used.
- Toolchain verified available: Python 3.11.15, Node 22.22.2, npm 10.9.7.

FROZEN CONTRACTS USED:
None (this is the first phase; no prior contracts existed to preserve).

FILES ADDED:
Backend (`backend/`):
- `app/main.py` — FastAPI app factory (CORS, request-context middleware,
  exception handlers, DEV_AUTH_MODE production guard).
- `app/config.py` — Settings loaded from environment (`.env`), including
  `DataRepositoryMode` / `FileStorageBackend` enums.
- `app/context.py` — `RequestContext`, `RequestContextMiddleware`
  (request-id + development user injection).
- `app/errors.py` — `ApiError`, error envelope builder, exception
  handlers (404, validation, generic 500).
- `app/dependencies.py` — composition root selecting Repository /
  StorageProvider implementation from config.
- `app/domain/common.py` — pagination (`PageParams`, `Page[T]`), UTC
  `utc_now()` helper, documented ID/date-time conventions.
- `app/api/v1/router.py`, `app/api/v1/health.py`, `app/api/v1/schemas.py`
  — `/api/v1/health`, `/api/v1/readiness`.
- `app/repositories/base.py` — `Repository` interface, `RepositoryError`.
- `app/repositories/mock/repository.py` — `MockRepository` (offline).
- `app/repositories/google_sheets/client.py`,
  `app/repositories/google_sheets/repository.py` — base Google Sheets
  adapter architecture (connectivity/config check only; no domain tables
  implemented yet, as scoped).
- `app/storage/base.py` — `StorageProvider` interface, `StoredFile`.
- `app/storage/local.py` — `LocalFileStorageProvider` (`./data/uploads`,
  path-traversal guarded).
- `pyproject.toml`, `requirements.txt`, `README.md`.
- `tests/` — `conftest.py` + 5 test files (see TESTS ACTUALLY PERFORMED).

Frontend (`frontend/`):
- Vite + React + TypeScript scaffold (`index.html`, `src/main.tsx`,
  `src/App.tsx`, `vite.config.ts` with `/api` dev proxy to the backend,
  `tsconfig.*`, `package.json`).
- `src/lib/apiClient.ts` — shared API client, error-envelope-aware
  `ApiResult<T>` / `ApiError`.
- `src/components/` — `AppLayout`, `NavBar`, `LoadingState`,
  `EmptyState`, `ErrorState`, `PermissionDeniedState`, `ConfirmDialog`,
  `StatusBadge` (all Thai-facing text).
- `src/pages/HomePage.tsx`, `src/pages/SystemStatusPage.tsx` (calls
  `/api/v1/health` + `/api/v1/readiness`, exercises loading/error states
  and the confirm dialog).
- `src/index.css` — responsive, theme-aware (light/dark) base styling.
- `src/test/setup.ts` + 3 test files (App shell, StatusBadge,
  SystemStatusPage with mocked fetch).
- `README.md`.

Docs / scripts:
- `docs/architecture/API_CONVENTIONS.md` — frozen API version, error
  envelope, pagination, search/filter, date/time, stable-ID, and
  repository/storage-abstraction conventions, with the Google Sheets ->
  PostgreSQL swap diagram.
- `docs/phase-results/web-phase-01-result.md` — this report.
- `scripts/run_backend.sh`, `scripts/run_frontend.sh`,
  `scripts/run_dev.sh`, `scripts/run_backend_tests.sh`,
  `scripts/run_frontend_tests.sh`.
- `CHANGELOG.md`.

FILES MODIFIED:
- `README.md` — replaced with local startup instructions, architecture
  summary, and links to the phase report / API conventions doc.
  (`.env.example` and `.gitignore` were reviewed and already matched the
  required variables/ignores; no changes were needed to either.)

API ROUTES ADDED:
- `GET /api/v1/health`
- `GET /api/v1/readiness`

DATABASE / SHEET TABLES USED:
None. Phase 1 defines the `Repository` interface and the
`GoogleSheetsRepository` base adapter architecture only; no domain sheet
tabs/tables are read or written yet (correctly out of scope per the
phase file).

UI PAGES ADDED:
- `/` — HomePage (หน้าหลัก / welcome).
- `/system-status` — SystemStatusPage (สถานะระบบ), calling the backend
  health/readiness endpoints through the Vite dev proxy and rendering the
  Thai loading/error/status-badge shell components.

IMPLEMENTATION SUMMARY:
Backend: FastAPI app with versioned routes under `/api/v1`, a shared
error envelope returned by every non-2xx response (404, 422 validation,
generic 500, and any `ApiError` a service raises), a request-id +
development-user context middleware, and a composition root
(`dependencies.py`) that is the only place concrete
`Repository`/`StorageProvider` implementations are chosen, based on
`DATA_REPOSITORY` / `FILE_STORAGE_BACKEND`. `MockRepository` and
`LocalFileStorageProvider` are fully functional and used by default so
the app runs with zero external dependencies. `GoogleSheetsRepository`
implements the same interface but only performs a configuration/
connectivity readiness check in Phase 1 — no domain table exists yet to
read/write, matching the phase's explicit scope ("Do not implement every
domain table yet"). Production startup fails fast if
`DEV_AUTH_MODE=true` while `APP_ENV=production`.

Frontend: React + TypeScript + Vite app with a Thai-language UI shell
(navigation, responsive layout, loading/empty/error/permission-denied
states, confirmation dialog, status badge) and a typed API client that
turns backend error envelopes into a discriminated `ApiResult<T>` so
pages can render error state uniformly. The Vite dev server proxies
`/api` to the local backend so the browser never needs a backend URL/CORS
workaround and — per the baseline's architecture rule — never talks to
Google Sheets directly. A System Status page proves the full path:
Thai UI -> `/api/v1` -> Backend -> Repository (mock).

LOCAL STARTUP COMMANDS:
```
cp .env.example .env

./scripts/run_backend.sh     # http://127.0.0.1:8000 (creates venv, installs deps)
./scripts/run_frontend.sh    # http://127.0.0.1:5173 (npm install on first run)
# or both together:
./scripts/run_dev.sh

./scripts/run_backend_tests.sh
./scripts/run_frontend_tests.sh
```
OpenAPI docs: http://127.0.0.1:8000/docs

BUILD / TYPECHECK / LINT RESULT:
- Backend: no separate type-check step configured (Python); `python -m
  pytest` (below) exercises the app import graph and all modules.
- Frontend typecheck: `npx tsc -b` — PASSED, no errors.
- Frontend production build: `npm run build` (`tsc -b && vite build`) —
  PASSED. Output: `dist/index.html` 0.43 kB, `dist/assets/*.css` 4.44 kB,
  `dist/assets/*.js` 266.14 kB (84.47 kB gzip).
- Frontend lint: `npx oxlint` — PASSED with 1 warning
  (`react/set-state-in-effect` on `SystemStatusPage.tsx:64`, the
  `setState` inside the data-fetching `useEffect`). This is the standard
  shape for an async data-fetch-on-mount effect; no fix applied in Phase
  1 since it does not affect behavior or correctness. Noted as a
  KNOWN LIMITATION below rather than suppressed.
- `npm audit` on the frontend: 0 vulnerabilities (an initial
  `react-router-dom@^6` install flagged 2 moderate advisories; resolved
  by installing the latest `react-router-dom@7.18.3`).

TESTS ACTUALLY PERFORMED:
Backend (`DATA_REPOSITORY=mock DEV_AUTH_MODE=true APP_ENV=development
python -m pytest`, via `./scripts/run_backend_tests.sh`):
- `tests/test_health.py` — health returns `status=ok`; readiness reports
  `ready=true` / `repository_mode=mock` in mock mode; every response
  carries an `X-Request-Id` header.
- `tests/test_error_envelope.py` — unknown route returns the error
  envelope with `code=NOT_FOUND`; wrong HTTP method returns the envelope
  with `code=HTTP_ERROR`.
- `tests/test_mock_repository.py` — `MockRepository.check_ready()` is
  always `(True, None)`.
- `tests/test_local_storage.py` — save/read/exists/delete round-trip on a
  temp directory; a path-traversal `storage_ref` raises `ValueError`.
- `tests/test_google_sheets_repository.py` — an unconfigured
  `GoogleSheetsRepository` reports `ready=False` with a reason.

Frontend (`npm run test` / `npx vitest run`, via
`./scripts/run_frontend_tests.sh`):
- `src/App.test.tsx` — renders the Thai nav brand and the home page
  heading.
- `src/components/StatusBadge.test.tsx` — renders the given Thai label.
- `src/pages/SystemStatusPage.test.tsx` — shows the Thai loading message,
  then (with `fetch` mocked) the resolved health/readiness status in
  Thai.

Manual end-to-end smoke test (both dev servers started locally):
- `curl http://127.0.0.1:8000/api/v1/health` -> `{"status":"ok","app_env":"development"}`
- `curl http://127.0.0.1:8000/api/v1/readiness` -> `{"ready":true,"repository_mode":"mock",...}`
- `curl http://127.0.0.1:8000/openapi.json` -> valid OpenAPI 3.1 document.
- `curl http://127.0.0.1:8000/api/v1/nope` -> HTTP 404 with the error
  envelope.
- Started `vite` bound to `127.0.0.1:5173` and confirmed
  `curl http://127.0.0.1:5173/api/v1/health` returns the same payload
  through the dev proxy (browser never needs the backend's host/port),
  and `GET /` returns HTTP 200.
- Both dev server processes were stopped after the smoke test.

TEST RESULTS:
- Backend: 9 passed, 0 failed.
- Frontend: 3 test files / 3 tests passed, 0 failed.
- Frontend typecheck + build: passed.
- Manual smoke test: all checks passed as listed above.

SCREEN / UX NOTES:
- All rendered UI text is Thai (nav labels "หน้าหลัก" / "สถานะระบบ", page
  headings, status labels "พร้อมใช้งาน" / "ยังไม่พร้อม" / "ผ่าน",
  loading/error/confirm-dialog copy). Internal codes (`repository_mode`,
  e.g. `mock`) are shown as-is next to a Thai label, consistent with the
  baseline rule that internal identifiers may stay English but must not
  be the only label shown to users.
- Layout is a single responsive column (nav bar wraps at narrow widths,
  content max-width 960px, footer marks "โหมดพัฒนา (Local Development)").
  Light/dark color schemes are both defined via CSS custom properties.
- No mobile/device QR testing was performed in Phase 1 (no vehicle routes
  exist yet); LAN/QR testing is scoped to Phase 2 once `/vehicle/{id}`
  exists.

TBD VALUES REMAINING:
- None blocking Phase 1. Real Google Sheets credentials, PostgreSQL, RBAC
  enforcement, and all domain entities (vehicle, inspection, PM, repair,
  parts, IoT, etc.) are explicitly out of scope until their respective
  phases.

KNOWN LIMITATIONS:
- `GoogleSheetsRepository.check_ready()` only checks that
  `GOOGLE_SHEET_ID` / `GOOGLE_APPLICATION_CREDENTIALS` are set; it does
  not yet open a real connection or validate headers, because no sheet
  tab/schema is defined until a domain phase needs one (as scoped by the
  phase file). `GoogleSheetsClient.validate_schema()` intentionally
  raises `NotImplementedError` rather than pretending to succeed.
  Google Sheets connectivity mode was not tested (no credentials
  available in this environment); only mock mode was exercised, which is
  the phase's required minimum ("The application must run with no Google
  credentials").
- `SystemStatusPage`'s data-fetch-on-mount triggers an oxlint
  `react/set-state-in-effect` warning; this is expected for a
  fetch-in-effect pattern and does not affect behavior.
- No RBAC/authorization enforcement yet — `DEV_AUTH_MODE` always grants
  `ADMIN`. Real authorization is explicitly scoped to the later hardening
  phase (Phase 10) per the baseline.
- No CI pipeline was set up (not requested in Phase 1 scope); tests are
  run manually/via the provided scripts.

RISKS / CONCERNS:
- None identified that block Phase 2. The repository/storage abstraction
  and error envelope are exercised by both mock-mode tests and a live
  manual smoke test, so the swap points documented in
  `docs/architecture/API_CONVENTIONS.md` are structurally verified, not
  just described.

ANY CHANGE TO PREVIOUS FROZEN PHASES:
NONE — this is Phase 1; no prior frozen contracts existed.

NEXT PHASE READINESS:
READY

STOP HERE.
DO NOT IMPLEMENT THE NEXT PHASE.
