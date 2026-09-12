REVISION NOTE: This report was updated after the baseline/phase prompt
files were revised on the branch to add the "MOBILE-FIRST / RESPONSIVE
WEB REQUIREMENT" (baseline) and "MOBILE-FIRST FOUNDATION REQUIREMENT"
(Phase 1 file). This revision re-reads both updated files and documents
the additional mobile-first work folded into the same Phase 1 (no new
phase was started). Everything in the original report remained valid;
sections below are updated in place where mobile-first work changed
them, and new mobile-first-specific content is added.

PHASE: Web/API Phase 1 — Foundation, Local Development Stack, API Contracts, Repository Abstraction, and Thai UI Shell (incl. mobile-first responsive foundation)
STATUS: PASS

OBJECTIVE:
Create a local-development application (backend + frontend) that runs
immediately on the user's computer with no production server and no
Google credentials, and freeze the architecture boundaries (API
versioning, error envelope, repository/storage abstraction, environment
configuration, shared API client, date/time and ID conventions, Thai UI
shell, request/user context) so later phases can plug in without
redesign. Following the baseline update, Phase 1 must also establish —
and freeze — the mobile-first responsive UI foundation (breakpoints,
mobile navigation, reusable card/table/form/dialog patterns, touch
targets) that later phases build real workflows on top of.

PREREQUISITE CHECK:
- 00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt — read in full, including the
  added "MOBILE-FIRST / RESPONSIVE WEB REQUIREMENT" section.
- 00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt — read in full
  (unchanged in this update).
- 01_PHASE1_FOUNDATION_LOCAL_STACK_EN.txt — read in full, including the
  added "MOBILE-FIRST FOUNDATION REQUIREMENT" section.
- Repository inspected before the original implementation: contained
  only `docs/claude-prompts/`, `.env.example`, `.gitignore`, `README.md`.
  Result: repository was "empty" per the baseline's Section 2 rule, so
  the default stack (Python/FastAPI/Pydantic/Uvicorn + React/TypeScript/
  Vite) was used and remains unchanged by this update.
- Toolchain verified available: Python 3.11.15, Node 22.22.2, npm
  10.9.7. Pre-installed Chromium (`/opt/pw-browsers/chromium`) verified
  available for the new smartphone-viewport Playwright tests.

FROZEN CONTRACTS USED:
None from a prior phase (this is still Phase 1). This revision itself
freezes the mobile-first UI foundation described below (breakpoints,
mobile nav pattern, `Card`/`ResponsiveTable`/`FormField`/dialog
patterns, `--tap-target` touch-target convention) — see
`docs/architecture/RESPONSIVE_UI.md`.

FILES ADDED (this mobile-first update, in addition to the original Phase 1 file list):
- `docs/architecture/RESPONSIVE_UI.md` — frozen breakpoints and the
  reusable mobile-first patterns (shell/nav, card, responsive table,
  form, dialog, touch targets), and how they are tested.
- `frontend/src/components/Card.tsx` — reusable mobile-friendly card,
  now the base of `LoadingState`, `EmptyState`, `ErrorState`,
  `PermissionDeniedState`, and the System Status page.
- `frontend/src/components/ResponsiveTable.tsx` (+ `.test.tsx`) —
  CSS-only responsive table/list pattern (table on tablet+, stacked
  labeled cards on phones). Used by `SystemStatusPage` for the
  readiness checks list.
- `frontend/src/components/FormField.tsx` (+ `.test.tsx`) — reusable
  responsive form field pattern (full-width, 44px-min-height inputs,
  label above input) for later phases' real forms.
- `frontend/src/components/NavBar.test.tsx` — verifies the mobile menu
  toggle starts collapsed, expands, and closes after choosing a link.
- `frontend/playwright.config.ts`, `frontend/e2e/responsive-shell.spec.ts`
  — real-browser (Chromium) viewport tests at smartphone-portrait
  (375×667), tablet-portrait (768×1024), and desktop (1280×800),
  satisfying the phase's new requirement for "at least one smartphone-
  size rendering test."
