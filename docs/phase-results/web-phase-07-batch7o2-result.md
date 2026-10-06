# Web/API Phase 7 — Batch 7O2 (R1 Registry / Branch slice) — Consolidated Result

This is the consolidated 7O2 result named in the file plan of
`Phase7_Batch7O1_Registry_Branch_Contract_Final_Rev2.md` §12.1. It covers 7O2a, 7O2b, 7O2c and 7O2d.
`Phase7_Batch7O1_Rev2_Outcome_Classification_Addendum.txt` governs response classification. Neither source document
is changed.

Per-batch detail:
- `web-phase-07-batch7o2a-result.md`
- `web-phase-07-batch7o2b-result.md`
- `web-phase-07-batch7o2c-result.md`
- `web-phase-07-batch7o2d-result.md`

R1 STATUS (technical, mock/fake): **ALL NON-LIVE ACCEPTANCE ROWS PASS — LIVE-SHEETS UAT BLOCKED (see §11).**
The final closure decision is the owner's and the independent reviewer's (§15).

WHOLE PHASE 7 STATUS: **PARTIAL**

## 1. Baseline and integration HEAD

| Item | SHA |
| --- | --- |
| 7O2 baseline (integration branch before 7O2a) | `1d8e3beb62cafc36b0427c4434dddeac556c6748` |
| Integration branch `web/phase7-dashboard-search-reporting` at 7O2d start | `5f8069f8b4db736887850c9ff5b35402e35d968d` |
| 7O2d | uncommitted review candidate on `review/phase7-batch7o2d-integration-acceptance`, tests and docs only |
| `main` | `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (unchanged throughout 7O2) |

## 2. Accepted commits

| Sub-batch | Commit | Parent | Message |
| --- | --- | --- | --- |
| 7O2a read foundation | `279fde619c1d4a49189cd8b79f5b2705067c8555` | `1d8e3be…` | feat(phase7): add registry and branch read foundation |
| 7O2b registration writes | `dd6e80925f5e70be64703736baf50d0e57f9bfbe` | `279fde6…` | feat(phase7): add registration write workflow |
| 7O2c branch writes (R1) | `5f8069f8b4db736887850c9ff5b35402e35d968d` | `dd6e809…` | feat(phase7): add branch write workflow |
| 7O2d integration acceptance | — (awaiting review) | `5f8069f…` | — |

Each was independently reviewed, committed on its review branch and fast-forwarded into the integration branch.

## 3. Endpoint inventory (all under `/api/v1`)

| Method and path | Capability | Batch |
| --- | --- | --- |
| `GET /branches` | `can_view` | 7O2a |
| `GET /provinces` | `can_view` | 7O2a |
| `GET /vehicles?branch_id=…` (exact filter; ANDs with status/model/q) | `can_view` | 7O2a |
| `registry` field on the vehicle list items and detail | `can_view` | 7O2a |
| `GET /vehicles/{id}/branch-history` | `can_view` | 7O2a |
| `GET /vehicles/{id}/registration-history` | `can_view` | 7O2a |
| `PATCH /vehicles/{id}/registration` | `can_edit_vehicle_registration` | 7O2b |
| `POST /vehicles/{id}/registration-history/reconciliations` | `can_edit_vehicle_registration` | 7O2b |
| `POST /vehicles/{id}/branch-transfers` | `can_transfer_vehicle_branch` | 7O2c |
| `POST /vehicles/{id}/branch-history/insertions` | `can_correct_branch_history` | 7O2c |
| `POST /vehicles/{id}/branch-history/events/{event_id}/corrections` | `can_correct_branch_history` | 7O2c |
| `POST /vehicles/{id}/branch-history/events/{event_id}/cancellations` | `can_correct_branch_history` | 7O2c |
| `POST /vehicles/{id}/branch-projection/reconciliations` | `can_transfer_vehicle_branch` | 7O2c |

No other registry or branch mutation route exists; inventory tests pin it.

## 4. Capability matrix (dev roles; the real matrix is M02, delegation R11)

| Role | view | edit registration | transfer branch / reconcile projection | correct branch history |
| --- | --- | --- | --- | --- |
| ADMIN | ✓ | ✓ | ✓ | ✓ (all capabilities) |
| MAINTENANCE_MANAGER | ✓ | ✓ | ✓ | ✓ |
| MAINTENANCE | ✓ | — | — | — |
| SUPERVISOR | ✓ | — | — | — |
| TECHNICIAN | ✓ | — | — | — |
| DRIVER | ✓ | — | — | — |
| no auth | — | — | — | — |

A refused mutation is 403 `HTTP_ERROR` with zero repository calls, for valid and invalid bodies alike. Transfer
and correction capabilities are separate (B-07).

## 5. Data-context behaviour (§8.1)

- **Mock:** always `TEST`. `REGISTRY_DATA_CONTEXT=REAL` with the mock repository fails settings validation.
- **Sheets, context unset:** every registry route returns 503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED` before any
  repository call. Existing routes are unaffected.
