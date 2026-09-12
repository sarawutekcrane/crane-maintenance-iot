# Web/API Phase 1 — Retroactive Post-Phase Verification

STATUS: AUDIT ONLY — no Phase 1 code was reimplemented, no Phase 2/3 work
was started, no frozen contract was changed, and no open decision was
resolved as part of this verification.

Verified against branch `web/phase-01-verification`, commit `2471f89`
(Phase 1 implementation commit `a4f847b` "Add mobile-first responsive UI
foundation to Web/API Phase 1", preceded by `31719d7` "Implement Web/API
Phase 1: foundation, local dev stack, Thai UI shell").

Documents read in full before this verification, as required:

- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`
- `docs/claude-prompts/web-api/01_PHASE1_FOUNDATION_LOCAL_STACK_EN.txt`
- `docs/phase-results/web-phase-01-result.md`

Plus direct inspection of every file under `backend/app/`, `backend/tests/`,
`frontend/src/`, `frontend/e2e/`, `docs/architecture/`, `scripts/`,
`.gitignore`, `.env.example`, `README.md`, `CHANGELOG.md`.

---

## A. Requirement Traceability

| Requirement (Phase 1 file, SCOPE items unless noted) | Implemented | Evidence file/module | Automated test evidence | Manual test needed | Notes |
|---|---|---|---|---|---|
| Inspect repo; default stack if empty (FastAPI+Pydantic+Uvicorn / React+TS+Vite) | YES | `backend/pyproject.toml`, `frontend/package.json` | build/typecheck below | No | Repo was empty at Phase 1 start per original report; default stack correctly applied. |
| Clear structure: frontend/backend/domain/services/repositories/storage/tests/docs | PARTIAL | `backend/app/{domain,repositories,storage}`, `backend/tests`, `frontend/src`, `docs/` | pytest, vitest | No | `domain/` exists as shared-conventions module (`common.py`) only; no `services/` subpackage yet because no business logic exists until Phase 2+. Correct for Phase 1 scope, not a defect. |
| Local `MockRepository`, runs with no Google credentials | YES | `backend/app/repositories/mock/repository.py` | `test_mock_repository.py`, `test_health.py::test_readiness_mock_mode_is_ready` | No | |
| Base `GoogleSheetsRepository` client/adapter architecture (no domain tables yet) | YES | `backend/app/repositories/google_sheets/{repository,client}.py` | `test_google_sheets_repository.py` | No | Correctly stops at connectivity/config check; `validate_schema()` raises `NotImplementedError` until a domain phase needs it — intentional, documented. |
| `StorageProvider` abstraction + `LocalFileStorageProvider` | YES | `backend/app/storage/{base,local}.py` | `test_local_storage.py` (round-trip + path-traversal rejection) | No | |
| Local env config + `.env.example`, no real secrets | YES | `.env.example`, `backend/app/config.py` | manual grep (this verification) | No | See Section E. |
| Thai UI shell: nav, loading/empty/error/permission-denied, confirm dialog, status badge, responsive base layout | YES | `frontend/src/components/*.tsx` | `App.test.tsx`, `NavBar.test.tsx`, `StatusBadge.test.tsx`, Playwright suite | Yes — visual check per Section I | `PermissionDeniedState` exists but is not yet wired to a real permission check (no RBAC yet) — correct for Phase 1. |
| Freeze `/api/v1` versioning | YES | `backend/app/api/v1/router.py` | `test_health.py` | No | |
| Common error envelope (code/message/details/request_id) | YES | `backend/app/errors.py` | `test_error_envelope.py` | No | All 4 exception handlers (`ApiError`, `StarletteHTTPException`, `RequestValidationError`, generic `Exception`) use the same envelope. |
| Pagination / search-filter / date-time / stable-ID conventions | YES (defined) | `backend/app/domain/common.py`, `docs/architecture/API_CONVENTIONS.md` | none direct (no listing endpoint exists yet) | No | Convention is documented and the UTC-`Z` serialization claim was independently verified (see Section C) — correct, but genuinely untested by an endpoint since no domain entity exists yet. Not a defect; flag for Phase 2's first real endpoint. |
| User/request context interface | YES | `backend/app/context.py` | `test_health.py::test_response_has_request_id_header` | No | |
| Development authentication mode | YES | `DEV_AUTH_MODE` in `config.py`, `context.py`, production guard in `main.py` | none direct, but guard logic is simple/inspectable | No | Verified production-mode + dev-auth-mode combination raises `RuntimeError` by reading `main.py`; not covered by an automated test. Recommend a small unit test in a later phase. |
| `GET /api/v1/health`, `GET /api/v1/readiness` | YES | `backend/app/api/v1/health.py` | `test_health.py` (3 tests) | No | |
| OpenAPI docs | YES | FastAPI auto-generated at `/docs` (from `create_app()` title/description) | manual (documented, not re-verified live in this audit since it needs a running server — see Section I) | Yes | |
| Testing foundation (pytest, frontend unit, API integration) | YES | `backend/tests/`, `frontend/src/**/*.test.tsx` | see Section G | No | |
| Document local startup | YES | `README.md`, `scripts/run_*.sh` | scripts executed successfully in this audit | No | |
| Frontend calls backend locally | YES | `frontend/src/lib/apiClient.ts`, `SystemStatusPage.tsx` | Playwright `system status page renders...` test | No | |
| Repository switch mock/google_sheets | YES | `backend/app/dependencies.py` (`DATA_REPOSITORY`) | `test_health.py` (mock) + `test_google_sheets_repository.py` (google_sheets, unconfigured) | No | |
| Do not implement PostgreSQL yet | YES (correctly not implemented) | `dependencies.py` raises `NotImplementedError` for `postgresql` | none needed | No | |
| Mobile-first CSS strategy / responsive shell / nav / tablet+desktop adaptation / reusable card / responsive table / responsive form / responsive dialog / large touch targets / no hover-only / Thai text wrapping / smartphone viewport test | YES | `frontend/src/index.css`, `NavBar.tsx`, `Card.tsx`, `ResponsiveTable.tsx`, `FormField.tsx`, `ConfirmDialog.tsx`, `docs/architecture/RESPONSIVE_UI.md` | `NavBar.test.tsx`, `ResponsiveTable.test.tsx`, `FormField.test.tsx`, Playwright suite (12 tests × 3 viewports) | Yes — Section I | See Section F for the one known gap (landscape orientation not in the automated viewport matrix). |
| Acceptance test #11: no production server required to run tests | YES | all test scripts run against `127.0.0.1` dev servers only | pytest + vitest + Playwright all executed in this audit with zero external network dependency | No | |

**Traceability verdict:** every mandatory Phase 1 requirement is present and evidenced. The only PARTIAL is the `domain/services/` naming, which is a documentation-literalism gap, not a functional one — Phase 1's own scope explicitly defers domain/service code to later phases.

---

## B. Open-Decision / Guessing Audit

Cross-checked against `OPEN_DECISIONS_REGISTER_EN.txt`. Phase 1 introduces
no domain entities (vehicle, inspection, PM, repair, part, alert, device),
so the large majority of registered items (A01–A09, B01–B04, C01–C03,
D01–D04, E01–E05, F01–F03, G01–G06, H01–H03, I01–I07, J01–J09, K01–K03,
L01–L08) are simply **not yet reachable** by any Phase 1 code — there is
nothing to hard-code because nothing in those domains exists yet. That is
correct behavior, not a gap.

Items that *are* touched by Phase 1 code were checked individually:

| Decision ID | Current implementation | Explicitly approved? | Risk | Required action |
|---|---|---|---|---|
| A10 — API Compatibility Policy (PARTIALLY FROZEN) | `/api/v1` prefix exists; no additive/breaking/deprecation policy is written or enforced. | N/A — register itself says only `/api/v1` is frozen, the rest remains open. | Low. Nothing in Phase 1 depends on a compatibility policy existing yet. | None for Phase 1. Freeze the policy before Web Phase 2 approval per `CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt` item 1 if not already planned. |
| M01 — Production Authentication Provider (TBD-DEFERRED) | `DEV_AUTH_MODE=true` injects a fixed `dev-user`/`ADMIN` context; no production auth provider is chosen or implemented. | N/A — deferred item; Phase 1's local-dev doc (`00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt` §9) explicitly directs exactly this placeholder-only behavior for early phases. | Low, and actively mitigated: `main.py` raises at startup if `APP_ENV=production` and `DEV_AUTH_MODE=true`. | None. This is the approved placeholder, not a guess. |
| M02 — Exact Permission Matrix (TBD-BLOCKING before RBAC approval) | `PermissionDeniedState` UI component exists but is not wired to any real check; `DEV_AUTH_MODE` grants a single fixed `ADMIN` role. No permission matrix is encoded. | N/A | None — no permission decision was made; the component is a display-only building block for later phases. | None for Phase 1. |
| M03 — Multi-Tenant Support (RECOMMENDED FREEZE: single-tenant) | No tenant concept anywhere in the code. | Consistent with the recommended freeze by omission. | None. | None. |
| M04 — Web Offline/PWA (NOT REQUIRED unless approved) | No service worker / offline cache / manifest. | Consistent — nothing implemented. | None. | None. |
| M07 — File Upload Limits / MIME / Malware Scanning (TBD-BLOCKING before production file upload) | `LocalFileStorageProvider.save()` accepts any `content_type`/size with no limit or scanning. | N/A — no upload **endpoint** exists yet in Phase 1 (only the provider + a unit test call it directly), so this is not yet "production file upload." | Low today, but **flag for the first phase that adds a real upload endpoint** (inspection/repair photos) — do not let that phase silently inherit "no limits" as a permanent decision. | Track as a pre-condition for whichever phase adds the first upload endpoint. |

**No defect found.** Phase 1 did not permanently hard-code behavior for any
item that should have remained open. Every touched TBD/deferred item is
either genuinely out of Phase 1's reach or implemented exactly as the
governance documents themselves direct for this stage (dev-auth placeholder,
no PWA, single-tenant by omission).

---

## C. Frozen Contract Review

| Contract | Status | Evidence |
|---|---|---|
| `/api/v1` convention | Confirmed | `backend/app/api/v1/router.py` (`prefix="/api/v1"`); both routes reachable and tested. |
| Common error envelope | Confirmed | `backend/app/errors.py`; verified live via `test_error_envelope.py` for 404 and 405 paths, and consumed correctly by `frontend/src/lib/apiClient.ts` (`ApiError` class). |
| Repository abstraction | Confirmed | `backend/app/repositories/base.py` is the only type domain/route code depends on; `dependencies.py` is the sole composition root selecting `MockRepository`/`GoogleSheetsRepository` by `DATA_REPOSITORY`. |
| Storage abstraction | Confirmed | `backend/app/storage/base.py` / `local.py`; `storage_ref` is an opaque UUID-based string, not a raw path, so a future Drive/object-storage swap needs no caller changes. |
| Local development configuration | Confirmed | `.env.example` matches `Settings` field names exactly; `pydantic-settings` loads `.env`; ports/mode configurable. |
| Stable ID principle | Confirmed (as a documented convention) | `backend/app/domain/common.py` docstring + `API_CONVENTIONS.md`. Not yet exercised by a real generated ID since no entity exists — this is a coverage gap, not a contract violation (see Section A). |
| Timezone-aware API timestamps | Confirmed | `utc_now()` returns a UTC-aware `datetime`; independently re-verified in this audit that Pydantic v2 serializes such a value with a trailing `Z` (`{"ts":"2026-09-12T09:03:48.276970Z"}`), matching the documented claim exactly. No endpoint returns a timestamp yet, so this is verified at the utility level, not end-to-end. |
| Thai user-facing UI | Confirmed | Every rendered string in `NavBar.tsx`, `HomePage.tsx`, `SystemStatusPage.tsx`, `ConfirmDialog.tsx`, all state components is Thai; nav toggle uses Thai `aria-label`s even for the symbolic ☰/✕ button. |
| English backend/domain codes | Confirmed | Error `code` values (`NOT_FOUND`, `VALIDATION_ERROR`, `INTERNAL_ERROR`, `HTTP_ERROR`), `repository_mode` (`mock`/`google_sheets`), field names all English. |
| Mobile-first responsive foundation | Confirmed | See Section F. |
| No browser → Google Sheets direct access | Confirmed | Frontend has no Google API imports/credentials anywhere; `apiClient.ts` only calls `/api/v1/...` through the Vite dev proxy. |
| No browser → ESP32 direct access | Confirmed (trivially) | No ESP32/device code path exists in the frontend; not yet applicable but not violated. |
| No Google Sheets row-number identity | Confirmed | `GoogleSheetsClient`/`SheetTabSchema` docstrings and design explicitly forbid row-position identity and mandate header-name mapping; no domain table exists yet to violate this. |
| Backend authoritative for business logic | Confirmed (trivially) | No business logic exists yet in either frontend or backend beyond health/readiness, so there is no duplication to find. |

**No conflicts found** between the Phase 1 implementation and current governance documents.

---

## D. Architecture Review

**Frontend**
- React/TypeScript/Vite structure is clean: `src/components/`, `src/pages/`, `src/lib/` separation; no stray files.
- No direct persistence access: only `apiClient.ts` performs `fetch`, always against `/api/v1/...`.
- Reusable responsive components exist and are actually reused (not just declared): `Card` is the base of 4 state components + the System Status card; `ResponsiveTable` and `FormField` are used/tested independently of any single page.

**Backend**
- FastAPI application structure: `main.py` (app factory) / `config.py` / `context.py` / `errors.py` / `dependencies.py` / `api/v1/` / `domain/` / `repositories/` / `storage/` — a standard layered layout.
- Router separation: `api/v1/router.py` composes sub-routers (currently just `health_router`); adding a `vehicles_router` etc. in Phase 2 requires no change to this pattern.
- Domain/service/repository boundaries: routes depend on `Repository`/`StorageProvider` abstractions only, injected via FastAPI `Depends(get_repository)`/`Depends(get_storage_provider)`. There is no separate "service" class yet because there is no business logic yet — routes calling the repository directly is appropriate at this scope and does not violate the future boundary (services will sit between routes and repositories starting Phase 2).
- Configuration isolation: all env-derived state lives in `config.py`'s `Settings`; no module reads `os.environ` directly outside it (tests set env vars only to influence `Settings`/`get_settings()`).
- Repository dependency injection: `dependencies.py` is the single composition root (`@lru_cache` singletons), with a documented test-only `reset_dependency_cache()` escape hatch used by `conftest.py`.

**Storage**
- Local storage abstraction exists and is exercised by a real round-trip test including a path-traversal rejection test (`test_rejects_path_traversal`).
- Future Google Drive/object storage remains replaceable: `StorageProvider` is a 4-method ABC; `storage_ref` is opaque, so no caller assumes filesystem semantics.

**Data**
- `MockRepository` works independently: constructs and answers `check_ready()` with zero configuration or network access.
- `GoogleSheetsRepository` is isolated behind the `Repository` interface; its `GoogleSheetsClient` intentionally imports no Google SDK yet, so mock-mode installs/tests never need Google dependencies.
- PostgreSQL can later be added without frontend redesign: adding it is "implement `Repository`, add one branch in `dependencies.py`" — no route or frontend code needs to change, consistent with the baseline's Section 2 rule 8.

No architectural defects found.

---

## E. Security / Secrets Review

- `git ls-files` search for `.env`, `credential*`, `secret*`, `*.pem`, `*.key`, `service-account*` returned **no matches** — no such files are tracked.
- `.gitignore` explicitly covers: `.env`, `.env.local`, `.env.production`, `*.pem`, `*.key`, `credentials.json`, `service-account*.json`, plus `data/`/`uploads/` (local upload dir) and `*.db`/`*.sqlite*`.
- `.env.example` contains only placeholder/default values (`GOOGLE_SHEET_ID=`, `GOOGLE_APPLICATION_CREDENTIALS=` both empty; no token, password, or key anywhere in the file).
- No hard-coded API keys, tokens, passwords, or private keys were found in any backend or frontend source file reviewed.
- Development auth mode is not represented as production security: `DEV_AUTH_MODE` is logged as a loud warning on startup ("This mode must never be enabled in production"), and `create_app()` raises `RuntimeError` at startup if `APP_ENV=production` and `DEV_AUTH_MODE=true` simultaneously — this was read directly in `main.py` and is a real (not documentation-only) guard.
- No secret values are reproduced in this report.

No security/secrets defects found.

---

## F. Mobile / Responsive Review

| Requirement | Status | Evidence |
|---|---|---|
| Smartphone portrait | Confirmed | Playwright project `smartphone-portrait` (375×667), 4/4 tests pass. |
| Smartphone landscape *capability* | Partially confirmed | CSS breakpoints (`481px`, base rules) are written to support this width range, but **no automated test runs at a landscape viewport** (e.g. ~667×375). This is a genuine test-coverage gap, not a CSS/architecture defect — see "known limitation" below, per the task's own instruction not to fail Phase 1 solely for this. |
| Tablet | Confirmed | Playwright project `tablet-portrait` (768×1024), 4/4 tests pass. Tablet-landscape (~1024×768) has a CSS breakpoint (`1024px`) but likewise no dedicated automated viewport test. |
| Desktop | Confirmed | Playwright project `desktop` (1280×800), 4/4 tests pass. |
| Responsive navigation | Confirmed | `NavBar` collapsible toggle below 641px, forced-inline above; verified by `NavBar.test.tsx` and the Playwright "mobile menu toggle" test on all 3 projects. |
| Minimum touch target | Confirmed | `--tap-target: 44px` applied to `.button`, nav toggle, nav links; Playwright "touch targets... meet the 44px minimum" test passes on all 3 viewports. |
| Thai text wrapping | Confirmed | `body { overflow-wrap: break-word; word-break: break-word }`; all rendered UI text is Thai and wraps rather than overflowing (verified via the "no unintended horizontal scrolling" Playwright assertion alongside real Thai strings on the page). |
| No hover-only dependency | Confirmed | Nav toggle and all buttons are click/tap-driven; no `:hover`-gated functionality found in `index.css` or component code. |
| Responsive table/card strategy | Confirmed | `ResponsiveTable` — CSS-only stacked-card-below-641px / real-`<table>`-above pattern; unit-tested (`data-label` per cell) and exercised live by the System Status page + Playwright. |
| Dialog behavior | Confirmed | `ConfirmDialog`/`.dialog` — full-width bottom sheet with `max-height: 90vh` + scroll on phones, centered `min(92vw, 420px)` box from tablet up; Playwright asserts the dialog's bounding box never exceeds the viewport at any of the 3 tested sizes. |
| Reusable form components | Confirmed, narrowly tested | `FormField` + `.form-grid` exist and are unit-tested (`FormField.test.tsx`: label association via `htmlFor`/`id`, error rendered with `role="alert"`), but are **not yet exercised inside a real multi-field form or by Playwright**, since no domain form workflow exists until Phase 2+. This matches the phase report's own disclosed limitation. |
| No normal horizontal scroll | Confirmed | Playwright asserts `scrollWidth <= clientWidth + 1` on the home page and the System Status page (with dialog open) across all 3 viewports. |

**Landscape orientation:** as instructed, this is reported as a **known
test-coverage limitation**, not a Phase 1 defect requiring a code change.
The CSS itself has breakpoints that address landscape widths (a
667-wide phone in landscape falls into the same `min-width: 641px` tablet
rules as a portrait tablet, which is a reasonable simplification for this
stage), but no automated assertion currently exercises a landscape-shaped
viewport specifically.

---

## G. Automated Tests — Actually Re-Run in This Verification

All commands below were executed in this session against the current
`web/phase-01-verification` branch checkout; none are assumed or copied
from the prior report without re-running.

**Backend — pytest**
```
$ bash scripts/run_backend_tests.sh -q
9 passed in 0.44s
```

**Frontend — unit/component tests (Vitest)**
```
$ npm run test     # (frontend/)
Test Files  6 passed (6)
     Tests  9 passed (9)
```

**Frontend — typecheck**
```
$ npx tsc -b       # (frontend/)
(no output; exit code 0 — PASSED)
```

**Frontend — lint**
```
$ npx oxlint       # (frontend/)
1 warning, 0 errors:
  src/pages/SystemStatusPage.tsx:65:10 warning react(set-state-in-effect)
```
Same single pre-existing warning documented in the original Phase 1
report; no new warnings introduced. Lint **PASSED** (warning-only, no
errors).

**Frontend — production build**
```
$ npm run build    # (frontend/)
✓ 36 modules transformed.
dist/index.html                   0.43 kB │ gzip:  0.31 kB
dist/assets/index-*.css           7.75 kB │ gzip:  2.10 kB
dist/assets/index-*.js          267.27 kB │ gzip: 84.82 kB
✓ built in 596ms
```
PASSED — output sizes match the original Phase 1 report exactly.

**Frontend — Playwright responsive/e2e**
```
$ npx playwright test   # (frontend/, backend+frontend dev servers auto-started)
Running 12 tests using 2 workers
  ✓ 12 passed (15.9s)
```
All 12 tests (4 tests × 3 viewport projects: smartphone-portrait,
tablet-portrait, desktop) **PASSED**.

**Summary**

| Suite | Result |
|---|---|
| Backend pytest | 9/9 passed |
| Frontend Vitest | 9/9 passed (6 files) |
| Frontend typecheck (`tsc -b`) | PASSED |
| Frontend lint (`oxlint`) | PASSED (1 pre-existing warning) |
| Frontend production build | PASSED |
| Playwright e2e | 12/12 passed |

No test was claimed without being executed in this session.

---

## H. Regression / Future Compatibility Review

| Future domain | Blocker found? | Notes |
|---|---|---|
| Vehicle/model/equipment | None | `Repository` ABC currently declares only `mode`/`check_ready`; adding vehicle CRUD methods is a pure extension, no breaking change needed to existing callers. |
| Inspection | None | Error envelope, pagination convention, and `StorageProvider` (for inspection photos) are all ready to be consumed as-is. |
| PM/repair | None | Same repository/storage/error-envelope foundation applies without modification. |
| Parts/lifetime | None | Stable opaque-ID convention (`VEH-1046`-style) is documented and generic enough for `part_instance_id` etc. |
| Alerts/events/GPS | None | `event_timestamp` vs `received_at` distinction is correctly *not* implemented yet (out of Phase 1 scope) and nothing in Phase 1 conflicts with adding it later. |
| IoT/device integration | None | `API_CONVENTIONS.md` already documents that device routes will be "logically separate" with their own prefix in Phase 8 — Phase 1 does not entangle Web routes with a future device contract. |
| PostgreSQL repository migration | None | This is precisely what `dependencies.py`'s composition-root pattern and the `Repository` ABC were built for; `DataRepositoryMode.POSTGRESQL` already exists as an enum value, just not yet implemented (`NotImplementedError`), which is correct sequencing rather than a blocker. |

No architectural blockers were identified for any later phase. This
review does not redesign or begin any later phase.

---

## I. Manual Acceptance Plan

1. **Backend health endpoint** — Run `./scripts/run_backend.sh`, then
   `curl http://127.0.0.1:8000/api/v1/health`; expect
   `{"status":"ok","app_env":"development"}` and an `X-Request-Id` response header.
2. **Readiness endpoint** — `curl http://127.0.0.1:8000/api/v1/readiness`
   with `DATA_REPOSITORY=mock`; expect `"ready": true`,
   `"repository_mode": "mock"`. Repeat with `DATA_REPOSITORY=google_sheets`
   and no `GOOGLE_SHEET_ID` set; expect `"ready": false` with a clear reason.
3. **Thai UI shell** — Run `./scripts/run_dev.sh`, open
   `http://127.0.0.1:5173/`; confirm the nav brand ("ระบบบำรุงรักษาเครน"),
   page heading, and footer render in Thai with no untranslated English
   user-facing strings.
4. **Mobile navigation** — With the browser devtools set to a ~375px-wide
   device, confirm the `☰` toggle appears, tapping it reveals "หน้าหลัก" /
   "สถานะระบบ" links, and tapping a link navigates and collapses the menu.
   Repeat at ≥641px and confirm the toggle disappears and the links are
   always visible.
5. **Responsive table/card behavior** — Open `/system-status` at ~375px;
   confirm the readiness checks render as stacked labeled cards. Widen to
   ≥641px; confirm the same data renders as an ordinary table with a header row.
6. **Confirmation dialog** — On `/system-status`, tap "โหลดสถานะใหม่";
   confirm the dialog appears as a bottom sheet at phone width (never
   taller/wider than the viewport, scrollable if needed) and as a centered
   box at ≥641px; confirm both "ยืนยัน"/"ยกเลิก" actions work and no
   background scroll or page overflow appears while it is open.
7. **Desktop rendering** — At ≥1280px width, confirm the content column is
   comfortably centered (not stretched full-bleed), nav renders inline, and
   no layout looks like an unstyled/unfinished desktop page.
8. **OpenAPI docs** (baseline acceptance item) — With the backend running,
   open `http://127.0.0.1:8000/docs` and confirm the Swagger UI lists
   `/api/v1/health` and `/api/v1/readiness`.

---

## J. Final Verdict

**PASS WITH KNOWN LIMITATIONS**

**Blocking defects:** None.

**Known limitations:**
- Automated viewport coverage tests smartphone-portrait, tablet-portrait,
  and desktop only; no dedicated smartphone-landscape or tablet-landscape
  automated Playwright project exists yet, even though the underlying CSS
  breakpoints target those widths (per instructions, this is reported as a
  coverage limitation, not a defect requiring a Phase 1 change).
- Mobile/tablet Playwright projects emulate viewport/`isMobile`/`hasTouch`
  on Chromium rather than using WebKit-based device presets, because only
  Chromium is pre-installed in this environment; Safari/iOS-specific
  rendering quirks are not covered by the automated suite.
- The responsive form pattern (`FormField`/`.form-grid`) is unit-tested
  only; it has not yet been exercised inside a real multi-field form or a
  Playwright test, since no domain form workflow exists until Phase 2+.
- `ResponsiveTable`'s CSS-only stacking (`data-label` pseudo-content) has
  the well-known accessibility trade-off of not being exposed identically
  to all screen readers versus a semantic mobile list — acceptable for
  Phase 1's single (system status) usage.
- The stable-ID and pagination conventions are documented and the UTC/`Z`
  timestamp serialization behavior was independently re-verified in this
  audit, but none of them are yet exercised end-to-end by a real domain
  endpoint, since no domain entity exists until Phase 2.
- `DEV_AUTH_MODE` + `APP_ENV=production` startup guard was verified by
  reading `main.py`; it has no dedicated automated test.

**Unapproved decisions found:** None. Every open-decision item reachable
by Phase 1 code is either genuinely out of Phase 1's scope or implemented
exactly as governance documents direct for this stage (see Section B).

**Frozen contracts confirmed:** `/api/v1` convention; common error
envelope; repository abstraction; storage abstraction; local development
configuration; stable-ID principle (as a documented convention); UTC ISO-8601
timestamp convention; Thai user-facing UI; English backend/domain codes;
mobile-first responsive foundation; no browser→Google Sheets access; no
browser→ESP32 access; no Google Sheets row-number identity; backend
authoritative for business logic (trivially, pending real logic).

**Future-phase architectural blockers:** None identified for
vehicle/model/equipment, inspection, PM/repair, parts/lifetime,
alerts/events/GPS, IoT/device integration, or the PostgreSQL repository
migration.

**Phase 1 approval status remains valid: YES**
