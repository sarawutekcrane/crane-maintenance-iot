# R4 / TASK-010 — Final Consolidated Completion and R4 Closure Record — Result

**Status:** R4 FINAL CONSOLIDATED CANDIDATE, **including Independent Review Correction R2**. UNSTAGED and UNCOMMITTED, local only, waiting for independent review and
the Owner's R4 closure decision. This is Mock/Fake evidence only. It is not a PostgreSQL PASS and not Production
readiness. No Git write action was taken.

**This batch is frontend only:**
- no backend, API, schema, route, Master, Preview, digest, Work Order, Repair UI, PostgreSQL or Google Sheets change;
- no man-hour calculation;
- no production activation;
- R5 has not been started.

**Authorization:** Owner-approved R4 Final Consolidated Source Implementation on
`feature/r4-pm-readiness-reconciliation-b1`, exact base `8f1013ae68d93a8d9c101052772448e5fda5dd16` (RT4-C). The
allowlist was 4 paths; **Correction R2** (Owner-approved after independent review) extended it to **5**:
1. `frontend/src/lib/types.ts` (R4 Final)
2. `frontend/src/components/PmDueSetTable.tsx` (R4 Final)
3. `frontend/src/pages/FleetPmDuePage.test.tsx` (R4 Final)
4. `frontend/e2e/technician-v2.spec.ts` (**R2: the only newly authorized path**; a stale end-to-end expectation)
5. this document (revised for R2)

Plan: `r4-final-consolidated-completion-plan.md` (independently reviewed).

> Google Sheets TEST-ONLY. DO NOT FIX SHEETS-ONLY PROBLEMS. SIMULATE THEM. PROTECT AND FIX CROSS-STORAGE/POSTGRESQL
> RISKS. MOCK PASS ≠ POSTGRES PASS.

## 1. Preflight
| Gate | Result |
|---|---|
| Remote HEAD | `origin/feature/r4-pm-readiness-reconciliation-b1` = `8f1013a…dd16` (exact base, fetched) |
| Checkout | A fresh clone in the session scratchpad, push disabled. The primary checkout and every earlier working copy were not modified or reset. |
| Starting SHA-256 | `types.ts` `c4f9bc89…c296`, `PmDueSetTable.tsx` `eb83ece9…21d2`, `FleetPmDuePage.test.tsx` `095a5d98…ae1ea`; result doc absent |
| Backend contract | `PmDueSetResponse.planned_team_minutes: int \| None` (RT4-C, committed); unchanged by this batch (0 backend paths in the diff) |
| HEAD after work | Unchanged at the base; every change unstaged |
| **R2 preflight** | Remote re-fetched: still `8f1013a…dd16`. The existing R4 Final checkout was located and its 4 files verified **byte-identical to the exported R4 Final manifest**; 0 staged; push disabled. `technician-v2.spec.ts` starting SHA-256 `49c33b2e…4abd` (= baseline). The R4 Final changes were preserved, not recreated. |

## 2. The one remaining R4 code gap and its correction
- **Gap:** RT4-C exposed the planned TEAM elapsed duration per Set in the API, but the frontend `PmDueSet` type did not
  declare it and `PmDueSetTable` rendered no column.
- **Effect:** the Roadmap requirement ("plan time = team elapsed time, not summed man-hours") was invisible to users.

| File | Change |
|---|---|
| `types.ts` | `PmDueSet.planned_team_minutes: number \| null` (documented as TEAM_ELAPSED, not man-hours). The TypeScript and API field sets now match exactly (programmatic check: no missing or extra field on either side). |
| `PmDueSetTable.tsx` | One column, **เวลาทีมตามแผน**, immediately after **รอบ**, with the hint "เวลาที่ทีมใช้ทำงานตามแผน ไม่ใช่ชั่วโมงคน". A local pure `plannedTeamTime(minutes: unknown)` formats ONE Set's server minutes: 150 → `2 ชม. 30 นาที (150 นาที)`, 180 → `3 ชม. (180 นาที)`, 45 → `45 นาที`. Only a safe integer > 0 is a value; `null`, a missing field, `0`, negative, fractional, `NaN`, a string or a boolean give `ไม่มีข้อมูลเวลาตามแผน` (never 0, never rounded, never coerced). `data-testid="pm-due-planned"`; `data-minutes` only for a valid value. |
| `FleetPmDuePage.test.tsx` | The factory adds `planned_team_minutes: null`; 18 new test cases (§4) |

