# Web/API Phase 7 — Batch 7O2c — Branch Write — Batch Result

BATCH: Phase 7 Batch 7O2c (R1 registry/branch slice, responsible-branch writes), implementing the 7O2c row of
`Phase7_Batch7O1_Registry_Branch_Contract_Final_Rev2.md` §11 and acceptance rows B-01 to B-21.
`Phase7_Batch7O1_Rev2_Outcome_Classification_Addendum.txt` takes precedence over Rev2 wherever they conflict on
how responses are classified. Its branch rows are implemented: A.1–A.4, B-OC-01..04, W-OC-01..07 (including
W-OC-05 `NOT_DETERMINED`) and I-OC-01 for the branch case. The binding review clarifications C-c1 to C-c8 are
implemented as listed in §3.6.

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING INDEPENDENT REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL**

Branch: `review/phase7-batch7o2c-branch-write` (local), created from
`dd6e80925f5e70be64703736baf50d0e57f9bfbe`, which equals `web/phase7-dashboard-search-reporting` at preflight.
Nothing is committed, pushed, merged or tagged. `main` is untouched.

**Revision R1 (independent review fixes).** The first candidate (patch SHA-256 `62c6e924…1e0fa0`, 35 files,
+5360/−130) received two bounded findings. Both are fixed in this revision; nothing else changed:
1. **The correction source is taken at the latest earlier instant only.** `branch_timeline.source_before` used to
   raise `SourceUndetermined` when any same-instant tie existed anywhere among the earlier in-force events. It now
   takes the latest earlier instant (excluding the target). Exactly one event there → its destination / `EVENT`;
   more than one → `SourceUndetermined` (409 `BRANCH_TIMELINE_AMBIGUOUS`, `SOURCE_UNDETERMINED`, zero writes). An
   older tie no longer matters once a later, uniquely ordered event has established the branch. "Source uniquely
   known" and "whole timeline still ambiguous" are separate: such a correction is recorded with
   `projection_write: NOT_DETERMINED`, no W2, master unchanged. See §3.5.
2. **A correction reads `branch_master` (R3) only for a new destination** (Rev2 §6.1). A time-only correction that
   keeps the event's existing branch no longer reads or validates `branch_master`, so an unknown or inactive
   historical code, or a `branch_master` outage, does not block it. A changed destination is validated as before.
   See §3.2 and §5.

**No live Google Sheets workbook was read or written.** Only synthetic mock data and the fake Sheets transport were
used. The live `branch_master` (BR-BANGNA-KM6, BR-LAEM-CHABANG, BR-RAYONG, no `is_active` column) is supported as
it is (C-c8). The live `asset_branch_history` tab has the 9-column prepared format, so it blocks live UAT only
(§8).

---

## 1. What users can do now, and what comes later

- **Transfer** a vehicle to another branch ("ย้ายสาขา"), effective now, on a Bangkok date, or at a Bangkok date and
  time. Needs `can_transfer_vehicle_branch`.
- **Reconcile** the vehicle record's branch to the history ("ปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติ"). Offered only
  when the history says `PROJECTION_MISMATCH`. Needs `can_transfer_vehicle_branch`.
- **Manage history** in a separate, initially closed area "จัดการประวัติสาขา": "เพิ่มประวัติย้อนหลัง",
  "แก้ไขประวัติ", "ยกเลิกรายการ". Needs `can_correct_branch_history`.
- **Who:** ADMIN (all capabilities) and the dev role MAINTENANCE_MANAGER = {`can_view`,
  `can_edit_vehicle_registration`, `can_transfer_vehicle_branch`, `can_correct_branch_history`}. MAINTENANCE,
  SUPERVISOR, TECHNICIAN, DRIVER and unauthenticated callers get 403 with zero repository calls.
- The branch-history panel stays read-only.
- **Uncertain outcomes** keep a durable notice, shared with registration intents under the same key
  `crane.registryPending.v1:<userId>:<vehicleId>`, judged only by a branch-history read (family-scoped).
- **Not in this batch:** cost measurement and the integration batch (7O2d); live-Sheets UAT; delegation (R11);
  PostgreSQL; R2.