- **Reads:**
  - `TEST` includes blank, `TRUE` and `FALSE` rows;
  - `REAL` refuses any `TRUE` or blank row of the vehicle (`CUTOVER_INCOMPLETE`), so test rows never become current.
- **Writes:**
  - `TEST` requires a non-blank `REGISTRY_TEST_BATCH_ID` (blank → 503 for mutations, reads unaffected) and writes
    `is_test_data=TRUE` with that batch id;
  - `REAL` writes `FALSE` and a blank batch id.

## 6. Read / write / replay order (every mutation)

1. capability (403);
2. client `X-Request-Id`, UUID (422 `REQUEST_ID_REQUIRED`);
3. raw-body validation (422 `VALIDATION_ERROR`, unknown keys refused, input never echoed);
4. semantic validation (reason 1–500, effective time) with zero reads;
5. data context;
6. R1 vehicle master;
7. R2 history tab + structural validation;
8. replay (same id + same fingerprint → 200 `replayed`; same id + other fingerprint → 409 `REQUEST_ID_REUSED`; the
   fingerprint includes the operation, vehicle and, for edits, the event id);
9. stale / state / no-op checks;
10. R3 reference read, only when a new reference value will be written (province; branch for a new destination);
11. build the row;
12. validate the row (strict validator);
13. W1 history append;
14. W2 targeted master cells when required;
15. respond.

There is no `HTTPException` after the dependencies, no retry, no compensation and no re-read after writing. History
is written first, so the history is the record of truth and the master is its projection.

## 7. Outcome-classification policy (Addendum)

- **Server side:** every coded refusal before W1 is on the operation's zero-write allowlist (A.4). W1 failures are
  503 `…_HISTORY_WRITE_FAILED` with `history_write_outcome` `rejected` or `unknown`. W2 failures are 503
  `…_MASTER_WRITE_FAILED` / `BRANCH_PROJECTION_WRITE_FAILED` with the record id. Anything else is 500
  `INTERNAL_ERROR`. One JSON table is shared by server and client, and a test proves they are identical.
- **Client side:**
  - An intent is persisted before send under `crane.registryPending.v1:<userId>:<vehicleId>`. The default outcome is
    KEEP `UNKNOWN`.
  - It is removed only for a validated, correlated, allowlisted first-attempt outcome. After any uncertainty, only
    history settlement or an explicit "รับทราบ" removes it.
  - A branch `NOT_DETERMINED` is KEEP `RECORDED_PROJECTION_PENDING`, never success.
  - There is no automatic resend; a resend reuses the same id and body.
- **Settlement is family-scoped:**
  - a registration-history read judges only registration intents; a branch-history read judges only branch intents;
  - own record found and `CONSISTENT` → removed with a notice;
  - found but not consistent → `RECORDED_PROJECTION_PENDING`;
  - not found → `UNCONFIRMED`;
  - `related_request_id` settles nothing.

## 8. Measured request costs (I-02; fake transport, warm)

Values reads, then writes as append + batchUpdate. Cold first use adds 1 worksheet-list request plus 1 per newly
touched tab. The full table with classifications is in the 7O2d result §5.