**Not done:**
- no sum across Sets, no multiplication by technician count, no man-hours or OT;
- no inference from the interval or item count;
- no effect on the server's DUE / NOT_DUE / UNKNOWN or explanation.

The shared table serves both the Fleet and the Vehicle Due screens. These are unchanged:
- Master-availability, `MASTER_NOT_ACTIVE` and `NO_ASSIGNED_PLAN` presentation;
- assignment and Plan explanations, meters and timestamps, history links;
- filters, paging, 403, TEST/REAL;
- `diagnostic_code` handling (still never used for branching).

No branch filter was added (R8). No Master activation.

## 2a. Independent Review Correction R2: stale Technician V2 end-to-end expectation
- **Discovered:** the first R4 Final Playwright run gave 692 passed, **5 failed**, 112 skipped (kept in §5).
  - All 5 failures were one test, `e2e/technician-v2.spec.ts:277` "corrupted / ambiguous data fails closed (error
    injection by route stub only)", in each viewport project.
  - It failed identically on a pristine baseline export.
- **Root cause (test drift, not a product defect):** for an injected `assignment_model: 'BROKEN'`, the spec still
  expected the pre-V2-only behavior: the title "รูปแบบการมอบหมายของงานนี้ไม่ถูกต้อง", code `ASSIGNMENT_MODEL_INVALID`, and
  the job still workable (the "บันทึกการดำเนินการ" button visible).
- **Current Owner-approved Technician V2-only contract (unchanged):** `RepairDetailPage.tsx` returns the `unsupported`
  state for any `assignment_model !== 'TECHNICIAN_V2'` **before** any further read (`load()`, lines 82–85). It shows
  only the repair id, the title "ใบงานนี้ไม่รองรับในระบบปัจจุบัน" and code `ASSIGNMENT_MODEL_UNSUPPORTED`, with no
  detail, no operation and no legacy identity. This is already unit-tested in `RepairDetailPage.test.tsx:368`
  (LEGACY / blank / unknown models).
- **Correction (spec only; the application was not changed):** only the unknown-model section of that test was
  rewritten. For `assignment_model: 'BROKEN'` (plus injected legacy `primary_technician` / `collaborators`) it now
  asserts:
  - the unsupported title and `รหัสข้อผิดพลาด: ASSIGNMENT_MODEL_UNSUPPORTED` are visible, with the repair id;
  - the normal Repair detail workflow is absent (headings "ความคืบหน้าล่าสุด" and "อะไหล่ที่ใช้จริง": 0);
  - "บันทึกการดำเนินการ" and "บันทึกการมอบหมายช่าง" are absent;
  - no legacy identifier is rendered (`/E2E-LEGACY-/`: 0);
  - **no V2 assignment GET** for the job (a counting route stub: 0).
- The test's AMBIGUOUS-set, queue-500, DATA_INVALID-row and retry sections are unchanged. No new error code; no Legacy
  fallback; no work allowed on a corrupted model.