## 2. File plan

### Added

| File | Purpose |
| --- | --- |
| `backend/app/domain/branch_write_service.py` | The five sequences (§6.2–§6.6): R1 → R2 + structural validation → replay → stale/state/no-op → R3 → build and validate the row → W1 → W2. |
| `backend/app/api/v1/branch_routes.py` | The five POST routes, their capability dependencies and the client request-id dependency. |
| `backend/app/domain/registry_write_support.py` | Helpers shared with the registration service, moved out of it with no behaviour change: the error builder, the write-context check and the read wrappers. |
| `backend/app/api/v1/registry_mutation_body.py` | Raw-body parsing (unknown keys and input echo refused), inlined OpenAPI bodies and the effective test batch id, shared by both route modules. |
| `backend/tests/test_branch_write_batch7o2c.py` | 373 HTTP tests with the mock repository (67 test functions, parametrized; 7 tests added in R1). |
| `backend/tests/test_branch_write_sheets_batch7o2c.py` | 23 tests: real gspread over the 7H2 writable fake transport (R1 adds two correction paths to the request-count test). |
| `frontend/src/components/BranchWriteControls.tsx` | The actions area, banners, notices, acknowledgement and resend. Outside the panel. |
| `frontend/src/components/BranchChangeDialog.tsx` | One dialog for the five operations; it builds each body from the last successful branch-history read. |
| `frontend/src/lib/branchEffectiveTime.ts` | Bangkok wall-clock helpers (stored instant → input text; input → ISO with `+07:00`). |
| `frontend/src/lib/registryPending.branch.test.ts` | 103 unit tests: branch allowlists, classifier rows for all five operations, NOT_DETERMINED, family settlement, dispatch. |
| `frontend/src/pages/VehicleDetailPage.branchWrite.test.tsx` | 12 page tests: C-c3, capability gating, bodies, NOT_DETERMINED, W2, reconciliation, family settlement. |
| `frontend/e2e/vehicle-branch-write.spec.ts` | 4 end-to-end tests on each of the 5 viewport projects (mutations route-mocked). |
| `docs/phase-results/web-phase-07-batch7o2c-result.md` | This document. |

### Modified

| File | Change |
| --- | --- |
| `backend/app/domain/authz.py` | Adds `CAN_TRANSFER_VEHICLE_BRANCH` and `CAN_CORRECT_BRANCH_HISTORY` to `ALL_CAPABILITIES`, and both to MAINTENANCE_MANAGER. No other role changes. |
| `backend/app/domain/branch_timeline.py` | Additive: `SourceUndetermined`, `tied_event_ids`, `source_before`, `in_force_instants`. Existing functions unchanged. |
| `backend/app/domain/request_replay.py` | Five operation names for the fingerprint. |
| `backend/app/domain/registry_outcomes.py` | The five branch allowlists (A.4, plus C-c1/C-c2) and the two branch write-failure codes as special outcomes. |
| `backend/app/domain/registration_write_service.py` | Delegates to `registry_write_support`; unused imports removed. No behaviour change: all 7O2b tests pass. |
| `backend/app/api/v1/registration_routes.py` | Uses the shared body helpers. No behaviour change. |
| `backend/app/api/v1/registry_schemas.py` | Request models (unknown keys forbidden) and response models for branch writes. |
| `backend/app/api/v1/router.py` | Registers the branch router. |
| `backend/app/repositories/base.py` | Additive: `read_vehicle_branch_master` (neutral R1, C-c7), `append_asset_branch_history` (W1), `write_vehicle_branch_cell` (W2). |
| `backend/app/repositories/google_sheets/schemas.py` | Adds the W2 whitelist `VEHICLE_BRANCH_WRITE_SHEET` (`responsible_branch_id`, `updated_at`). |
| `backend/app/repositories/google_sheets/repository.py` | The three methods. The registration R1 and branch R1 share one private reader; only the schema check differs. |
| `backend/app/repositories/mock/repository.py` | The same three methods with the existing W1/W2 fault injection and write log. The branch-history read now also returns its header. |
| `backend/tests/test_registration_write_batch7o2b.py` | Role/capability and route inventories updated for 7O2c (§6). |
| `backend/tests/test_registry_read_api_batch7o2a.py` | The "no registry mutation route" inventory now allows the five branch routes (§6). |
| `frontend/src/lib/registryPending.ts` | Branch operations, `operationFamily`, per-family W1/W2 codes, branch success shape, NOT_DETERMINED → KEEP RECORDED_PROJECTION_PENDING, `settleBranch`, family-scoped notices, `event_id` on intents and in paths. |
| `frontend/src/lib/registryPending.test.ts` | The allowlist equality now covers all seven operations; `isAllowlisted('transfer', 403, 'HTTP_ERROR')` is now true (§6). |
| `frontend/src/lib/registryOutcomeAllowlist.json` | Regenerated from the server table: all seven operations. |
| `frontend/src/components/VehicleRegistrationEditor.tsx` | Lists only registration-family intents (one line). |
| `frontend/src/components/RegistryHistoryPanels.tsx` | The branch panel reports each completed read and re-reads on a reload token (a shared hook, same behaviour as the registration panel). It renders no write control. |
| `frontend/src/lib/labels.ts`, `frontend/src/lib/capabilityNames.ts` | Thai texts for the branch codes, banners and operations; two capability constants. |
| `frontend/src/pages/VehicleDetailPage.tsx` | Mounts the branch controls in the registry card; branch settlement on every successful branch-history read. |