- `scripts/run_e2e_tests.sh` — runs the Playwright suite (starts
  backend + frontend automatically via Playwright's `webServer` config).

FILES MODIFIED (this mobile-first update):
- `frontend/src/index.css` — rewritten mobile-first: base rules target
  smartphone portrait with no media query; `min-width` breakpoints at
  481 / 641 / 1024 / 1280px only add/adjust rules for larger screens.
  Added `--tap-target: 44px`, 16px base font (avoids iOS input auto-zoom
  and improves readability at increased font scaling), `overflow-wrap`
  for long Thai/URL text, CSS-only responsive table pattern, responsive
  form pattern, a bottom-sheet-on-phone / centered-on-tablet+ dialog that
  always fits the viewport (`max-height` + internal scroll), and a
  `.sticky-actions` utility reserved for later long-scrolling workflows.
- `frontend/src/components/NavBar.tsx` — added the mobile navigation
  pattern: a `☰`/`✕` toggle button (44px touch target, `aria-expanded`,
  `aria-controls`) that shows/hides the link list below tablet width; the
  list is forced always-visible by CSS from tablet width up regardless of
  toggle state, and the toggle itself is hidden there.
- `frontend/src/components/LoadingState.tsx`, `EmptyState.tsx`,
  `ErrorState.tsx`, `PermissionDeniedState.tsx` — now render via the
  shared `Card` component instead of ad hoc panel markup, so they share
  one mobile-friendly container styling.
- `frontend/src/pages/SystemStatusPage.tsx` — readiness checks now use
  `ResponsiveTable` (was a plain `<ul>`); the "reload status" button uses
  the new `.button--full-width` pattern (full width on phones, auto width
  from tablet up).
- `frontend/vite.config.ts` — excludes `e2e/**` from the Vitest run
  (Playwright specs are a separate test runner/command).
- `frontend/package.json` — added `test:e2e` script and the
  `@playwright/test`, `@testing-library/user-event` devDependencies.
- `README.md`, `frontend/README.md` — document the responsive UI
  foundation and the new `test:e2e` / `run_e2e_tests.sh` commands.
- `.gitignore` — ignore Playwright's `test-results/`, `playwright-report/`,
  `blob-report/`.

API ROUTES ADDED:
None new in this update (`GET /api/v1/health`, `GET /api/v1/readiness`
from the original Phase 1 implementation are unchanged).

DATABASE / SHEET TABLES USED:
None (unchanged — still correctly out of scope for Phase 1).

UI PAGES ADDED:
None new in this update. Both existing pages (`/` HomePage, `/system-status`
SystemStatusPage) were updated to use the new mobile-first components
(`Card`, `ResponsiveTable`, full-width buttons).

IMPLEMENTATION SUMMARY:
Mobile-first responsive foundation, addressing each item in the phase
file's "MOBILE-FIRST FOUNDATION REQUIREMENT" list:
- Mobile-first CSS/layout strategy — `index.css` rewritten so base rules
  target the smallest phone and larger viewports are additive
  `min-width` overrides only.
- Responsive application shell — `AppLayout`/`NavBar`: sticky header,
  single fluid content column, no fixed desktop-only width at any
  breakpoint.
- Mobile navigation — `NavBar`'s collapsible `☰` menu (large touch
  target, keyboard/AT-friendly via `aria-expanded`/`aria-controls`,
  closes itself on navigation), forced inline from tablet width up.
- Tablet and desktop adaptation — verified breakpoints at 641px
  (tablet) and 1024/1280px (desktop): nav goes inline, content padding
  and heading size increase, `.responsive-table` switches from stacked
  cards to a real `<table>`, `.dialog` switches from a bottom sheet to a
  centered box, `.form-grid--two-column` becomes two columns.
- Reusable mobile-friendly cards — `Card` component; used by every state
  panel and the System Status card.
- Responsive table/list pattern — `ResponsiveTable`: CSS-only via
  `data-label` on each `<td>`; degrades to real semantics (no JS
  resize listener needed).
- Responsive form pattern — `FormField` + `.form-field`/`.form-grid`
  CSS: full-width, 44px-minimum inputs, label above input; established
  for later phases' inspection/PM/repair forms (no real form workflow
  exists yet in Phase 1's scope to attach it to, so it is unit-tested
  directly, matching how `ConfirmDialog`/`PermissionDeniedState` were
  already established in the original Phase 1 without a real workflow).
- Responsive dialog/modal pattern — `ConfirmDialog`'s `.dialog` is a
  full-width bottom sheet with `max-height: 90vh` + internal scroll on
  phones, and a centered `min(92vw, 420px)` box on tablet/desktop —
  verified never to exceed the viewport at any tested size.
- Large touch-friendly controls / no hover-only interaction — `.button`,
  the nav toggle, and nav links all use `--tap-target: 44px` as a
  minimum; nothing in the shell requires `:hover` to be usable (already
  true of the original `NavLink`-based nav, now also true of the new
  toggle button).
- Thai text wrapping — `body { overflow-wrap: break-word; word-break:
  break-word }` so long unbroken Thai strings/URLs wrap instead of
  causing horizontal overflow.
