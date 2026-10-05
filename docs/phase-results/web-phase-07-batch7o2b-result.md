# Web/API Phase 7 — Batch 7O2b — Registration Write — Batch Result

BATCH: Phase 7 Batch 7O2b (R1 registry/branch slice, registration writes only), implementing the 7O2b row of
`Phase7_Batch7O1_Registry_Branch_Contract_Final_Rev2.md` §11 and acceptance rows W-01 to W-15.
`Phase7_Batch7O1_Rev2_Outcome_Classification_Addendum.txt` takes precedence over Rev2 wherever they conflict on
how responses are classified. Its registration rows (A.1–A.4, B-OC-01..04, W-OC-01..04, W-OC-06, W-OC-07 and
I-OC-01) are implemented. W-OC-05 (`NOT_DETERMINED`) is branch-only and belongs to 7O2c.

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING INDEPENDENT REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL**

Branch: `review/phase7-batch7o2b-registration-write` (local), created from
`279fde619c1d4a49189cd8b79f5b2705067c8555`, which equals `web/phase7-dashboard-search-reporting` at preflight.
Nothing is committed, pushed or merged.

**Revision R1 (independent review fixes).** The first candidate (patch SHA-256 `b2a32d48…6e32eef`) received two
bounded findings. Both are fixed in this revision, and nothing else changed:
1. **The reconciliation reason length is semantic validation.** Before, `reason_th` had a Pydantic `max_length=500`,
   so a 501-character reason was 422 `VALIDATION_ERROR`. The whole 1–500 rule is now checked by the service before
   any read and refused with 422 `REASON_REQUIRED` (Rev2 §4.6 step 1). The rule is: a string, not blank, 1–500
   characters. The framework still checks the type (a number is `VALIDATION_ERROR`). A valid reason is stored
   exactly, not trimmed. The frontend textarea keeps `maxLength=500`. See §3.1.
2. **A late response keeps its original operation.** `PendingStore.applyResponse` now receives the sending intent's
   operation from the dispatch path. A response whose intent is already gone (settled or acknowledged, e.g. in
   another tab) is classified by that operation's allowlist, no longer by a hard-coded `registration`. Such a
   response is still `found:false`: it recreates nothing, removes nothing and reverses no settlement or
   acknowledgement. See §3.4.

**No live Google Sheets workbook was read or written.** Only synthetic mock data and the fake Sheets transport were
used. The workbook still lacks `vehicle_master.registration_province_code`, `province_master` and
`vehicle_registration_history`, so live-Sheets UAT stays blocked until a separately authorized schema and data
preparation step (see §8). This batch creates none of those columns, tabs or province rows.

---

## 1. What users can do now, and what comes later

- **Who can edit:** holders of the new capability `can_edit_vehicle_registration`. These are ADMIN (through
  `ALL_CAPABILITIES`) and the new dev role `MAINTENANCE_MANAGER`.
- **What they can do** on the vehicle detail page, in the "ทะเบียนและสาขาที่รับผิดชอบ" card:
  - change or clear a vehicle's registration text and province;
  - reconcile a registration history that no longer matches the vehicle record.
- **Who cannot:** MAINTENANCE, SUPERVISOR, TECHNICIAN, DRIVER, and unauthenticated callers, who get 403 with zero
  repository calls.
- **If the outcome is uncertain,** the page keeps a durable notice ("ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ").
  The notice is cleared only by the registration history (the request's own record found **and** history
  CONSISTENT) or by the user's explicit "รับทราบ". Nothing is resent automatically.
- **Not in this batch:**
  - branch mutations, branch capabilities and branch dialogs (7O2c);
  - cost measurement and the integration batch (7O2d);
  - live-Sheets UAT;
  - delegation (R11);
  - PostgreSQL.

## 2. File plan

### Added