### Unchanged

- `client.py`, the 7O2a GET routes and their response shapes;
- `RegistrationWriteService` behaviour: it still refuses a vehicle master without the registration columns;
- `capabilities.tsx`, `apiClient.ts`, CORS, configuration, dependencies and governance documents;
- every existing test except the three expectation updates in §6.

## 3. Behavior

### 3.1 Endpoints and request order

| Method and path | Capability | Fingerprint op |
| --- | --- | --- |
| `POST /vehicles/{id}/branch-transfers` | `can_transfer_vehicle_branch` | `transfer` |
| `POST /vehicles/{id}/branch-history/insertions` | `can_correct_branch_history` | `insertion` |
| `POST /vehicles/{id}/branch-history/events/{event_id}/corrections` | `can_correct_branch_history` | `correction` (event id included) |
| `POST /vehicles/{id}/branch-history/events/{event_id}/cancellations` | `can_correct_branch_history` | `cancellation` (event id included) |
| `POST /vehicles/{id}/branch-projection/reconciliations` | `can_transfer_vehicle_branch` | `reconcile` |

Order: capability (403) → client `X-Request-Id` (422 `REQUEST_ID_REQUIRED`) → raw-body validation (422
`VALIDATION_ERROR`, no input echoed) → semantic validation (reason, effective time) → data context → R1 vehicle
master → R2 `asset_branch_history` + structural validation → replay → stale, state and no-op checks → R3
`branch_master` (only for a destination that will be written) → build the row → validate the row → W1 append →
W2 cell write when required → respond.

There is no `HTTPException` after the dependencies (pinned by a static test), no retry, no compensation and no
re-read after writing. The post-write timeline is derived in memory.

### 3.2 State rules (Addendum reference model)

- **Transfer:** revision → ambiguous → mismatch → expected current → same instant → not latest → no-op → R3. The
  first record captures the baseline from the master (`IMPORTED_MASTER`, or `NONE` when blank).
- **Insertion:** must be earlier than the latest in-force event; `NOW` is refused. It never writes W2
  (`NOT_NEEDED`) and never rewrites a later event.
- **Correction:** appends a revision that supersedes the head. A no-op compares destination, stored instant and
  precision with the head. R3 runs only when the destination differs from the head's branch (R1 fix 2).
- **Cancellation:** appends a `CANCELLATION`. Cancelling every event projects the baseline, never a guessed value.
- **Reconciliation:** writes the derived current branch, even an unknown historical code, with
  `reconciled_old_master_branch_id` = the master; W2 always. `related_request_id` must name a request of this vehicle
  (422 `RELATED_REQUEST_NOT_FOUND` otherwise) and settles nothing.
