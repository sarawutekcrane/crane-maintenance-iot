# Changelog

## Web/API Phase 2 — Vehicle, Model, Workshop Equipment, Asset References, and QR Detail

- Domain: `VehicleModel`/`ComponentRole` (with a dual-engine model
  demonstrating multi-engine support), `Vehicle`/`VehicleComponent`/
  `VehicleStatusHistoryEntry`, `Equipment`/`EquipmentCategory`, and the
  shared `AssetRef`/`AssetType` pattern for later inspection/repair/
  attachment records. `OperationalStatus` added to the shared domain
  conventions (`app.domain.common`).
- `Repository` extended (per its Phase 1 freeze note) with vehicle/model/
  component/status-history/equipment methods; `MockRepository` gets a
  full in-memory implementation and seed data (`VEH-1046`, matching the
  local-dev doc's QR example, plus a dual-engine vehicle and one with a
  deliberately blank serial number). `GoogleSheetsRepository` declares
  the Phase 2 tab/header schemas and implements the same interface,
  reporting a controlled not-configured/not-implemented error until real
  credentials exist (no Google credentials or network path exist in this
  environment to test live Sheets I/O).
- `VehicleService`/`EquipmentService` (domain/service layer) assemble the
  Vehicle Detail view and translate "not found" into the frozen error
  envelope, so later phases (Dashboard, alerts) can reuse them.
- API: `GET/{id} /api/v1/models`, `GET /api/v1/vehicles`,
  `GET/PATCH /api/v1/vehicles/{vehicle_id}` (machine_no — vehicle_id never
  changes), `PATCH .../status` (append-only history),
  `GET .../status-history`, `GET .../components`,
  `GET/{id} /api/v1/equipment`.
- Frontend: `VehicleListPage`/`VehicleDetailPage` (`/vehicle/:vehicleId` —
  the stable QR route) and `EquipmentListPage`/`EquipmentDetailPage`
  (`/equipment/:equipmentId`), a status-change dialog reusing the frozen
  dialog pattern, and Thai label/error-code mapping helpers
  (`lib/labels.ts`) — all built on the `Card`/`ResponsiveTable`/
  `FormField` primitives frozen in Phase 1, with no new layout patterns.
- Backend tests (pytest, 37 total, 28 new) and frontend tests (Vitest, 18
  total, 9 new) plus 18 new Playwright viewport tests (smartphone/tablet/
  desktop) covering the QR route, status change, search, and controlled
  404s.

See `docs/phase-results/web-phase-02-result.md` for the full Phase Result
Report.

## Web/API Phase 1 — Foundation, Local Development Stack, API Contracts, Repository Abstraction, Thai UI Shell

- Backend: FastAPI application (`backend/`) with `/api/v1/health` and
  `/api/v1/readiness`, a shared error envelope, request-id middleware,
  a development request/user context (`DEV_AUTH_MODE`), and OpenAPI docs.
- Repository abstraction (`Repository` interface) with a working
  `MockRepository` (fully offline) and a `GoogleSheetsRepository` base
  adapter (connectivity/config check only; no domain tables yet).
- `StorageProvider` abstraction with a working `LocalFileStorageProvider`.
- Frontend: React + TypeScript + Vite app (`frontend/`) with a Thai UI
  shell (nav, loading/empty/error/permission-denied states, confirm
  dialog, status badge, responsive layout) and a System Status page that
  calls the backend through the `/api` dev proxy.
- Backend tests (pytest, 9 tests) and frontend tests (Vitest + Testing
  Library, 3 test files) — both run fully offline.
- `docs/architecture/API_CONVENTIONS.md` documents the frozen API
  version/error-envelope/pagination/ID/date-time conventions and the
  Google Sheets -> PostgreSQL swap boundary.
- `scripts/` for local backend/frontend/test startup.

See `docs/phase-results/web-phase-01-result.md` for the full Phase Result
Report.

### Update: mobile-first / responsive foundation

Following a baseline/phase-file update mandating a mobile-first UI, added
to the same Phase 1:

- `frontend/src/index.css` rewritten mobile-first (base rules target
  smartphone portrait; `min-width` breakpoints at 481/641/1024/1280px
  only add rules for larger screens), with a `--tap-target: 44px`
  minimum touch target, 16px base font, and Thai text wrapping.
- `NavBar` gains a collapsible mobile menu toggle; always shown inline
  from tablet width up.
- New reusable components: `Card`, `ResponsiveTable` (CSS-only
  table-on-tablet+/stacked-cards-on-phone), `FormField` (full-width,
  touch-sized inputs) — documented in
  `docs/architecture/RESPONSIVE_UI.md`.
- `ConfirmDialog` is now a bottom sheet on phones and a centered dialog
  from tablet width up, always fitting the viewport.
- New Playwright suite (`frontend/e2e/`, `npm run test:e2e` /
  `./scripts/run_e2e_tests.sh`) verifies the shell at smartphone,
  tablet, and desktop viewports (no horizontal scrolling, 44px+ touch
  targets, working mobile nav, dialog fits viewport).