- Smartphone viewport testing — new Playwright suite (see TESTS ACTUALLY
  PERFORMED) runs the real app in Chromium at 375×667/768×1024/1280×800
  and asserts no horizontal scrolling, 44px+ touch targets, working
  mobile nav toggle, and a dialog that fits the viewport — satisfying
  "Phase 1 acceptance must include at least one smartphone-size
  rendering test."

Because only Chromium is pre-installed in this environment (no WebKit),
the Playwright config emulates the phone/tablet viewports on Chromium
directly (explicit viewport/isMobile/hasTouch/deviceScaleFactor) rather
than via Playwright's built-in `devices['iPhone SE']` / `devices['iPad
Mini']` presets, which default to WebKit and are unavailable in this
environment; this still exercises the same CSS breakpoints, mobile
input flags, and touch interaction the acceptance tests care about.

LOCAL STARTUP COMMANDS:
```
cp .env.example .env

./scripts/run_backend.sh     # http://127.0.0.1:8000 (creates venv, installs deps)
./scripts/run_frontend.sh    # http://127.0.0.1:5173 (npm install on first run)
# or both together:
./scripts/run_dev.sh

./scripts/run_backend_tests.sh
./scripts/run_frontend_tests.sh
./scripts/run_e2e_tests.sh    # NEW: Playwright smartphone/tablet/desktop viewport tests
```
OpenAPI docs: http://127.0.0.1:8000/docs

BUILD / TYPECHECK / LINT RESULT (re-run after the mobile-first changes):
- Backend: unchanged by this update; `python -m pytest` still exercises
  the full app import graph (see TEST RESULTS).
- Frontend typecheck: `npx tsc -b` — PASSED, no errors.
- Frontend production build: `npm run build` — PASSED. Output:
  `dist/index.html` 0.43 kB, `dist/assets/*.css` 7.75 kB (2.10 kB gzip,
  up from 4.44 kB pre-mobile-first due to the new responsive
  table/form/dialog/nav CSS), `dist/assets/*.js` 267.27 kB (84.82 kB
  gzip).