| Operation | Reads | Writes |
| --- | --- | --- |
| `GET /vehicles` (any filter) / usable `q` / hyphen-only `q` | 1 / 2 / 1 | 0 |
| vehicle detail | 4 (one vehicle_master read serves the registry fields) | 0 |
| `GET /provinces`, `GET /branches` | 1 each | 0 |
| registration / branch history GET | 2 each | 0 |
| registration change: with province / without | 3 / 2 | 1 + 1 |
| registration reconciliation | 2–3 | ACCEPT 1 + 0; APPLY 1 + 1 |
| transfer / transfer no-op | 3 / 2 | 1 + 1 / 0 |
| insertion | 3 | 1 + 0 |
| correction: time-only / new destination | **2** / 3 | 1 + 0, or 1 + 1 when the current branch changes |
| cancellation | 2 | 1 + 0, or 1 + 1 when the current branch changes |
| projection reconciliation: mismatch / consistent | 2 / 2 | 1 + 1 / 0 |

Every value matches Final Rev2 §6.8 or lies within its range. The one exception is the time-only correction (2,
not 3), which is the accepted 7O2c R1 clarification.

## 9. Acceptance matrix

| Row | Status | Evidence |
| --- | --- | --- |
| R-01 column combinations, list + detail | PASS | 7O2a sheets `test_r01_*`; API list/detail/dashboard tests |
| R-02 numeric-looking text; legacy callers | PASS | 7O2a `test_r02_*` |
| R-03 reference lists | PASS | 7O2a API + sheets + frontend resolution tests |
| R-04 branch filter | PASS | 7O2a API filter tests; e2e filter |
| R-05 filter while `/branches` fails | PASS | 7O2a frontend + e2e outage |
| R-06 branch envelope / §5.2 issues | PASS | 7O2a domain + API tests |
| R-07 registration envelope | PASS | 7O2a domain + API tests |
| R-08 contexts | PASS | 7O2a context tests; 7O2b/7O2c B-13/W context tests |
| R-09 effective time | PASS | 7O2a `test_effective_*`; 7O2c C-c4 |
| R-10 RK1 | PASS | 7O2a `test_rk1_*` |
| R-11 UI read states (incl. keyed remount) | PASS | 7O2a detail tests; 7O2d I-04 tests |
| R-12 mock/fake parity (reads) | PASS | 7O2a `test_r12_*` |
| W-01 403 zero calls | PASS | 7O2b `test_w01_*` |
| W-02 request id | PASS | 7O2b `test_w02_*` |
| W-03 registration rules | PASS | 7O2b `test_w03_*` |
| W-04 duplicate no-op | PASS | 7O2b `test_w04_*` |
| W-05 stale / mismatch | PASS | 7O2b `test_w05_*` |
| W-06 replay | PASS | 7O2b `test_w06_*` |
| W-07 W1/W2 failure matrix | PASS | 7O2b `test_w07_*` (mock and fake) |
| W-08 reconciliation APPLY / ACCEPT | PASS | 7O2b `test_w08_*` |
| W-09 header reorder | PASS | 7O2b fake test; the move-during-request limit is disclosed |
| W-10 interleaved registrations | PASS | 7O2b fake test; the duplicate is visible afterwards (disclosed) |
| W-11 intent store | PASS | `registryPending.test.ts`; e2e reload |
| W-12 byte-exact text | PASS | 7O2b `test_w12_*` (fake) |
| W-13 deferred responses | PASS | store, editor and page tests |
| W-14 reconciliation settlement | PASS | 7O2b `test_w14_*` |
| W-15 registration row matrix | PASS | 7O2b `test_w15_*` |
| B-01 baseline | PASS | 7O2c `test_b01_*` |
| B-02 transfer | PASS | 7O2c `test_b02_*` |
| B-03 insertion | PASS | 7O2c `test_b03_*`; 7O2d e2e |
| B-04 correction | PASS | 7O2c `test_b04_*`, R1 fix tests; 7O2d e2e |
| B-05 cancellation | PASS | 7O2c `test_b05_*` |
| B-06 revision on older edit | PASS | 7O2c `test_b04_correction_appends_a_revision_*` |
| B-07 capability separation | PASS | 7O2c `test_b07_*` |
| B-08 W1/W2 matrix | PASS | 7O2c `test_b08_*` (mock), fake failure tests |
| B-09 projection reconciliation | PASS | 7O2c `test_b09_*`; 7O2d e2e |
| B-10 reconciliation concurrent with a transfer | PASS | 7O2d `test_b10_reconciliation_concurrent_*` (race reproduced, repaired); 7O2c interleaved transfers |
| B-11 structural issues | PASS | 7O2c `test_b11_*` |
| B-12 branch-only master | PASS | 7O2c `test_b12_*` (mock and fake) |
| B-13 test rows never current | PASS | 7O2c `test_b13_*` |
| B-14 UI dialogs | PASS | `VehicleDetailPage.branchWrite.test.tsx`; e2e |
| B-15 UI settlement after later changes | PASS | `registryPending.branch.test.ts` (RECORDED_LATER_CHANGED) |
| B-16 mock/fake parity (mutations) | PASS | 7O2c `test_b16_*` |
| B-17 expected master in every state | PASS | 7O2c `test_b17_*` |
| B-18 strict row validation | PASS | 7O2c `test_b18_*` |
| B-19 three tied events | PASS | 7O2c `test_b19_*` |
| B-20 entry-time sources | PASS | 7O2c `test_b20_*` |
| B-21 related request id | PASS | 7O2c `test_b21_*` |
| B-OC-01 allowlisted pairs, zero writes | PASS | 7O2b and 7O2c `test_b_oc_01_*` (case tables = allowlists; one documented unreachable pair) |
| B-OC-02 crash after a write → 500 | PASS | 7O2b and 7O2c `test_b_oc_02_*` |
| B-OC-03 no `HTTPException`; every code classified | PASS | static AST tests (both families) |
| B-OC-04 success / no-op / replay shapes | PASS | 7O2b and 7O2c `test_b_oc_04_*` |
| W-OC-01 A.2 rows, first and after uncertainty | PASS | `registryPending.test.ts`, `registryPending.branch.test.ts` |
| W-OC-02 transport/5xx/HTML/timeout → UNKNOWN | PASS | `registryPending.test.ts`, `apiClient.mutation.test.ts` |
| W-OC-03 malformed / uncorrelated envelopes | PASS | store tests (both families) |
| W-OC-04 wrong status / other operation | PASS | store tests (both families) |
| W-OC-05 NOT_DETERMINED | PASS | `registryPending.branch.test.ts`; page test; e2e |
| W-OC-06 resend refused or succeeding | PASS | store and editor tests |
| W-OC-07 `apiMutation` exposure; existing callers unchanged | PASS | `apiClient.mutation.test.ts`; existing API tests untouched |
| I-OC-01 500 after a real write, settled by history | PASS | 7O2d R1 e2e `vehicle-registry-ioc01.spec.ts`: one browser flow against an isolated real backend + `MockRepository` (real write → mocked correlated 500 → UNKNOWN banner → real history read, `CONSISTENT` with its request id → settlement; no resend); see the 7O2d result §9 |
| I-01 e2e on 5 viewports | PASS | 7O2a/b/c specs + 7O2d `vehicle-registry-integration.spec.ts` |
| I-02 measured costs | PASS — MEASURED | 7O2d `test_registry_costs_sheets_batch7o2d.py` (§8) |
| I-03 full regression | PASS | §10 |
| I-04 keyed remount | PASS | 7O2a tests + 7O2d `VehicleDetailPage.keyedRemount.test.tsx` |
| I-05 PostgreSQL rows of §9 | DEFERRED BY CONTRACT — R11/R12 | not implemented or tested in R1 |
| Live-Sheets 7O2 UAT | BLOCKED FOR LIVE UAT ONLY | §11 |