| File | Purpose |
| --- | --- |
| `backend/app/api/v1/request_id_dependency.py` | The capability route dependency (403) and the client `X-Request-Id` dependency (422 `REQUEST_ID_REQUIRED`). The request id is read from the request header, never the id the middleware generates. |
| `backend/app/domain/request_replay.py` | Canonical-JSON SHA-256 fingerprint (Rev2 §3.2) and the replay lookup over the whole history tab. |
| `backend/app/domain/registry_outcomes.py` | The zero-write allowlist per operation (Addendum A.4), the special outcomes and the never-allowlisted codes. |
| `backend/app/domain/registration_write_service.py` | The PATCH (§4.4) and reconciliation (§4.6) sequences, history-first. |
| `backend/app/api/v1/registration_routes.py` | `PATCH /vehicles/{vehicle_id}/registration` and `POST /vehicles/{vehicle_id}/registration-history/reconciliations`. |
| `backend/tests/test_registration_write_batch7o2b.py` | 341 HTTP tests with the mock repository (16 added in R1). |
| `backend/tests/test_registration_write_sheets_batch7o2b.py` | 27 tests: real gspread over the 7H2 writable fake transport. |
| `frontend/src/lib/registryOutcomeAllowlist.json` | The shared allowlist table read by the client classifier. A backend test asserts it equals the server table. |
| `frontend/src/lib/registryPending.ts` | Intent store, Addendum A.2 classifier, §10.4 settlement, dispatch and explicit resend. |
| `frontend/src/components/VehicleRegistrationEditor.tsx` | The editor, outcome banners, acknowledgement and resend. |
| `frontend/src/components/RegistrationReconcileDialog.tsx` | The APPLY_RECORDED / ACCEPT_MASTER dialog. |
| `frontend/src/lib/registryPending.test.ts`, `frontend/src/lib/apiClient.mutation.test.ts`, `frontend/src/components/VehicleRegistrationEditor.test.tsx`, `frontend/src/pages/VehicleDetailPage.registrationWrite.test.tsx` | 92 unit tests (6 added in R1). |
| `frontend/e2e/vehicle-registration-write.spec.ts` | 7 end-to-end tests on each of the 5 viewport projects. |
| `docs/phase-results/web-phase-07-batch7o2b-result.md` | This document. |

### Modified

| File | Change |
| --- | --- |
| `backend/app/domain/authz.py` | Adds `CAN_EDIT_VEHICLE_REGISTRATION` to `ALL_CAPABILITIES` and the role `MAINTENANCE_MANAGER` = {`can_view`, `can_edit_vehicle_registration`}. No other role changes. |
| `backend/app/repositories/base.py` | Additive: `RegistryTableRead.header` (default `()`), `RegistrationPairRow`, `RegistrationMasterRead` and three abstract methods: R1 read, W1 append, W2 cells. |
| `backend/app/repositories/google_sheets/schemas.py` | Adds the write whitelist `VEHICLE_REGISTRATION_WRITE_SHEET`. `VEHICLE_SHEET` keeps its 7 headers. |
| `backend/app/repositories/google_sheets/repository.py` | Splits `_locate_vehicle_record` into read + `_match_vehicle_record` (same behaviour). Adds the R1 read, W1 and W2. `_registry_table` now returns the header. |
| `backend/app/repositories/mock/repository.py` | The same three methods, plus test-only fault injection (`registry_write_faults`) and a write log. |
| `backend/app/api/v1/registry_schemas.py` | Request models (unknown keys forbidden) and response models. |
| `backend/app/api/v1/router.py` | Registers the new router. |
| `backend/tests/test_registry_read_api_batch7o2a.py` | The "no registry mutation route" inventory now allows exactly the two 7O2b routes (§6). |
| `frontend/src/lib/apiClient.ts` | Additive only: `MutationResponse`, `MUTATION_TIMEOUT_MS`, `apiMutation`. `apiGet`, `apiPatch`, `apiPost`, `apiUpload` and `performRequest` have 0 lines removed or changed. |
| `frontend/src/lib/capabilityNames.ts` | Adds `CAN_EDIT_VEHICLE_REGISTRATION`. |
| `frontend/src/lib/labels.ts` | Thai messages for the new codes, banner texts, intent-state labels and accepted-exception labels. |
| `frontend/src/components/RegistryHistoryPanels.tsx` | The registration panel reports each completed read (data, or null for a failure) and re-reads when a reload token changes. It still renders no write control. |
| `frontend/src/pages/VehicleDetailPage.tsx` | Mounts the editor for capability holders. Silent detail refresh. Settlement on every successful registration-history read. |

### Unchanged

- `client.py`;
- `_vehicle_from_row` and the legacy and dashboard reads;
- the 7O2a GET routes;
- every existing frontend API function;
- `capabilities.tsx`, CORS, configuration, dependencies and governance documents.

## 3. Behavior

### 3.1 Request order (Rev2 §3.3; Addendum A.1)

1. **Route dependencies:**
   - `can_edit_vehicle_registration` → 403 `HTTP_ERROR`;
   - then the client `X-Request-Id` (UUID text) → 422 `REQUEST_ID_REQUIRED`.