- Frontend lint: `npx oxlint` — PASSED with the same single pre-existing
  warning as the original report (`react/set-state-in-effect` on
  `SystemStatusPage.tsx`'s data-fetch effect); no new warnings introduced.
- `npm audit`: 0 vulnerabilities (`@playwright/test`,
  `@testing-library/user-event` added cleanly).

TESTS ACTUALLY PERFORMED:
Backend — unchanged, re-run to confirm no regression
(`./scripts/run_backend_tests.sh -q`): 9 passed.

Frontend unit/component tests (`./scripts/run_frontend_tests.sh` /
`npx vitest run`) — now 6 test files / 9 tests (up from 3 files / 3
tests):
- `src/App.test.tsx` — Thai nav brand + home heading render.
- `src/components/StatusBadge.test.tsx` — renders the given Thai label.
- `src/components/FormField.test.tsx` (NEW) — label/input association
  via `htmlFor`/`id`; error message rendered with `role="alert"`.
- `src/components/ResponsiveTable.test.tsx` (NEW) — each cell carries
  the correct `data-label`; Thai empty state renders when there are no
  rows.
- `src/components/NavBar.test.tsx` (NEW) — menu starts collapsed
  (`is-open` absent, `aria-expanded="false"`), expands on toggle click,
  and collapses again after a link is chosen.
- `src/pages/SystemStatusPage.test.tsx` — Thai loading message, then
  (mocked `fetch`) the resolved status, still passing with the
  `ResponsiveTable`/`Card`-based markup.

Frontend end-to-end viewport tests (NEW; `./scripts/run_e2e_tests.sh` /
`npx playwright test` in `frontend/`, real Chromium against the actual
Vite dev server + FastAPI backend, both started automatically by
Playwright's `webServer` config) — 12 tests across 3 viewport projects:
- `smartphone-portrait` (375×667), `tablet-portrait` (768×1024),
  `desktop` (1280×800), each running:
  - "home page has no unintended horizontal scrolling" — asserts
    `document.documentElement.scrollWidth <= clientWidth`.
  - "touch targets in the nav meet the 44px minimum" — measures the nav
    toggle (where visible) and the "หน้าหลัก" link's bounding box.
  - "mobile menu toggle expands and collapses navigation" — on
    smartphone-portrait: toggle is visible, expands the menu, clicking
    "สถานะระบบ" navigates to `/system-status`; on tablet-portrait/desktop:
    toggle is hidden and the menu is already visible (CSS-forced).
  - "system status page renders and the confirmation dialog fits the
    viewport" — health/readiness render, opens `ConfirmDialog`, asserts
    the dialog's bounding box never exceeds the viewport's width/height,
    and no horizontal scrolling appears afterward.

Manual verification (in addition to the automated Playwright suite):
started both dev servers and used a throwaway Playwright/Chromium script
to screenshot the home page at 375×667 with the nav collapsed and
expanded, and the System Status page with the confirmation dialog open,
confirming visually that the hamburger menu, the `ResponsiveTable`
stacked-card layout, and the bottom-sheet dialog render as intended. Both
dev servers were stopped afterward.

TEST RESULTS:
- Backend: 9 passed, 0 failed (unchanged).
- Frontend unit/component: 9 passed, 0 failed, across 6 files (up from 3/3/3).
- Frontend e2e (Playwright): 12 passed, 0 failed, across 3 viewport
  projects × 4 tests.
- Frontend typecheck + build: passed.
- Manual visual verification: as described above, matched expectations.

SCREEN / UX NOTES:
- All rendered UI text remains Thai; no new English-only user-facing
  text was introduced by the mobile-first work (the nav toggle uses
  symbolic ☰/✕ glyphs with Thai `aria-label`s "เปิดเมนู"/"ปิดเมนู").
- Below tablet width (≤640px): nav collapses behind the toggle; the
  System Status readiness list renders as stacked labeled cards instead
  of a table; `ConfirmDialog` renders as a full-width bottom sheet with
  stacked full-width Confirm/Cancel buttons.
- From tablet width up (≥641px): nav renders inline and the toggle
  disappears; the readiness list renders as an ordinary table; the
  dialog becomes a centered `min(92vw, 420px)` box with side-by-side
  buttons.
- No layout at any tested width (375/768/1280px) produces horizontal
  scrolling; verified both by the Playwright assertions and visually via
  screenshots.
- No mobile/device QR testing was performed (no vehicle routes exist
  yet); still correctly scoped to Phase 2 once `/vehicle/{id}` exists.
  Camera/photo capture and the specific mobile Vehicle Detail/Inspection
  layouts described in the baseline addendum are implemented starting
  Phase 2/3, reusing the `Card`/`ResponsiveTable`/`FormField`/dialog
  primitives frozen here.

TBD VALUES REMAINING:
- None blocking Phase 1. Same as the original report: real Google
  Sheets credentials, PostgreSQL, RBAC enforcement, and all domain
  entities remain out of scope until their respective phases. The
  `.sticky-actions` CSS utility is defined but intentionally unused
  until a later phase has a long-scrolling workflow to apply it to.

KNOWN LIMITATIONS:
- All limitations from the original report still apply unchanged
  (`GoogleSheetsRepository` config-only readiness check, the
  `react/set-state-in-effect` lint warning, no RBAC yet, no CI pipeline).
- Mobile/tablet Playwright projects emulate viewport + `isMobile` +
  `hasTouch` + `deviceScaleFactor` on Chromium rather than using
  Playwright's WebKit-based device presets, because only Chromium is
  pre-installed in this environment. Real Safari/iOS-specific rendering
  quirks are therefore not covered by the automated e2e suite; the CSS
  itself (16px base font, standard flex/grid, no WebKit-specific hacks)
  is not expected to differ meaningfully, but this is not verified by
  automated tests in this environment.
- The responsive form pattern (`FormField`, `.form-grid`) is verified by
  unit test only; it is not yet exercised inside a real multi-field form
  or a Playwright test, since no domain form workflow exists until
  Phase 2+. Its "keyboard opening does not hide the current input/action"
  acceptance point (baseline's mobile acceptance test #16) can only be
  meaningfully verified once a real form with multiple stacked inputs
  exists.
- `ResponsiveTable`'s CSS-only stacking technique has one known
  accessibility trade-off shared by this well-known pattern: the
  `data-label` pseudo-content is not exposed to all screen readers the
  same way a semantic mobile list would be. Acceptable for Phase 1's
  single demonstration usage (system status checks); worth revisiting if
  a later phase's table carries safety-critical information.

RISKS / CONCERNS:
- None identified that block Phase 2. The mobile-first patterns are
  exercised by both component tests and real-browser viewport tests
  (not just described in docs), so Phase 2's Vehicle/Equipment detail
  pages can build on `Card`/`ResponsiveTable`/`FormField`/`ConfirmDialog`
  with reasonable confidence they already behave correctly at phone,
  tablet, and desktop widths.

ANY CHANGE TO PREVIOUS FROZEN PHASES:
NONE — this is still Phase 1. No contracts frozen by the original Phase
1 report (API versioning, error envelope, repository/storage interfaces,
etc.) were changed; this update only adds the previously-missing
mobile-first UI foundation the revised baseline/phase files now require,
and freezes it alongside the rest of Phase 1's output.

NEXT PHASE READINESS:
READY

STOP HERE.
DO NOT IMPLEMENT THE NEXT PHASE.