## 3. R4 closure reconciliation
| # | R4 requirement | Classification | Evidence |
|---|---|---|---|
| A1 | PM source → Plans / Sets / Items / revisions | **MOCK_FUNCTIONAL_PASS** | `pm_source_preview.py`, `pm_master.py` (`register_preview`, `record_review`, `publish`), `pm_master_runtime.build_catalogue`; `test_pm_master_b1_mock.py`; the real native-workbook export passes the opt-in `test_r2_real_workbook_read_only_reconciliation` (260 Sets, 1146 Items, 0 REVIEW; 4 Plans build with 0 problems). Real publication is OPEN-005. |
| A2 | Published Master lineage and history | **MOCK_FUNCTIONAL_PASS** | Immutable `MasterRevision`, `resolve_lineage`, `compare_sets`, audit events, commit uniqueness; `b1_10`, `rt3a_06..10` |
| A3 | Model-variant mapping (evidence-backed) | **MOCK_FUNCTIONAL_PASS** (policy and mechanism); real approvals **OPEN_OWNER_POLICY** | RT2 approve / correct / revoke, `_check_variant_evidence` (model from the registry); `rt2_01..15`. Real: 183 candidates (incl. SL-650R), 0 conflicts, never auto-approved (OPEN-016 data) |
| A4 | Independent PM group cycles | **MOCK_FUNCTIONAL_PASS** | Source `INDEPENDENT_GROUP` (260/260); `pm_due_evidence`; `f07`, RT1 end-to-end |
| A5 | Completion-based next Due (600@650 → 1250) | **MOCK_FUNCTIONAL_PASS** | `pm_due.py` (DUE-01), SUBMIT meter anchor; `f08`, `f10`, `f10b`, `test_pm_submit_meter_anchor.py` |
| A6 | CARRIER / CRANE / odometer separation | Rules **MOCK_FUNCTIONAL_PASS**; real topology **OPEN_SOURCE_DATA** | `OWNER_HOUR_RULE`, KM odometer, PTO excluded; `f05`, `f06`. Real `vehicle_component` 0 rows, model `component_roles` blank (OPEN-012) |
| A7 | Missing meter / completion → UNKNOWN | **MOCK_FUNCTIONAL_PASS** | `NO_IOT_METER_SOURCE`, `NO_VERIFIED_ACTUAL_SET_COMPLETION`; `f01`, `f12`, `f13` |
| A8 | Planned TEAM_ELAPSED duration | **MOCK_FUNCTIONAL_PASS** | Backend / API RT4-C (`rt4c_*`, 29 cases) + frontend display (this batch, 18 cases, 6 mutants) |
| A9 | Standard vs actual parts | Actual used parts **MOCK_FUNCTIONAL_PASS**; standard part sets **DEFERRED_APPROVED_PHASE (R6)** + **OPEN_SOURCE_DATA** | API `used_parts`; UI `PmWorkOrderDetailPage.tsx` (entry), `PmTaskCard.tsx` (display). Real `pm_task_part` / `part_sets` empty |
| A10 | Fleet / Vehicle Due and explanations | **MOCK_FUNCTIONAL_PASS** | `GET /pm/due/vehicles[/{id}]`; `FleetPmDuePage.tsx`, `PmDueSetTable.tsx`; `FleetPmDuePage.test.tsx` (30), `rt4b_*` (one Master state per page) |
| A11 | PM opening with frozen snapshot | **MOCK_FUNCTIONAL_PASS** (domain); in-app Master opening **OPEN_OWNER_POLICY** (activation) + **R11_POSTGRES_BLOCKED** (durability) | `open_master_work_order` (frozen membership, RT1 scope / identity, RT4-A revalidation); `rt4a_*`. The Master is dormant in the app (`f24`, `f25`, `test_23`). |
| A12 | Technician V2 assignment | **MOCK_FUNCTIONAL_PASS** | V2-only routes, legacy 410; `test_technician*`, `test_v2_*` |
| A13 | PM results, SUBMIT, manager review, CLOSE | **MOCK_FUNCTIONAL_PASS** | E01 routes (`api/v1/pm.py`); `test_r4_pm_wf_*`; partial close with Outstanding, zero-work refusal |
| A14 | Manager queue and history | **MOCK_FUNCTIONAL_PASS** | `PmManagerQueuePage.tsx`, `PmWorkOrderHistoryPage.tsx` + tests; `test_pm_manager_queue.py` |
| A15 | Authorization and TEST/REAL isolation | **MOCK_FUNCTIONAL_PASS** | `can_view` derived reads, 503 unconfigured scope, RT1 scope binding, RT3-B catalogue `CAN_VIEW`; `f18`, `f19`, `rt1_f26`/`f27`, `rt3b_*`, `rt4b_08`/`10`, `rt4c_08`, XR-07 |
| A16 | Duplicate and concurrent-read safeguards | **MOCK_FUNCTIONAL_PASS** (in-process); multi-process **R11_POSTGRES_BLOCKED** | Request-id replay; RT3-A commit uniqueness; RT4-A open revalidation; RT4-B Master snapshot; XR-04 exact-source dedup |
| A17 | Unified PM alerts; near / overdue rules | **OPEN_OWNER_POLICY (E02)** + **DEFERRED_APPROVED_PHASE (R7)** | No PM alert generation (`alert.py` opaque categories); `pm_due.py` has no windows by design |
| A18 | Calendar / multi-condition PM rules | **OPEN_SOURCE_DATA / OPEN_OWNER_POLICY**; unsupported by design | Source has HOUR 231 + KM 29 only; the preview refuses a calendar substitute |