2. **The body is parsed and validated inside the handler,** after both dependencies → 422 `VALIDATION_ERROR`.
   FastAPI would parse a *declared* body parameter before any dependency. A probe showed malformed JSON then
   returning 422 before the 403, so the routes read the raw body themselves. Error details are produced without
   `input`, `ctx` or `url`, so raw request bytes or non-JSON values are never echoed. All three refusals make zero
   repository calls (tests A–F, §4).
3. **Semantic validation, then the data context.** In the TEST context a blank `REGISTRY_TEST_BATCH_ID` is refused
   with 503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED` before any read (C7). Mock mode uses the labelled synthetic batch
   id `MOCK-7O2B-SYNTHETIC`. The 7O2a read endpoints are unaffected, and no startup requirement is added.
4. **R1:** one validated `vehicle_master` read. It locates the exact row, checks that both registration columns
   exist, and scans the raw text of every non-phantom row for duplicates.
5. **R2:** the history read. The vehicle's rows are validated against the §7.7 matrix, and duplicate change ids
   anywhere in the tab are refused.
6. **Replay** (§6), before every state check.
7. **PATCH:**
   - `REGISTRATION_PROJECTION_MISMATCH`, then `VEHICLE_REGISTRY_STALE` (C1, pinned by test);
   - the duplicate scan;
   - a no-op returns 200 `changed:false`, with `EXISTING_DUPLICATE_PAIR` when relevant;
   - **R3** (only when a code is given): `PROVINCE_NOT_FOUND`, or `PROVINCE_INACTIVE` when newly assigning an
     inactive code;
   - `REGISTRATION_DUPLICATE`;
   - **W1**, then **W2**.
8. **Reconciliation:**
   - before any read: `RECONCILIATION_MODE_INVALID`, then `REASON_REQUIRED` for a reason that is null, not a
     string, blank or whitespace-only, or longer than 500 characters (R1). Only a wrong JSON type is
     `VALIDATION_ERROR`;
   - `RELATED_REQUEST_NOT_FOUND` (the id must name a request of this vehicle);
   - `VEHICLE_REGISTRY_STALE`, then `REGISTRATION_HISTORY_STALE` (RHR1);
   - CONSISTENT or NO_HISTORY → 200 `changed:false`.
   - **APPLY_RECORDED:** the normal province and duplicate rules, then W1 + W2, `master_write: WRITTEN`.
   - **ACCEPT_MASTER:** the master pair must be valid, else 409 `MASTER_PAIR_INVALID`. Unknown province, inactive
     province and existing duplicates are recorded in `accepted_exceptions`. W1 only, `master_write: NOT_NEEDED`
     (C2). A `province_master` outage is 503, never a guess.

After W1 the only coded outcomes are 503 `VEHICLE_MASTER_WRITE_FAILED {history_recorded:true, change_id,
master_write_outcome, request_id}` and 200. A W1 failure is 503 `REGISTRATION_HISTORY_WRITE_FAILED
{history_write_outcome, master_write:"NOT_ATTEMPTED", request_id}`. Any other exception is 500 `INTERNAL_ERROR`,
which the client treats as UNKNOWN. There is no retry, no compensation, no re-read and no re-append. Earlier
history rows are never edited.

### 3.2 Writes and text (§4.1, §4.5; C3, C8)

- **W1:** one `values:append` of a 16-column row, ordered by the R2 header.
  - Every non-empty cell is text-forced (apostrophe); an empty value is sent as `""`.
  - Ids are `VRH-<uuid4 hex>`.
  - `recorded_at` is UTC with microseconds.
  - `recorded_by` is the actor's user id; the capability dependency also refuses an actor without one.
  - TEST rows carry `is_test_data=TRUE` and the batch id; REAL rows carry `FALSE` and a blank batch id.
- **W2:** one `values:batchUpdate` through `VEHICLE_REGISTRATION_WRITE_SHEET` at the R1 row address, writing
  `registration_no` and `registration_province_code` (text-forced, or an actual empty cell `""` for null) and
  `updated_at`.
- **Exactness:** text is never trimmed or normalised. RK1 is used only for comparison. Byte-exact round trips of
  `0012`, edge spaces, Thai digits, `=1+1`, `+66`, `'quoted`, `1,234`, `1e3`, `TRUE` and others are pinned over the
  fake transport (W-12).
- **No re-read after writing:** the PATCH success response builds `vehicle` from R1 plus the applied pair and the
  W2 `updated_at`. A test pins zero reads after W2 (C8).

### 3.3 Request identity (§3.2; C4)