- **Expected master** is checked by correction, cancellation and reconciliation in every state, including
  ambiguous and no-op (B-17).
- **W2 decision** comes from the timeline after the new row:
  - VALID with current ≠ master → `WRITTEN`;
  - VALID with current = master → `NOT_NEEDED`;
  - AMBIGUOUS_ORDER → `NOT_DETERMINED`: no W2, master unchanged.
- **Write failures:**
  - W1 → 503 `BRANCH_HISTORY_WRITE_FAILED` with `{history_write_outcome, projection_write:"NOT_ATTEMPTED",
    request_id}`;
  - W2 → 503 `BRANCH_PROJECTION_WRITE_FAILED` with `{event_recorded:true, record_id, projection_write_outcome,
    request_id}`.

### 3.3 Rows

- Every generated row passes the strict 7O2a validator before W1 (B-18). A failure would be an internal error with
  zero writes, never a bad row.
- Record ids are `ABH-` + 32 hex characters. An assignment's `event_id` is its own id.
- Text is text-forced in Sheets (a leading apostrophe on every non-empty cell). A cleared master is an empty cell.
- `is_test_data` / `test_batch_id` follow the data context (§8.1). A tab-wide duplicate record id refuses
  mutations but not reads.

### 3.4 Client

- **Success** = correlated 200 with `changed:true`, a non-empty `record_id`, and `projection_write` `WRITTEN` or
  `NOT_NEEDED` → removed with a notice.
- **`NOT_DETERMINED`** → KEEP `RECORDED_PROJECTION_PENDING`, shown as "recorded, current branch not yet determined
  and the vehicle record not changed". It is never described as success.
- **W2 failure with a record id** → KEEP `RECORDED_PROJECTION_PENDING`. **W1 rejected** → proven zero write.
  Anything else uncertain → KEEP `UNKNOWN`.
- **Settlement is family-scoped.** A registration-history read judges only registration intents; a branch-history
  read judges only branch intents. Branch rules:
  - own record (by `request_id`) not found → `UNCONFIRMED`;
  - found with `PROJECTION_MISMATCH` or `UNDETERMINED` → `RECORDED_PROJECTION_PENDING`;
  - found with `CONSISTENT` → removed with a notice.

  `related_request_id` settles nothing.
- **Resend** is explicit only: same id, same stored body, same event path.
- The DATETIME input is sent as Bangkok `…+07:00`.
- The reason is checked for blankness on the client and the textarea is capped at 500 characters. The server is
  authoritative.

### 3.5 Engineering notes (labelled)

- The registration and branch R1 reads share one private reader. Only the schema requirement differs:
  - registration needs its columns;
  - branch needs only `responsible_branch_id`.
- C-c2 (R1 fix 1): `source_before` looks only at the **latest earlier instant** among the in-force events other
  than the target. One event there → its destination / `EVENT`; several → `SourceUndetermined` (no tie-break by
  recorded order, no master fallback, never a false `NONE`); no earlier event → the baseline / `BASELINE`, else
  `NONE`. A tie at an older instant does not block the correction, although the timeline may still be ambiguous
  (then `NOT_DETERMINED`, no W2).

### 3.6 Review clarifications