**No item is FAILED or IMPLEMENTED_UNVERIFIED.**

## 4. Evidence of this batch
**New tests (`FleetPmDuePage.test.tsx`, 18 cases):**
- **Formatting:** 150 / 45 / 180 / 60 / 61 minutes render as specified, with no decimal hours, the correct
  `data-minutes` and the hint.
- **No data:** `null` gives no-data text, never zero; a response **omitting the field** renders no-data without
  crashing; `0`, `-30`, `12.5`, `NaN`, `'150'` and `true` give no-data, no coercion.
- **Per Set:** 150 and 90 keep their own values, with no 240 or `4 ชม.` anywhere.
- **Both screens:** the Fleet and Vehicle screens show the identical contract.
- **Status untouched:** DUE / UNKNOWN / NOT_DUE badges and server explanations are unchanged by the duration.
- **Inactive Master:** `MASTER_NOT_ACTIVE` shows no table and no duration.
- **Layout:** the column sits right after **รอบ** and carries a responsive `data-label`.
- **Existing tests:** the 12 existing tests (loading, UNKNOWN, `MASTER_NOT_ACTIVE`, filters and paging, empty and
  out-of-range, error and retry, 403, responsive labels, vehicle route, `NO_ASSIGNED_PLAN`, R2 URL / filter
  consistency) pass unchanged.
- **Baseline:** against the base frontend source, 17 of the 30 file tests fail (the column is absent).

**Mutation checks** (disposable copies; the delivery source was never mutated):

| Mutant | Killed by (assertion) |
|---|---|
| F1 null rendered as zero | omitted-field and unexpected-value tests (`toHaveTextContent` no-data) |
| F2 durations summed across Sets | independent-Sets test (`['240','240']` ≠ `['150','90']`) |
| F3 planned-duration column removed | column-position test (`-1` ≠ `3`) and every `pm-due-planned` lookup |
| F4 field ignored | formatting, independent-Sets and Fleet / Vehicle tests |
| F5 minutes as decimal hours | formatting tests (`2.5 ชม.`) |
| F6 duration shown when the Master is inactive | inactive-Master test (element not null) |

**6 / 6 killed**, all by assertion or element-not-found failures, none by an import or setup error. A first F3
formulation only renamed the column; it was replaced by a true removal before counting.

