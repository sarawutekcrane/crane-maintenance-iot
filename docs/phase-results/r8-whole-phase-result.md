# R8 — Whole-Phase Result (Phase 7 closure work + early Crew + Resource Calendar)

STATUS: **IMPLEMENTATION REVIEW CANDIDATE — NOT ACCEPTED**

This report records the R8 Mock/TEST source implementation on `feature/r8-whole-phase`, built on base
`911da0b080dcea096bbec6023ad4acd5a0056181` as an **uncommitted** working tree, under the Owner source approval of
2026-11-18, plus the one-file Owner gate of the same day for `backend/tests/test_access_management.py`. That approval covered the R1 read-only pack's allowlist and the choices OD-1 = A, OD-2 = A, OD-3 = A, OD-4 = A,
S5 = A, S7 acknowledged, A-5 acknowledged, OD-6, OD-7 = A and SG-1 = A.

This report is **not** an R8 acceptance, not a Phase 7 closure verdict, not PostgreSQL evidence and not production readiness.
It also does not mean Phase 8 has started. Passing implementation tests does not accept the phase. Acceptance needs an
independent implementation review, a separate exact-path Owner Git Gate, the open STOP gates below, and the EXTERNAL
items (OD-6).

Google Sheets is TEST-ONLY. Sheets-only problems were simulated, not fixed. Cross-storage and PostgreSQL risks are recorded
as R11 obligations. A Mock pass is not a PostgreSQL pass.

## 1. Requirement status (Master Roadmap §4 R8)

| ID | Implemented | Status |
|---|---|---|
| R8-01 | The six KPIs are unchanged. Each card links to `/vehicles?status=…[&branch_id=…]`. The total card links to the unfiltered or branch list. | IMPLEMENTED (Mock/TEST) |
| R8-02 | Vehicle-list filters and page number live in the URL. The vehicle page shows "กลับไปรายการที่กรองไว้" using router state checked by `safeListFrom`. | IMPLEMENTED |
| R8-03 | New `GET /vehicles/{id}/machine-state`: requires a trusted reader with `can_view`, returns no GPS, and reuses `MeterService.preview_current_state`. Meters appear on the vehicle page with update time and quality. | IMPLEMENTED |
| R8-04 | The vehicle summary uses only guarded reads: meters, PM due, open repairs, finding follow-up (now guarded), part lifetime, alerts. Each section checks the response shape and shows "ไม่ทราบ" rather than 0. Certificates are a link only, so no read triggers a write. | IMPLEMENTED |
| R8-05 | The latest location says "ตำแหน่งที่บันทึกล่าสุด ไม่ใช่ตำแหน่งสด" and gives its age, with no threshold. The route now requires a trusted `can_view` reader. | IMPLEMENTED; the final H03 policy is an OWNER GATE before REAL |
| R8-06 | Online/offline is a placeholder: "รอเชื่อมต่ออุปกรณ์ (Phase 8)". | DEFERRED → R9 |
| R8-07 | Flexible search (7J2) is unchanged; covered by regression. The S3 type filter is closed as "not wanted". | EXISTING |
| R8-08 | Handled per item, as in R1 OD-5. A-3 and A-6a/b/e are WAIVED_NONPRODUCTION (Sheets adapter). The A-4 URL part is DEFERRED to R12 ID validation. New R8 links follow ED-13. | DISPOSITIONED |
| R8-09 | New `GET /reports/part-lifetime-due` (trusted reader, test-batch scope, page size ≤ 50) and its page. UNKNOWN is never shown as NOT_DUE. NO_APPLICABLE_RULE is a separate status. Out-of-scope vehicles are counted. Fleet PM Due gets a branch filter. | IMPLEMENTED |
| R8-10 | Deferrals listed in §4 with their target phase. | DISPOSITIONED |
| R8-11 | In-container runs: see §6. Windows, real devices and Firefox/WebKit are not run. | PARTIAL / EXTERNAL |
| R8-12 | New Thai menu items "อายุอะไหล่ถึงกำหนด" and "ปฏิทินทรัพยากร". No existing ID or path changed. On a short landscape screen (≥ 641 px wide, ≤ 500 px tall) the menu uses the existing collapsed toggle, because the extra items would otherwise wrap into a sticky bar covering most of a 375 px-tall screen. Taller screens are unchanged, except that the desktop inline bar can wrap one more row. | IMPLEMENTED |
| R8-S1 | Optional exact `branch_id` on `/dashboard/fleet-status`, sharing one predicate with the list, so the counts match. The unfiltered response body is unchanged (`response_model_exclude_none`). | IMPLEMENTED |
| R8-S2 | Vehicle page as R8-03/04/05. The device part waits for R9. | IMPLEMENTED / DEFERRED (device) |
| S5 | `GET /vehicles?has_open_alert=true` requires a trusted `can_view` reader **before** any alert read. The unfiltered list is unchanged. Uses OWNER-GATED paths that S5 = A unlocked. | IMPLEMENTED |
| S7 | Search by location is not practical now: no worksite or geo master exists, and H03 privacy is undecided. | DEFERRED with finding (R9/R12), acknowledged |
| R8-X | This report. The Phase 7 closure verdict stays with the Owner. | CANDIDATE |