| Item | Implementation | Pinned by |
| --- | --- | --- |
| C-c1 | In AMBIGUOUS_ORDER, a correction or cancellation must target a tied event; otherwise 409 `BRANCH_TIMELINE_AMBIGUOUS` (`TARGET_NOT_TIED`) before any write. Added to both allowlists. | `test_c_c1_ambiguous_timeline_refuses_edits_of_a_non_tied_event`, B-OC-01 cases, allowlist tests |
| C-c2 | The correction source is derived immediately before the new instant, excluding the target: a tie at the LATEST earlier instant → 409 `BRANCH_TIMELINE_AMBIGUOUS` (`SOURCE_UNDETERMINED`) before R3/W1; an older tie does not block. A unique source proceeds (`NOT_DETERMINED` if the timeline stays ambiguous). A cancellation of a tied event proceeds; if a tie remains → `NOT_DETERMINED`, no W2. | `test_c_c2_*`, `test_c_c1_c_c2_*`, `test_b19_*`, `test_r1_c_c2_*` |
| C-c3 | The panel stays read-only. "จัดการประวัติสาขา" is separate, outside the panel and closed at first. The three actions render only after opening. Existing tests are unchanged. | `VehicleDetailPage.branchWrite.test.tsx` (C-c3), e2e C-c3 test |
| C-c4 | Lower bound `1990-01-01T00:00:00Z`: exactly that instant is accepted; earlier is `EFFECTIVE_TIME_OUT_OF_RANGE`. DATE 1990-01-01 (= 1989-12-31T17:00Z) is refused. `.000` is accepted; a non-zero fraction is `EFFECTIVE_TIME_PRECISION`. | `test_c_c4_*` |
| C-c5 | `reason_th` for insertion, correction, cancellation and reconcile: a wrong JSON type → `VALIDATION_ERROR`; missing, null, blank, whitespace or >500 characters → `REASON_REQUIRED` with zero repository calls; 1–500 characters stored exactly. | `test_c_c5_*` |
| C-c6 | Transfer `note_th`: string, null or omitted. Type check only, no length rule, stored exactly. | `test_c_c6_*`, fake-transport byte-exact test |
| C-c7 | Neutral `read_vehicle_branch_master`. A branch-only master supports every branch operation (mock and fake transport); registration still refuses it with `VEHICLE_MASTER_SCHEMA_INVALID`. | `test_b12_c_c7_*`, `test_b12_branch_only_master_*` |
| C-c8 | A `branch_master` without `is_active` treats every branch as usable. Live data untouched. | `test_c_c8_*` (mock and fake) |

## 4. Contract-to-test mapping