- **Fingerprint:** SHA-256 of canonical JSON (sorted keys, UTF-8, separators `,` `:`, `ensure_ascii=False`) of
  `{op, vehicle_id, event_id: null, body}`.
- **The body is exactly as accepted** (`model_dump(exclude_unset=True)`):
  - an omitted optional key stays absent; an explicit `null` stays `null`;
  - user text is not altered;
  - both request models forbid unknown keys.
- **Pinned by tests:**
  - same id + identical body (any key order) → replay;
  - same id + changed value (including added trailing whitespace) → `REQUEST_ID_REUSED`;
  - same id + extra key → `VALIDATION_ERROR`;
  - same id on another vehicle or operation → `REQUEST_ID_REUSED`;
  - reconciliation with `related_request_id` omitted vs explicit null → two different requests (the second is
    `REQUEST_ID_REUSED`).
- **Client choice:** the reconciliation dialog **omits** `related_request_id` when the field is blank.

### 3.4 Client (Rev2 §10; Addendum A.2–A.3; C5, C6)

- **`apiMutation(path, method, body, {requestId})`:**
  - returns `{kind:"http", status, headerRequestId, json}` or `{kind:"transport", error}`;
  - never throws and never retries;
  - aborts after 60 s, reported as transport.
- **Store:** `crane.registryPending.v1:<userId>:<vehicleId>` in localStorage, written **before** `fetch`. It holds
  the exact body, state, page instance and route epoch.
  - Limits: 5 intents per user per vehicle; dropped after 14 days at load.
  - When storage fails, intents live in page memory and the banner shows "คำเตือนนี้จะหายเมื่อออกจากหน้า".
- **Classifier:** the Addendum A.2 table exactly; the default is KEEP UNKNOWN.
  - It removes an intent only on a correlated, validated first-attempt outcome: applied, no-op, allowlisted
    refusal, or W1 `rejected`.
  - Once an intent has been uncertain, no response removes it. A refused resend is shown **and** the banner stays.
  - A replay keeps UNKNOWN. `REQUEST_ID_REUSED` → CONFLICT. W2 failure with a record → RECORDED_PROJECTION_PENDING.
  - Branch codes and any unlisted code stay UNKNOWN.
- **Settlement on every successful registration-history read** (a failed read changes nothing):
  - own record not found → UNCONFIRMED;
  - found but not CONSISTENT → RECORDED_PROJECTION_PENDING;
  - found and CONSISTENT → removed, with a notice (later changes are named).
  - Intents in flight on the sending page are not judged.
  - `related_request_id` settles nothing.
  - Banner precedence: CONFLICT > PENDING > UNKNOWN/UNCONFIRMED > SUBMITTING.
- **Late responses:** bookkeeping always applies them; only the same mounted view updates its UI. Each response
  is classified with the operation of the intent that sent it, passed through the dispatch path. If that intent
  was already settled or acknowledged, the result is `found:false`: the message is classified by that operation's
  allowlist (R1), and the intent is not recreated.
- **Editor:**
  - stored text is prefilled exactly and sent untrimmed;
  - an explicit "ล้างทะเบียน" sends null/null;
  - text is required for a save (otherwise the request is blocked in the UI);
  - an inactive province is disabled unless it is the current one;
  - while `/provinces` is unavailable, only the recorded raw code (or none) can be selected (C6);
  - NOT_IN_SCHEMA → "แหล่งข้อมูลยังไม่มีช่องนี้ จึงแก้ไขทะเบียนไม่ได้";
  - with no user id the editor is disabled and no storage key is created (C5);
  - stale, duplicate (conflicting vehicle ids shown, links only for safe ids), province and text refusals are
    shown inline and keep the typed values;
  - stale offers "โหลดใหม่"; mismatch and pending offer the reconcile dialog;
  - "ส่งคำขอเดิมอีกครั้ง" reuses the same id and body, for UNKNOWN/UNCONFIRMED only;
  - "รับทราบ" removes the local entry, and its text states it changes nothing on the server and does not establish
    whether the first attempt wrote.
- **Naming:** the open action is labelled "เปลี่ยนทะเบียน". "แก้ไขทะเบียน" collided by substring with the existing
  "แก้ไข" (machine number) button in a 7O2a end-to-end test. The label was renamed; the test was not changed.

### 3.5 Engineering notes (labelled)

- **E-b-raw:** manual body parsing after the dependencies (§3.1), so the 403-first order holds even for malformed
  JSON.