### Early Crew + Resource Calendar (DEC-R8-CREW-CALENDAR-20261111)

| ID | Implemented |
|---|---|
| CC-01…04 | `/resource-calendar`: month (42 cells), week (7) and day views; VEHICLES / PERSONNEL / BOTH; clicking a day shows each person with their own start/end, vehicle, role and period. The window is ≤ 42 days (otherwise `CALENDAR_WINDOW_INVALID`). Vehicle rows are read in pages. |
| CC-05 / OD-1 | Crew roles RIGGER / SIGNALMAN / OTHER. OTHER requires a Thai note. Exactly one driver comes from E2 (no second driver scheduler). |
| CC-06 / CC-11 | Crew periods reuse the E2 `Schedule` (FULL_DAY / DAY_SHIFT / NIGHT_SHIFT, half-open intervals, Asia/Bangkok). New append-only `crane_crew_assignment_history`. Operations are CREATE / REVISE / CANCEL / EARLY_END (OD-4); there is no SUBSTITUTE / H2 / H3. |
| CC-07…09 / OD-2 | Person-axis conflicts cover crew×crew, crew×E2 and E2×crew, through the personnel↔driver link (LINKED / UNLINKED / AMBIGUOUS). An overlap with an unlinked or ambiguous identity is refused with `CROSS_ROLE_IDENTITY_UNVERIFIED`, for that interval only. A verified overlap returns `RESOURCE_CONFLICT`. Adjacent assignments give the warning `PERSON_ADJACENT_ASSIGNMENT_REST_WARNING` only. |
| CC-10 / CC-12 | E2 derivation is unchanged: 123 existing E2 tests pass unmodified. E2 CREATE / REVISE / SUBSTITUTE now also run the crew-person check and use the two-stream append. |
| OD-3 | `can_assign_crane_crew` is in AM group H and SENSITIVE. It is held only through a per-employee TEST grant: no default role holder, no root holder, no REAL grant. Writes need a verified AM actor plus `can_view`; otherwise `CREW_ASSIGNMENT_NOT_AUTHORIZED` / `ACCESS_ACTOR_NOT_VERIFIED`. REAL writes return 409 `CREW_REAL_WRITES_NOT_ENABLED`. Google Sheets returns `RepositoryFeatureNotImplementedError` (501). |
| D6 | The crew POST is added to the D6 write-route inventory, additively, as `R8_CREW_WRITE_ROUTES`, in the default verified-employee class (neither unresolved nor recovery). The inventory goes from 107 to 108 routes. |
| OD-7 | The fleet calendar requires a trusted actor with `can_assign_crane_driver` OR `can_assign_crane_crew`. It returns no GPS. PII is limited to names (driver names only for unlinked drivers). |
| CC-15 | The Mock guard checks the row counts of both histories with no await before the append. This works in one process only; see §3, R11. |