## 5. Quality gates
| Gate | Result |
|---|---|
| `npm run build` (`tsc -b && vite build`) | **PASS** (exit 0; only the pre-existing chunk-size warning) |
| `npm run lint` (oxlint) | **PASS**, exit 0; 29 warnings, **identical to the base** (no new finding; none in the changed files) |
| Full Vitest | **88 files, 1097 tests passed, 0 failed** |
| Fleet PM Due + PM Status tests | 30 + 7 passed (inside the full run) |
| Playwright E2E, **original R4 Final run** (Chromium, all projects, `--trace off`, run in a disposable copy of the final tree so that `backend/.venv` and the reports did not touch the delivery checkout) | **692 passed, 5 failed, 112 skipped** (9.1 min). *Recorded as discovered test drift; resolved by Correction R2 (rows below).* The **5 failures are pre-existing and unrelated to this batch.** They are one Repair test, `e2e/technician-v2.spec.ts:277` "corrupted / ambiguous data fails closed", in each of the 5 viewport projects. With a stubbed `assignment_model: 'BROKEN'`, the app shows `รหัสข้อผิดพลาด: ASSIGNMENT_MODEL_UNSUPPORTED`, while the spec expects `ASSIGNMENT_MODEL_INVALID` and the title "รูปแบบการมอบหมายของงานนี้ไม่ถูกต้อง" (lines 299–300). The same test **fails identically (5 / 5) on a pristine export of the baseline `8f1013a`** with no change applied. It does not touch PM Due, and its fix (spec expectation or Repair UI) is outside this batch's allowlist; see §7. No e2e spec covers PM Due. |
| **R2:** corrected test in isolation (`technician-v2.spec.ts -g "corrupted / ambiguous data fails closed"`, all 5 projects) | **5 passed, 0 failed** |
| **R2:** complete Playwright suite (final 5-file tree, disposable copy) | **697 passed, 0 failed, 112 skipped** (11.5 min; the earlier 692 plus the 5 corrected cases). The **112 skips are identical to the original run** and are gated by the specs themselves: `access-management.spec.ts` 30 (needs `ACCESS_MANAGEMENT_E2E=1`), `r2-c2a-panels` 25, `r2-c2b-e2-panels` 25, `r3-inspection-finding` 20, and `web-uat-defect-fix`, `pm-repair`, `inspection` 4 each (project-gated, e.g. writes run once on desktop). **No failure, no new failure.** |
| **R2:** build / lint / full Vitest re-run on the final tree | build PASS; lint identical to the base (no new finding); **1097 passed / 88 files** |
| **R2:** targeted Vitest (Fleet PM Due, PM Status, `RepairDetailPage`, `TechnicianAssignmentV2Panel.r3`, `.withdrawal`, `TechnicianV2Cutover`) | **122 passed / 6 files** |
| **R2:** end-to-end mutation checks (disposable copies, desktop project) | **2 / 2 killed**. E1: the `unsupported` gate removed (a BROKEN job rendered as an ordinary workable Repair), killed at "unsupported title visible" (element not found). E2: the gate kept but a "บันทึกการดำเนินการ" button rendered, killed at "button count 0" (received 1). The original 6 frontend mutants (F1–F6) were re-run on the final tree: **6 / 6 still killed**. |
| Backend sanity (backend unchanged, 0 paths) | `test_pm_fleet_due.py` (all) + firewall / Master-inactive (`b1_13`, `b1_17`, `test_23`, `f24`, `f25`, `rt1_f26`) + RT4-B / RT4-C: **81 passed** (re-run for R2: **81 passed**). The full backend was not re-run (no backend change); last full run RT4-C: 5954 passed / 0 failed / 4 skipped (prior evidence, not re-run). |
| Frontend / backend contract | `PmDueSet` (TypeScript) ≡ `PmDueSetResponse` fields (programmatic, exact) |
| `git diff --check` | clean |
| Allowlist / staging | exactly the 5 approved paths (after R2); 0 staged; no other tracked or untracked change in the delivery tree |
| Secret scan | no matches |

## 6. Files
| Path | Status | Lines |
|---|---|---|
| `frontend/src/lib/types.ts` | M | +2 |
| `frontend/src/components/PmDueSetTable.tsx` | M | +36 |
| `frontend/src/pages/FleetPmDuePage.test.tsx` | M | +108 |
| `frontend/e2e/technician-v2.spec.ts` | M | +19 / −4 (R2) |
| `docs/phase-results/r4-final-consolidated-completion-result.md` | A | this report |