- **E-b-tabdup:** duplicate `change_id`s anywhere in the tab refuse mutations (`CHANGE_ID_DUPLICATE`), as Rev2 §7.7
  states. One vehicle's corrupt id therefore blocks registration writes for all vehicles until it is repaired.
- **E-b-settle:** a history read finished before `/me` has answered is kept once and judged when the editor mounts
  with the user id. It is never re-used.

## 4. Contract-to-test mapping

| Row | Where |
| --- | --- |
| W-01 | `test_w01_*`: 4 roles + no-auth × 5 bodies × 2 endpoints × with/without id → 403, zero calls |
| W-02 | `test_w02_*` and the order test: missing or malformed id → `REQUEST_ID_REQUIRED`, zero calls; the middleware-generated id is not accepted |
| W-03 | `test_w03_*`: RK1 variants, other province, `0012`≠`12`, partial pair, clear, historical reuse, blank-id row, gate-failing and phantom rows (fake), inactive kept vs new |
| W-04 | `test_w04_*`: no-op on an existing duplicate |
| W-05 / C1 | `test_w05_*`, `test_c1_projection_mismatch_precedes_stale` |
| W-06 / C4 | `test_w06_*`, `test_c4_*` |
| W-07 | `test_w07_*` (mock and fake): W1/W2 × rejected / unknown-applied / unknown-not-applied |
| W-08 / C2 | `test_w08_*`, `test_c2_accept_master_*` |
| W-09 | `test_w09_targeted_cells_after_a_header_reorder` (fake) |
| W-10 | `test_w10_interleaved_*` (fake): both pass, the duplicate is visible afterwards (disclosed race) |
| W-11 | `registryPending.test.ts` (persist before dispatch, reload, scoping, limits, memory fallback, resend, settlement); e2e reload |
| W-12 | `test_w12_*` (fake, 10 values) |
| W-13 | store tests (in-flight protection, two tabs); editor unmount test; page navigation test |
| W-14 | `test_w14_*` |
| W-15 | `test_w15_*`: every §7.7 issue code on both endpoints; malformed recorded pair; ACCEPT of a malformed master; accepted exceptions; since-inactive province |
| B-OC-01 | `test_b_oc_01_*`: every (operation, status, code) in A.4 is triggered, with exact status and code, zero writes and a correlated `request_id`. `test_b_oc_cases_cover_exactly_the_allowlist` |
| B-OC-02 | crash after W1, crash after W2, failure while building the response → 500 `INTERNAL_ERROR`; stored state matches the fault point |
| B-OC-03 | AST check: no `HTTPException` or `require_capability` in the service or routes; exactly one `raise HTTPException` in the dependency module |
| B-OC-04 | success, no-op and replay body shapes and the header echo |
| Static | `test_b_oc_static_every_coded_refusal_is_classified`: every code literal raised by the service or dependency is allowlisted or special |
| Allowlist parity | `test_allowlist_client_and_server_tables_are_identical` (backend reads the client JSON) and the frontend table test |
| W-OC-01..04, 06, 07 | `registryPending.test.ts`, `apiClient.mutation.test.ts`, editor tests |
| I-OC-01 | e2e `I-OC-01: …` (mocked network layer) and the page unit test |
| Raw-body A–F | `test_raw_body_*` (43 tests): malformed / truncated / non-UTF-8 / empty bodies; schema-invalid and extra keys; envelopes never echo request bytes or input values |
| Parity | `test_mock_and_fake_give_identical_results` |
| R1 fix 1 | `test_r1_reason_rule_is_semantic_reason_required_with_zero_calls` (empty, spaces, tab/newline, null, 501, 501 with an edge space × both modes → `REASON_REQUIRED`, zero calls and writes); `test_r1_reason_of_wrong_type_is_still_framework_validation`; `test_r1_reason_of_1_to_500_characters_is_accepted_and_stored_exactly` (1, 500, and 500 with edge spaces, stored untrimmed) |
| R1 fix 2 | `registryPending.test.ts` › "late response keeps its original operation" A–E: a registration late response after another tab settled it is harmless; a reconcile late response is classified by reconcile rules (`409 MASTER_PAIR_INVALID` → refusal reported); the same code is not a refusal for registration; a registration-only code (`REGISTRATION_TEXT_INVALID`) is not a reconcile refusal; acknowledgement during flight is not undone and other intents are intact |

**End-to-end test design.** Every mutation and the history reads that follow it are answered by a mocked network
layer (`page.route`). The 5 viewport projects run in parallel against one shared mock backend, and these tests must
not change the synthetic registry data other specs read. Server-side writes are covered by the backend suites.

