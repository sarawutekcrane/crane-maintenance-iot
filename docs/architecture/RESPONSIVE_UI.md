# Mobile-First / Responsive UI Foundation (Frozen — Phase 1)

Added to the baseline after Phase 1 was first accepted
(`00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`, "MOBILE-FIRST / RESPONSIVE WEB
REQUIREMENT") and required as a Phase 1 foundation deliverable
(`01_PHASE1_FOUNDATION_LOCAL_STACK_EN.txt`, "MOBILE-FIRST FOUNDATION
REQUIREMENT"). This document and the patterns below are frozen — later
phases build real workflows (inspection, PM, repair, ...) on top of them
rather than inventing new layout primitives per page.

## Why mobile-first

Operators scan a QR code beside a crane/machine and use the phone in
their hand to inspect, report a repair, or check status. Phone usability
is the primary case, not a secondary adaptation of a desktop layout.

## Breakpoints

`frontend/src/index.css` is written mobile-first: unqualified rules
target the smallest phone, and each `@media (min-width: ...)` block only
adds/adjusts rules for larger viewports.

| Breakpoint         | Target                          |
|--------------------|----------------------------------|
| (base, no query)   | smartphone portrait (~360–480px) |
| `min-width: 481px` | smartphone landscape             |
| `min-width: 641px` | tablet portrait                  |
| `min-width: 1024px`| tablet landscape / small desktop |
| `min-width: 1280px`| desktop                          |

## Reusable patterns established in Phase 1

- **Application shell** (`AppLayout`, `NavBar`): sticky header, single
  responsive content column (`max-width: 960px`, more padding on larger
  screens), footer. No fixed desktop-only width anywhere.
- **Mobile navigation** (`NavBar`): below tablet width the link list is
  collapsed behind a `☰` toggle button (large touch target, `aria-expanded`,
  closes itself after a link is chosen); from tablet width up the CSS
  forces the list to always render inline and hides the toggle — this
  does not depend on the toggle's React state, so it works identically
  regardless of how the user last left it collapsed/expanded.
- **Card** (`components/Card.tsx`, `.card`): the base mobile-friendly
  content container. `LoadingState`, `EmptyState`, `ErrorState`,
  `PermissionDeniedState`, and the System Status page all build on it.
- **Responsive table/list pattern** (`components/ResponsiveTable.tsx`,
  `.responsive-table`): CSS-only technique — each `<td>` carries a
  `data-label` attribute. Below tablet width, rows render as stacked
  cards with the label shown next to each value; from tablet width up it
  renders as an ordinary `<table>`. Use this instead of a plain `<table>`
  for any list of records added in later phases (vehicles, PM history,
  alerts, devices, ...).
- **Responsive form pattern** (`components/FormField.tsx`, `.form-field`,
  `.form-grid` / `.form-grid--two-column`): label-above-input, full-width,
  minimum 44px input height (also avoids iOS Safari's input auto-zoom,
  since the base font size is 16px). Compose real inputs inside
  `FormField`; group fields in `.form-grid` (single column on phones, two
  columns from tablet width up via the `--two-column` modifier).
- **Dialog/modal** (`ConfirmDialog`, `.dialog`): a bottom sheet on phones
  (full width, rounded top corners, `max-height: 90vh` with internal
  scrolling, stacked full-width action buttons) that becomes a centered
  dialog box (`min(92vw, 420px)`) from tablet width up. Always fits the
  viewport at any screen height.
- **Touch targets**: `--tap-target: 44px` is the minimum height/width for
  buttons, the nav toggle, and nav links, per WCAG 2.5.5 / mobile
  platform guidance. No interaction in the shell depends on `:hover`.
- **Sticky actions utility** (`.sticky-actions`, defined but not yet used
  by any page): available for later phases with a long scrolling form
  where a primary action (submit inspection, save repair report, ...)
  should stay reachable without excess scrolling.
- **Readability**: base font-size is 16px in `rem`/`em` throughout (not
  fixed `px` heights that would clip text), so the UI stays legible when
  the browser/device font scale is increased. Thai text wraps via
  `overflow-wrap: break-word` on `body` rather than overflowing.

## What Phase 1 does not yet cover

No real domain workflow exists yet (vehicle detail, inspection, repair,
...), so the patterns above are validated using the System Status page
(which already uses `Card` and `ResponsiveTable`) and dedicated tests
rather than a full inspection/repair screen. Camera/photo capture,
sticky-action workflows, and the specific mobile Vehicle Detail/Inspection
layouts described in the baseline are implemented starting Phase 2/3,
reusing these same primitives.

## How this is tested

- Component tests (Vitest + Testing Library) verify behavior: the nav
  menu starts collapsed and expands/collapses (`NavBar.test.tsx`),
  `ResponsiveTable` emits `data-label` per cell (`ResponsiveTable.test.tsx`),
  `FormField` associates its label (`FormField.test.tsx`).
- Real-browser viewport tests (Playwright, `frontend/e2e/responsive-shell.spec.ts`,
  run via `./scripts/run_e2e_tests.sh` or `npm run test:e2e` in
  `frontend/`) load the actual dev server against smartphone-portrait
  (375×667), smartphone-landscape (568×320), tablet-portrait (768×1024),
  tablet-landscape (1024×768), and desktop (1280×800) viewports and
  assert: no unintended horizontal scrolling, touch targets meet the
  44px minimum, the mobile menu toggle works (and is hidden/unnecessary
  on larger viewports), and the confirmation dialog always fits within
  the viewport. The nav-toggle assertion is driven by the actual viewport
  width against the 641px breakpoint above, not by project name, so it
  covers every project uniformly. This satisfies the phase's requirement
  for "at least one smartphone-size rendering test" and closes the
  smartphone-landscape/tablet-landscape gap noted in
  `docs/phase-results/web-phase-02-verification.md`.