## 10. Full regression (7O2d candidate, 2026-10-06)

| Check | Result |
| --- | --- |
| Backend full suite | 3067 passed |
| Backend ruff | 13 pre-existing findings, unchanged since before 7O2; none in 7O2 files |
| Frontend unit suite | 58 files, 645 passed |
| Typecheck + build | exit 0 |
| Lint | exit 0; 33 warnings, the same set as the pre-7O2 baseline |
| Playwright | 565 tests in 23 files (5 Chromium viewport projects); 565 passed, first run (one standard invocation; it includes the I-OC-01 spec, which starts its own isolated backend per test) |

## 11. Live Google Sheets blockers (read-only status; nothing was changed)

| Item | Live state | Effect |
| --- | --- | --- |
| `branch_master` | BR-BANGNA-KM6, BR-LAEM-CHABANG, BR-RAYONG; no `is_active` column | **usable as is** (every branch active, C-c8) |
| `vehicle_master.registration_no`, `responsible_branch_id` | present | usable |
| `vehicle_master.registration_province_code` | missing | registration reads report NOT_IN_SCHEMA; registration writes refused |
| `province_master` tab | missing (owner-supplied rows needed) | `/provinces` and province checks unavailable |
| `vehicle_registration_history` tab | missing | registration history and writes unavailable |
| `asset_branch_history` tab | legacy/prepared **9-column** schema; Rev2 columns missing | branch history GET and every branch mutation return `BRANCH_HISTORY_SCHEMA_INVALID` |
| UAT deployment settings | `REGISTRY_DATA_CONTEXT=TEST` and a non-blank `REGISTRY_TEST_BATCH_ID` required | without them, registry routes are 503 |