## 2. Read authorization (CP-0, ED-10 / ED-11)

| Route | Before | After |
|---|---|---|
| `GET /vehicles/{id}/latest-location` | no guard | `require_trusted_reader` |
| `GET /findings/follow-up` | no guard | trusted user + a repair-read capability |
| `GET /dashboard/fleet-status` | role-based | `require_trusted_reader` |
| `GET /vehicles/{id}/machine-state` | (new) | `require_trusted_reader`, no GPS |
| `GET /vehicles?has_open_alert=true` | (new branch) | `require_trusted_reader` before the alert read |
| `GET /reports/part-lifetime-due` | (new) | `require_trusted_reader` + test-batch scope |
| crew reads / `GET /resource-calendar` | (new) | trusted reader / OD-7 capabilities |

Every guard runs before any repository read.

## 3. STOP gates

1. **Capability-set test — RESOLVED by the one-file Owner gate (2026-11-18, Owner verbatim "อนุมัติ").**
   - `backend/tests/test_access_management.py` was added as the 79th path, for this correction only.
   - The union in `test_am_catalog_maps_only_existing_capabilities_into_the_ten_categories` now also includes
     `authz.R8_TEST_ONLY_CAPABILITIES`. `ALL_CAPABILITIES`, `PENDING_CAPABILITIES` and the frozen R7
     `TEST_ONLY_CAPABILITIES` are unchanged, and the R7 exact-set test in `test_r7_document_pdf_binding.py` is not touched.
   - Narrow assertions were added in the same test. The R8 set is grantable; it is disjoint from `ALL_CAPABILITIES`, the
     R7 TEST set and every default role set; it is SENSITIVE (root-only); and the crew entry is in category H.
2. **SG-1.** Pre-existing unguarded reads stay a security STOP before REAL/Production. One example is
   `GET /machine-state/current`, which returns GPS with no guard. R8 adds no consumer of them.
3. **A-5.** The R7 certificate GET writes EXPIRED on read, with no audit row. It is retained for Mock/TEST, and R8 adds
   no caller. Before REAL, either make it pure or audit the transition (R11).
4. **R11 (PostgreSQL).** Each of these is owed before REAL:
   - one-winner writes across the E2 and crew histories (transaction plus EXCLUDE constraint or advisory locks);
   - persistent overlap safety;
   - request-id replay storage;
   - no history-ID collision;
   - an atomic status write plus history (A-6d).
5. **S7.** Location search is deferred with a finding (acknowledged).
6. **H03.** The final latest-location privacy policy is still an Owner gate before REAL.
7. **R7 E-1…E-7.** The conditional exclusions are unchanged. Their wording was not reviewed in R8.

## 4. Deferrals

- **R9:** online/offline status and device alerts (R8-06, D3, D10); the device part of the vehicle page.
- **R10:** device-driven alerts (D10, partly).
- **R11:** PostgreSQL / RBAC obligations (§3.4), A-5 for REAL, SG-1 remainder.
- **R12:** ID validation and master import checks (A-3, A-4 URL part, B-5); S7 practicality.
- **Out of scope** (not invented): booking identity, approvals, multi-role eligibility, crew per work order, overnight
  handling, substitution of crew.

## 5. Volume probe (OD-6; synthetic; no threshold)

- Setup: in-process Mock, through the ASGI app; median of 5 runs, in ms.
- Recorded while the backend test shards were running concurrently, so the numbers are indicative only.

| Read | 183 vehicles | 549 vehicles |
|---|---|---|
| dashboard fleet-status | 38.0 | 45.9 |
| dashboard + branch | 20.6 | 41.8 |
| vehicles page_size 50 | 23.1 | 51.8 |
| vehicles status + branch | 28.0 | 59.2 |
| resource-calendar 42 days BOTH | 32.4 | 96.0 |
| part-lifetime-due page_size 50 | 54.1 | 143.7 |
| vehicle machine-state | 28.8 | 36.2 |

These times say nothing about Google Sheets or PostgreSQL latency.

## 6. Tests (corrected stable snapshot C1, 2026-11-18)