| Row | Where |
| --- | --- |
| B-01 baseline capture | `test_b01_*` |
| B-02 transfer | `test_b02_*` |
| B-03 insertion | `test_b03_*` |
| B-04 correction | `test_b04_*` |
| B-05 cancellation | `test_b05_*` |
| B-06 revision changes on an older edit | `test_b04_correction_appends_a_revision_*` |
| B-07 separate capabilities, 403 zero calls | `test_b07_*`, `test_refused_with_403_*` |
| B-08 write-failure matrix | `test_b08_*` (mock), `test_write_failures_are_classified_*` (fake) |
| B-09 reconciliation | `test_b09_*` |
| B-10 interleaved transfers | `test_b10_*` (fake) |
| B-11 structural issues block mutations | `test_b11_*` |
| B-12 branch-only master | `test_b12_*` (mock and fake) |
| B-13 data contexts | `test_b13_*` |
| B-14 / B-15 client | `registryPending.branch.test.ts`, `VehicleDetailPage.branchWrite.test.tsx` |
| B-16 mock/fake parity | `test_b16_*` |
| B-17 expected master every state; replay precedence | `test_b17_*` |
| B-18 strict row validation | `test_b18_*` |
| B-19 three tied events | `test_b19_*` |
| B-20 entry-time sources | `test_b20_*` |
| B-21 related request id | `test_b21_*` |
| B-OC-01 every allowlisted pair, zero writes | `test_b_oc_01_*` (case table = allowlist; one unreachable pair documented; since R1 the correction's `branch_master` cases change the destination, as R3 needs) |
| R1 fix 1 (latest earlier instant) | `test_r1_c_c2_source_is_the_latest_earlier_instant_even_with_an_older_tie`, `test_r1_c_c2_source_before_rules` |
| R1 fix 2 (R3 only for a new destination) | `test_r1_time_only_correction_skips_r3` (A unknown code, B inactive code, E outage), `test_r1_destination_changing_correction_runs_r3` (C, D), fake `test_request_counts_per_path` (F) |
| B-OC-02 crash after a write → 500 | `test_b_oc_02_*` |
| B-OC-03 every raised code classified; no `HTTPException` | `test_b_oc_static_*` |
| B-OC-04 shapes and header echo | `test_b_oc_04_*` |
| W-OC-01..07, NOT_DETERMINED | `registryPending.branch.test.ts` |
| I-OC-01 (branch) | e2e "a 500 after a real write is uncertain…" |

The one unreachable allowlisted pair is transfer `(422, EFFECTIVE_MODE_NOT_ALLOWED)`: `NOW` is a valid transfer
mode. It stays in the A.4 table as written and is listed in the test.

End-to-end mutations are network-mocked: the five viewport projects share one mock backend, so these tests must not
change data other specs read. Server-side writes are covered by the backend suites.

## 5. Request counts (fake transport, warm metadata; not live Sheets)

| Path | Values reads | Writes |
| --- | --- | --- |
| transfer no-op | 2 | 0 |
| transfer (R3) | 3 | append + batchUpdate |
| correction, time only (same destination, no R3) | 2 | append |
| correction, new destination (R3) | 3 | append |
| cancellation, projection NOT_NEEDED | 2 | append |
| reconciliation no-op (CONSISTENT) | 2 | 0 |

## 6. Existing expectation updates

- **`test_registry_read_api_batch7o2a.py::test_no_registry_mutation_route_exists`** now allows the five branch
  routes and lists them in its OpenAPI inventory. Every other method and path is still asserted as 404/405.
- **`test_registration_write_batch7o2b.py`:**
  - `test_capability_and_dev_role_mapping` expects the four-capability MAINTENANCE_MANAGER and the two branch
    capabilities;
  - `test_only_the_two_registration_mutations_exist` adds the five branch paths.
- **`registryPending.test.ts`:** the allowlist equality loop covers all seven operations, and
  `isAllowlisted('transfer', 403, 'HTTP_ERROR')` is now `true`. It had been pinned `false` with the comment "branch
  operations arrive with 7O2c".

No other existing test was changed.

## 7. Verification (2026-10-05/06)

**Environment:** Python 3.11.15, FastAPI 0.141.1, gspread 6.2.1; Node 22, Vitest 5.0.0, Playwright 1.63.0
(Chromium, 5 viewport projects).

| Check | Result |
| --- | --- |
| Directly affected backend tests (R1) | 7O2c mock 373 + fake 23 + 7O2a domain 80 = **476 passed**. The 5 regression tests for the two fixes fail on the R0 code and pass on R1. |
| Backend full suite (R1) | **3036 passed** (base 2640; +396 new; R0 was 3029) |
| Backend ruff | 13 findings, identical before and after; all in files this batch does not touch |
| Frontend unit suite (R1) | **57 files, 642 passed** (base 55 files, 527; +115 new). R1 changes no frontend file. |
| Typecheck + build (`tsc -b && vite build`) | exit 0. The existing chunk-size notice is unchanged. |
| Lint (`oxlint`) | exit 0, **33 warnings**. The warning set (file + rule) is identical to `dd6e809`'s, checked in a scratch worktree. |
| Playwright inventory | **540 tests in 21 files** (base 520 in 20; +20 = 4 tests × 5 projects) |
| Playwright full suite (R1) | **540 passed**, first run (R0: 540 passed) |
| New e2e spec, flakiness check | `--repeat-each 3`: 60 passed |

## 8. Limitations and live-data status

- **Live-Sheets UAT is blocked.** The live `asset_branch_history` tab has the 9-column prepared format, and the
  proposed columns are missing, so R2 returns `BRANCH_HISTORY_SCHEMA_INVALID`. An authorized schema step must add
  the columns, and the UAT deployment must set `REGISTRY_DATA_CONTEXT=TEST` with a non-blank
  `REGISTRY_TEST_BATCH_ID`. The live `branch_master` is usable as is (C-c8).
- **Disclosed races remain.** Two transfers prepared from the same revision can both be recorded (B-10; Sheets has
  no conditional append). The next read shows the result, and a tie is reported as AMBIGUOUS_ORDER, never guessed.
- **The intent store is per browser profile**, as in 7O2b. localStorage is not a security boundary.
- **Permissions:** only dev roles exist. The real matrix (M02) and delegation (R11) are later.

## 9. Stop state

- Uncommitted review candidate on `review/phase7-batch7o2c-branch-write`. HEAD is still `dd6e809`; the index is
  empty.
- No 7O2d work. No R2 work.
- No live Google Sheets access.
- Nothing committed, pushed, merged or tagged.