## 5. Request counts (fake transport, warm metadata; not live Sheets)

| Path | Values reads | Writes |
| --- | --- | --- |
| no-op | 2 | 0 |
| stale | 2 | 0 |
| change without a province code | 2 | append + batchUpdate |
| change with a province code | 3 | append + batchUpdate |

These match the Rev2 §4.4 estimate.

## 6. Existing expectation update

`test_registry_read_api_batch7o2a.py::test_no_registry_mutation_route_exists` pinned "no registry mutation route".
It now skips exactly `PATCH …/registration` and `POST …/registration-history/reconciliations`, and its OpenAPI
inventory lists those two. Every other method and path is still asserted as 404/405. No other existing test was
changed.

## 7. Verification (2026-10-05)

**Environment:** Python 3.11.15, FastAPI 0.141.1, gspread 6.2.1; Node 22.22.2, Vitest 5.0.0, Playwright 1.63.0
(Chromium, 5 viewport projects).

| Check | Result |
| --- | --- |
| Backend full suite | **2640 passed** (base 2272; +368 new: 352 in R0, 16 in R1) |
| Frontend unit suite | **55 files, 527 passed** (base 435; +92 new: 86 in R0, 6 in R1) |
| Typecheck + build (`tsc -b && vite build`) | exit 0. The existing chunk-size notice is unchanged. |
| Lint (`oxlint`) | exit 0, **33 warnings**. The warning set (file + rule) is identical to the base commit's, checked in a scratch worktree of `279fde6`. |
| Playwright inventory | **520 tests in 20 files** (base 485; +35 = 7 tests × 5 projects) |
| Playwright full suite (R1) | **520 passed**, first run |
| Playwright full suite (R0, for the record) | run 1: 519 passed, 1 failed; run 2: 519 passed, 1 failed; run 3: 520 passed |

**About the two failed R0 Playwright runs:** each failure was a single test in `pm-repair.spec.ts`, and a different
test each time.
- **Run 1:** "uploaded action evidence…" (smartphone-landscape). The repair form submitted as a repair *request*
  (RRQ) instead of a repair (RPR). `RepairCreatePage` chooses that flow while `/me` capabilities are still loading,
  and the test submits immediately.
- **Run 2:** "report a MANUAL repair…" (desktop), a 30 s timeout waiting for the parts free-text field.

Neither the repair pages, the capabilities provider nor that spec is changed by 7O2b. The spec passed **105/105** in
isolation (3 repeats × 5 projects). These are recorded as intermittent, load-related, pre-existing timing issues,
not hidden and not changed here. The R1 full run did not reproduce them.

**Earlier in development:** four failures were a real 7O2b regression. The new "แก้ไขทะเบียน" label made the 7O2a
end-to-end locator `getByRole('button', { name: 'แก้ไข' })` ambiguous. The label was renamed to "เปลี่ยนทะเบียน"; the
existing test was not edited.

## 8. Limitations and live-data status

- **Live-Sheets UAT is blocked** until an authorized step adds:
  - `vehicle_master.registration_province_code`;
  - the `province_master` tab, with owner-supplied rows;
  - the `vehicle_registration_history` tab;
  - and the UAT deployment sets `REGISTRY_DATA_CONTEXT=TEST` with a non-blank `REGISTRY_TEST_BATCH_ID`.

  `registration_no` and `responsible_branch_id` exist live.
- **Disclosed races remain.** Sheets has no unique constraint, so two concurrent requests can register the same
  pair. A recorded but not-yet-applied pair is not reserved. A row move during a request is not detected.
- **The intent store is per browser profile.** A cleared browser, another device or eviction loses it. W1
  unknown-not-applied is then invisible to the server. localStorage is not a security boundary.
- **Cross-origin deployment** would need `Access-Control-Expose-Headers: X-Request-Id`. Otherwise every 200 is
  classified UNKNOWN (safe, but unhelpful). Dev uses the same-origin Vite proxy; CORS is unchanged here.
- **Permissions:** only dev roles exist. The real matrix (M02) and delegation (R11) are later.
- **End-to-end mutations are network-mocked** (§4), as noted there.

## 9. Stop state

- Uncommitted review candidate on `review/phase7-batch7o2b-registration-write`; HEAD is still `279fde6`; the index
  is empty.
- No 7O2c code: no branch mutation route, capability, schema or dialog.
- No live Google Sheets access.
- Nothing committed, pushed, merged or tagged.