- **Snapshot C1:** HEAD `911da0b` plus the uncommitted tree, after the one-file Owner-gated correction.
  - Code fingerprint: `9bb58c1a986aea1ef21c6d5b9600be2f972df83c9dc87284f5112e848767ca99`.
  - It covers 76 code files: all 79 changed paths except CHANGELOG.md, README.md and this report.
  - Identical before and after the final runs.
- **Earlier evidence superseded:** the earlier snapshot (`65d1f8ec…`, 78 paths) and its green runs are kept in the earlier
  delivery. They are **not** reused as evidence for C1.

| Run (C1) | Command | Result | Exit | Time |
|---|---|---|---|---|
| Focused backend | `pytest` on `test_access_management.py`, `test_r7_document_pdf_binding.py`, `test_access_management_security.py`, `test_r8_crew_assignment.py`, `test_r8_read_authorization.py` | 234 passed | 0 | 224 s |
| Backend full | `pytest` in 4 shards | **6565 passed, 4 skipped, 0 failed** (baseline at `911da0b`: 6390 passed, 4 skipped, 0 failed) | 0 | 500 s |
| Frontend type-check | `npx tsc -b` | ok | 0 | 13 s |
| Frontend lint | `npm run lint` | 0 errors, **29 warnings** (= baseline; no net-new warnings) | 0 | 1 s |
| Vitest | `npx vitest run` | 102 files, 1253 passed | 0 | 68 s |
| Build | `npm run build` | ok | 0 | 11 s |
| Playwright default | `npx playwright test --trace off` (includes the 667×375 photo-overflow case) | **752 passed, 0 failed, 162 skipped** | 0 | 719 s |
| Playwright AM | `ACCESS_MANAGEMENT_E2E=1 npx playwright test --trace off --workers=1` + the 4 AM-aware specs | **28 passed, 0 failed, 82 skipped** | 0 | 45 s |
| `/me` probe (scratchpad, not a repo file) | per-employee crew grant | Only the granted employee holds `can_assign_crane_crew`: not root, not the other employees | 0 | — |

The skips come from the specs themselves: by project (writes run once, on desktop) or by mode. Windows, real devices and
Firefox/WebKit are **NOT RUN / EXTERNAL**.

### C1 correction delta (vs the earlier 78-path candidate)

- **A/B:** `backend/tests/test_access_management.py` (new 79th path; one-file Owner gate) — the union is extended and the
  narrow assertions in §3.1 are added.
- **C:** a trailing blank line at end of file was removed (1 byte each, whitespace only) from 12 already-approved paths:
  - backend: `meter.py`, `meter_schemas.py`, `report_schemas.py`, `reports.py`;
  - frontend: `App.test.tsx`, `NavBar.test.tsx`, `VehicleLatestLocationCard.test.tsx`, `labels.ts`, `types.ts`,
    `FleetPmDuePage.test.tsx`, `VehicleDetailPage.test.tsx`, `VehicleListPage.test.tsx`.

  `git diff --check` is now clean.
- **D:** the 3 net-new `set-state-in-effect` warnings are removed. Each async loader in `CrewAssignmentPanel.tsx`,
  `ResourceCalendarPage.tsx` and `PartLifetimeDueReportPage.tsx` now makes one `setState` call through a small pure helper,
  the pattern `FleetStatusPage` already uses. The state for each outcome is unchanged: a malformed 200 is an error, 403 is
  denied, any other failure is an error with its code.
- **Docs:** this report, and CHANGELOG.md.

### Mutation checks (re-run on C1; each reverted; file hash verified equal to the original)

| Mutation | Result |
|---|---|
| Remove the `/findings/follow-up` capability guard | caught: 2 tests fail |
| Add a latitude field to `VehicleMachineStateResponse` | caught: 5 tests fail |
| Remove the crew-stream row-count check in the two-stream append | caught: 2 tests fail (crew one-winner; E2 append refused after a crew move) |

## 7. Git

Nothing was staged, committed, pushed, merged or released. There were no Sheets writes, no PostgreSQL changes, and no
schema or migration changes.