Live 7O2 mutation UAT therefore **cannot be declared complete**. It needs a separately authorized schema and data
preparation step. That step is not part of R1's technical acceptance, and nothing here creates those columns, tabs
or rows.

## 12. Disclosed Sheets race limitations (no conditional write in Sheets)

- **Registration:** two concurrent changes can register the same pair; the duplicate is visible afterwards (W-10).
- **Branch:**
  - two transfers prepared from the same revision can both be recorded (7O2c B-10);
  - a reconciliation concurrent with a transfer can re-apply a stale projection, which shows as
    `PROJECTION_MISMATCH` and is repaired by a further reconciliation (7O2d B-10);
  - a tie is reported as AMBIGUOUS_ORDER, never guessed.
- **Rows:** a row moved during a request is not detected (targeted cells by row number).
- **Lost responses:** an unknown W1 that was not applied is invisible to the server. Only the client intent (per
  browser profile) remembers it.

## 13. PostgreSQL (I-05)

Final Rev2 §9 (branch tables and constraints, one transaction per mutation, registration tables, contexts) is
**DEFERRED BY CONTRACT — PLANNED FOR R11/R12**. Nothing PostgreSQL-related was implemented or tested in R1.

## 14. What R2 may rely on as frozen

- **Endpoint paths, capability names and the dev-role mapping** in §3–§4.
- **The vehicle `registry` field shape** (`state` + `value` per field) and the reference-resolution vocabulary
  (`RESOLVED` / `UNKNOWN_CODE` / `REFERENCE_UNAVAILABLE`).
- **The `asset_branch_history` record model:**
  - `record_kind`s, revisions, cancellation and projection reconciliation;
  - the `asset_type` column, which is `VEHICLE` in R1;
  - strict row validation;
  - the `BHR1-` revision token;
  - timeline derivation and consistency states;
  - baseline retention.
- **The effective-time rules:** NOW / DATE Bangkok / DATETIME with offset, whole seconds, lower bound
  1990-01-01T00:00:00Z, no future.
- **The mutation step order** (§6), request identity and fingerprint, and the replay rules.
- **The outcome allowlist JSON** shared by server and client, and the pending store key and families. A new family
  must be added explicitly, not inferred.
- **The data-context and test-batch rules** (§5).

R2 (equipment branch rollout) is not started.

## 15. R1 closure recommendation

**A. ACCEPTABLE TO CLOSE WITH LIVE-UAT BLOCKER RECORDED.**

- **Why it is acceptable:**
  - every non-live acceptance row passes on the mock repository and the fake Sheets transport;
  - the costs are measured, and the only deviation from §6.8 is the accepted 7O2c R1 clarification;
  - the full backend, frontend, build, lint and 5-viewport e2e regression is green;
  - no integration defect was found, and 7O2d changed no production source;
  - PostgreSQL is deferred by contract.
- **What stays open (recorded, not hidden):** live-Sheets UAT is blocked by the missing live schema (§11) until a
  separately authorized schema step. The owner and the independent reviewer make the final decision.