## 7. Unresolved conditions (not implemented, not production-ready)
| Condition | Meaning |
|---|---|
| **OPEN-005** | PM Master publish / assign / approve authority and production activation; REAL stays fail-closed, Production Master dormant |
| **OPEN-012** | Real vehicle component topology, the meter source and historical opening / last-PM anchors; Due stays UNKNOWN |
| **OPEN-016 (data)** | The 183 real mapping candidates are unapproved; the 52 `PENDING_PM_PLAN` vehicles have no Plan |
| **E02** | Owner-defined near-due / overdue policy |
| **R6** | Standard part sets and BOM revisions |
| **R7** | Central PM alert lifecycle |
| **R8** | Fleet Due branch filter (the API supports `branch_id`) and dashboard integration |
| **R9** | Real IoT telemetry |
| **R11** | PostgreSQL durable Master, repository vehicle resolver, atomic opening + open snapshot, atomic SUBMIT + anchor, full Due REPEATABLE READ snapshot, Repair Request exact-source unique key, Access Management log key, real concurrency tests |
| Calendar / multi-condition PM | Unsupported; no approved rule or source data exists |
| Master Work Order planned duration | Not shown on Work Orders (would need the frozen membership to carry it); DEFER |
| ~~Pre-existing e2e drift~~ **RESOLVED by Correction R2** | `e2e/technician-v2.spec.ts:277` now asserts the current V2-only fail-closed contract (`ASSIGNMENT_MODEL_UNSUPPORTED`); the application was unchanged (§2a) |

## 8. Closure verdict
1. **R4 Mock Functional Scope: COMPLETE.**
   - Every currently authorized and testable R4 rule is implemented and proven on the Mock (A1–A16 and A8 in full).
   - Each item is backed by named tests, mutation checks and green build, lint, unit and end-to-end gates. The
     original end-to-end drift (5 failures of one stale Technician V2 test) is corrected by R2; see §5 for the
     re-run.
   - No authorized R4 code gap remains.
2. **Full Roadmap / Production Scope: NOT COMPLETE.**
   - It depends on: Owner authority and activation (OPEN-005), real source data (OPEN-012 topology, meters and anchors;
     OPEN-016 approvals and the 52 pending Plans), an Owner policy (E02), and later phases (R6 parts, R7 alerts, R8
     branch filter, R9 IoT, R11 PostgreSQL, R12 cutover).
   - The exit-gate clause "vehicle page, report **and alerts** agree" cannot be met before R7 / E02.

A Mock Functional PASS is **not** formal R4 closure. The Owner must accept this closure classification (§3, §7) before
R5 begins. R5 then starts on a **new remote branch** from the accepted R4 commit.

## 9. Mandatory Cleanup Review
| Item | Class | Reason |
|---|---|---|
| `PmDueSet` TypeScript type | REPLACE (extended) | Now exactly matches the API |
| `plannedTeamTime` (local, pure) | RETAIN (new) | Display formatting of one value; no duration service, shared util or schema validator |
| `PmDueSetTable` | RETAIN + one column | No restructuring; responsive behavior preserved |
| RT4-A / B / C backend | RETAIN | Unchanged |
| Stale `technician-v2.spec.ts` unknown-model assertions | REPLACE (R2) | Now assert the approved V2-only fail-closed contract; the other sections are retained |
| `RepairDetailPage` `unsupported` state | RETAIN | Approved fail-closed behavior; unchanged |
| `PmStatusPage` Phase-4 seed status | RETAIN | Approved separate path (XPR-05) |
| `VehicleListPage` branch-filter flow | RETAIN; reuse DEFER (R8) | Not copied |
| Master Work Order planned duration | DEFER | Data-contract change to the frozen membership |
| `MockVehicleResolver` | RETAIN now / REPLACE in R11 | Mock-only by design |
| `evaluate_master_set_due` (internal, no route) | DEFER | Route decision with activation |
| Original-upload `MAINTENANCE.xlsx` preview | UNVERIFIED | Bytes unavailable; the native export was verified instead |

No destructive cleanup.

## 10. Git state
- `HEAD` is unchanged at `8f1013ae68d93a8d9c101052772448e5fda5dd16`. Nothing is staged; nothing was committed or pushed.
- Working tree: `M frontend/e2e/technician-v2.spec.ts`, `M frontend/src/components/PmDueSetTable.tsx`,
  `M frontend/src/lib/types.ts`, `M frontend/src/pages/FleetPmDuePage.test.tsx`,
  `?? docs/phase-results/r4-final-consolidated-completion-result.md`.
- `frontend/node_modules` (git-ignored) was installed for the gates.
