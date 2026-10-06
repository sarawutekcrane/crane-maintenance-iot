# Web/API Phase 7 — Batch 7O2d — Integration Acceptance — Batch Result

BATCH: Phase 7 Batch 7O2d, the final 7O2 sub-batch of R1 (integration and acceptance), implementing the 7O2d row of
`Phase7_Batch7O1_Registry_Branch_Contract_Final_Rev2.md` §11 and acceptance rows I-01 to I-05 (§13.1).
`Phase7_Batch7O1_Rev2_Outcome_Classification_Addendum.txt` governs response classification. The consolidated 7O2
result, with the full acceptance matrix, is `docs/phase-results/web-phase-07-batch7o2-result.md`.

BATCH STATUS: **IMPLEMENTED — UNCOMMITTED REVIEW CANDIDATE, AWAITING INDEPENDENT REVIEW**

WHOLE PHASE 7 STATUS: **PARTIAL**

Branch: `review/phase7-batch7o2d-integration-acceptance` (local), created from
`5f8069f8b4db736887850c9ff5b35402e35d968d`, which equals `web/phase7-dashboard-search-reporting` and its origin at
preflight. Nothing is committed, pushed, merged or tagged. `main` is untouched (`af75b548…`).

**No production source changed.** This batch adds tests and documentation only. No integration defect was found.

**Revision R1 (independent review fix).** The first candidate (patch SHA-256 `bcfdae5f…5135d`, 5 files, +1338)
classified I-OC-01 as PASS on composed evidence. Review required the Addendum row literally, as one browser flow.
R1 adds `frontend/e2e/vehicle-registry-ioc01.spec.ts`: a real mock-repository write, a correlated 500 shown to the
browser only after it, the uncertainty banner, and settlement by the next real history read from the same isolated
repository (§9). Nothing else changed apart from these two documents.

**No live Google Sheets workbook was read or written.** Measurements use the fake Sheets transport. PostgreSQL is
not implemented. No R2 work.

---

## 1. Inventory of existing evidence (before adding anything)

| Operation | Existing direct coverage (7O2a/b/c) | 7O2d action |
| --- | --- | --- |
| Registry fields on the list and detail view | e2e `vehicle-registry-read`: list registry text and labels; detail card and read-only panels; no-history; failed read | none (EXISTING) |
| Vehicle-list branch filter | e2e `vehicle-registry-read`: exact filter and clear; branch-list outage | none (EXISTING) |
| Registration edit | e2e `vehicle-registration-write`: change, no-op, duplicate, stale, W2 pending, 500 uncertainty, reload + resend | none (EXISTING) |
| Registration reconciliation | e2e `vehicle-registration-write` "a master-write failure stays pending until an APPLY reconciliation…" | none (EXISTING) |
| Branch transfer | e2e `vehicle-branch-write`: transfer confirmed; 500 uncertainty settled by history | none (EXISTING) |
| Historical insertion | backend and unit tests only | **NEEDS INTEGRATION COVERAGE** → added |
| Correction | backend and unit tests only | **NEEDS INTEGRATION COVERAGE** → added |
| Cancellation | e2e `vehicle-branch-write` "NOT_DETERMINED is shown as recorded…" | none (EXISTING) |
| Branch projection reconciliation | backend and unit tests only | **NEEDS INTEGRATION COVERAGE** → added |
| Pending intent / uncertain result | e2e (both write specs), unit store tests | cross-family flow **added** |
| 5 viewport projects | every spec runs on all 5 configured Chromium projects | — |
| §10.6 keyed remount | e2e and unit: machine-number editor reset; delayed detail, history and machine-number results | status dialog, registry/branch editors and late status result **added** (I-04) |
| §6.8 costs | 7O2a: GET counts; 7O2b/7O2c: a few mutation paths | full table **added** (I-02) |

No test was duplicated to raise counts, and no existing assertion was weakened.

## 2. Added files (tests and documentation only)

| File | Content |
| --- | --- |
| `backend/tests/test_registry_costs_sheets_batch7o2d.py` | 31 tests: I-02 cost measurements (warm per §6.8 row, cold metadata) and B-10 in its contract wording, over real gspread on the 7H2 writable fake transport. |
| `frontend/src/pages/VehicleDetailPage.keyedRemount.test.tsx` | 3 tests: I-04 keyed remount. |
| `frontend/e2e/vehicle-registry-integration.spec.ts` | 4 tests × 5 projects: I-01 insertion, correction, projection reconciliation, and the cross-family flow. |
| `frontend/e2e/vehicle-registry-ioc01.spec.ts` (R1) | 1 test × 5 projects: I-OC-01, literally, against an isolated backend (§9). |
| `docs/phase-results/web-phase-07-batch7o2d-result.md` | This document. |
| `docs/phase-results/web-phase-07-batch7o2-result.md` | The consolidated 7O2 result (Rev2 §12.1 file plan). |

No existing file is modified.

## 3. I-01 — integrated e2e across the 5 viewport projects

| Operation | Evidence (all on the 5 projects) |
| --- | --- |
| A. registry/detail view | `vehicle-registry-read`: list text and labels; detail card and panels |
| B. branch filter | `vehicle-registry-read`: exact filter and clear; outage |
| C. registration edit | `vehicle-registration-write`: 7 tests |
| — registration reconciliation | `vehicle-registration-write`: APPLY reconciliation after a W2 failure |
| D. branch transfer | `vehicle-branch-write`: confirmed transfer; I-OC-01 branch |
| E. historical insertion | **new** `vehicle-registry-integration` "I-01 insertion" |
| F. correction | **new** "I-01 correction" (event id in the path, prefilled event, expected master) |
| G. cancellation | `vehicle-branch-write` "NOT_DETERMINED…" (cancellation, kept pending, survives reload) |
| H. projection reconciliation | **new** "I-01 projection reconciliation" (offered only on a mismatch, gone when consistent) |
| Cross-feature | **new** "I-01 cross-feature" — below |

**Cross-feature flow (new):**
1. A registration intent and a branch intent on VEH-1046 are both uncertain (500 after send).
2. Each banner lists only its own family's request.
3. After the branch-history re-check finds the branch record:
   - only the branch intent settles (notice shown);
   - the registration banner and its request id are unchanged, with no registration notice;
   - the URL and heading stay on VEH-1046 (TC-12);
   - the card still shows "แหลมฉบัง" and "ระยอง", and the panel still resolves branch names;
   - there is no horizontal scroll.

As in 7O2b/7O2c, mutations are answered by a mocked network layer: the 5 parallel projects share one mock backend
whose only registry vehicles (VEH-1046/1047/1048) are asserted by the other specs.

**Result: PASS.** The new spec ran 20/20, then 60/60 with `--repeat-each 3`; the full suite ran 560/560.

## 4. I-04 — keyed remount (Final Rev2 §10.6)

The production mechanism is unchanged: `VehicleDetailPage` reads `vehicleId` and renders
`<VehicleDetailView key={vehicleId} />` (`frontend/src/pages/VehicleDetailPage.tsx:51`).

| Expectation (A → B in-app) | Test |
| --- | --- |
| A's open machine-number editor is gone | 7O2a unit "navigating to another vehicle resets an open machine-number editor (Rev2 §10.6)"; e2e "moving to another vehicle resets an open machine-number editor" |
| A's open status dialog (with typed note) is gone | **new** "an open status dialog from vehicle A is gone on vehicle B" |
| A's registration editor (typed text), opened management area and branch dialog are not carried into B | **new** "open registration and branch editors from vehicle A are not carried into vehicle B" |
| A late status-change result from A changes nothing on B and triggers no read for A | **new** "a late status-change result from vehicle A does not change vehicle B or reload A" |
| Late detail / history / machine-number results from A | 7O2a unit tests (delayed detail, delayed histories, late machine-number result) |
| Late registration success from A after navigation | 7O2b page test W-13 |

**Result: PASS.** The production code was not changed.

## 5. I-02 — measured request costs vs Final Rev2 §6.8

Fake transport, real gspread 6.2.1. "Warm" = worksheet list and tabs already fetched in this process. Each row is
pinned by `test_registry_costs_sheets_batch7o2d.py`.

| Operation | §6.8 estimate | Measured values reads | Measured writes (append / batchUpdate) | Classification |
| --- | --- | --- | --- | --- |
| `GET /vehicles` (none / status / model / branch filter) | 1 | **1** | 0 | matches |
| `GET /vehicles` with usable `q` | 2 | **2** (vehicle + model) | 0 | matches |
| `GET /vehicles` with hyphen-only `q` | 1 | **1** | 0 | matches |
| `GET /vehicles/{id}` | as today; registry from the same read | **4**: vehicle_master 1, model 1, plans 1, components 1 | 0 | matches: one vehicle_master read serves registry fields |
| `GET /provinces` | 1 | **1** | 0 | matches |
| `GET /branches` | 1 | **1** | 0 | matches |
| `GET …/registration-history` | 2 | **2** | 0 | matches |
| `GET …/branch-history` | 2 | **2** | 0 | matches |
| registration change, province code | 3 / 2 | **3** (master, history, province) | **1 / 1** | matches |
| registration change, no province | 2 / 2 | **2** | **1 / 1** | matches |
| registration change, no-op | — | **2** | 0 | refinement (not estimated) |
| reconciliation ACCEPT_MASTER, no province | 2–3 / 1–2 | **2** | **1 / 0** | within range |
| reconciliation ACCEPT_MASTER, province (exception check) | 2–3 / 1–2 | **3** | **1 / 0** | within range |
| reconciliation APPLY_RECORDED, province | 2–3 / 1–2 | **3** | **1 / 1** | within range |
| reconciliation APPLY_RECORDED, cleared pair | 2–3 / 1–2 | **2** | **1 / 1** | within range |
| reconciliation, CONSISTENT (no-op) | — | **2** | 0 | refinement |
| transfer | 3 / 2 | **3** (master, history, branch_master) | **1 / 1** | matches |
| transfer, no-op | 2 / 0 (7O2d prompt) | **2** | 0 | matches |
| insertion | 3 / 1 | **3** | **1 / 0** | matches |
| correction, time-only (same destination) | 3 / 1–2 | **2** | **1 / 0**; latest-event time-only: 1 / 0 | **accepted R1 refinement** (7O2c R1: no R3 for an unchanged destination) |
| correction, new destination | 3 / 1–2 | **3** | older event **1 / 0**; latest event **1 / 1** | matches |
| cancellation | 2 / 1–2 | **2** (never branch_master) | older event **1 / 0**; latest **1 / 1** | matches |
| projection reconciliation, mismatch | 2 / 2 | **2** (never branch_master) | **1 / 1** | matches |
| projection reconciliation, CONSISTENT | 2 / 0 (7O2d prompt) | **2** | 0 | matches |

**Metadata (first use, cold client):** 1 worksheet-list request plus 1 per newly touched tab. Values reads and
writes are the same as warm. Measured:

| Request | Metadata |
| --- | --- |
| list | 2 |
| branch history | 3 |
| transfer | 4 |
| registration change with a province | 4 |

A repeated identical GET in the same process makes 0 metadata requests. This matches §6.8's "+1 metadata request
per tab" (measured P6/F1), plus the one worksheet-list request.

**Deviations:** only the time-only correction (2 reads, not 3). It is the accepted 7O2c R1 clarification, not a
defect. The two no-op rows were not estimated in §6.8; they are refinements. No value contradicts an estimate.

**Result: PASS — MEASURED.**

## 6. B-10 in its contract wording (test-only addition)

Final Rev2 §13.1 B-10 reads "projection reconciliation concurrent with a transfer (fake transport): limitation
reproduced; repair by a further reconciliation". The accepted 7O2c B-10 test covers two interleaved transfers. 7O2d
adds that exact scenario:
1. Rec-A reads a mismatch.
2. Rec-B repairs it.
3. A transfer to Bangna is recorded.
4. Rec-A writes from its stale read, so the master is Laem again while the history says Bangna.
5. The next read shows `PROJECTION_MISMATCH`, never hidden.
6. A further reconciliation makes it `CONSISTENT`.

This is the disclosed Sheets race (§6.7), not a defect.

## 7. I-03 — regression (2026-10-06)

| Check | Result |
| --- | --- |
| New 7O2d backend tests | 31 passed |
| Backend full suite | **3067 passed** (base 3036; +31) |
| Backend ruff | 13 findings, identical to the accepted baseline; none in 7O2d files (`All checks passed` on the new file) |
| Frontend new tests | 3 passed |
| Frontend full unit suite | **58 files, 645 passed** (base 57 / 642; +3) |
| Typecheck + build | exit 0; the existing chunk-size notice is unchanged |
| Lint (`oxlint`) | exit 0, **33 warnings**; the warning set (file + rule) is identical to the accepted baseline |
| Playwright inventory (R1) | **565 tests in 23 files** (base 540 in 21; +25 = 5 tests × 5 projects) |
| Playwright full suite (R1, standard invocation, includes the isolated I-OC-01 spec) | **565 passed, first run** |
| `vehicle-registry-integration` `--repeat-each 3` | **60 passed** |
| `vehicle-registry-ioc01` alone / `--repeat-each 3` (R1) | **5 passed** / **15 passed** |

No flaky failure occurred in this batch's runs.

**Result: PASS.**

## 8. I-05 — PostgreSQL

The §9 rows (branch tables, a transaction per mutation, registration tables, contexts) are **DEFERRED BY CONTRACT —
PLANNED FOR R11/R12**. Nothing PostgreSQL-related was implemented or tested in R1, and none is claimed.

## 9. I-OC-01 — literal end-to-end (R1)

Addendum: "7O2d e2e: a mocked 500 after a real mock-repository write shows the uncertainty banner, and the next
history read settles it." Spec `frontend/e2e/vehicle-registry-ioc01.spec.ts`, test "I-OC-01: a mocked 500 after a
real mock-repository write shows the uncertainty banner; the next real history read settles it". It runs on all 5
viewport projects inside the standard Playwright invocation.

**Isolation.**
- Each test run starts its own application backend: the real FastAPI app with the real `MockRepository`
  (`DATA_REPOSITORY=mock`), launched from `backend/.venv` with uvicorn on a free port.
- Its in-memory repository is fresh and private to that run; the process is stopped in `finally`.
- The browser's `/api/v1/**` calls are routed to it with `route.fetch()`.
- The shared mock backend that the other specs and projects use is never written. The test asserts that the shared
  VEH-1047 history does not contain the request id.
- No production code has a test hook; only the browser boundary is intercepted.

**Flow (VEH-1047, registration change `กข-1234 / TH-99` → `กข 7O2D` / no province):**
1. **Real mutation:**
   - the browser sends `PATCH …/registration` with a generated UUIDv4 `X-Request-Id`;
   - it reaches the isolated backend, which returns 200 `changed:true, master_write:WRITTEN` with the same
     `request_id`;
   - the isolated repository's history then contains exactly that request id and is `CONSISTENT`;
   - its master shows `กข 7O2D` with no province, so the master and history agree.
2. **Mocked 500 after the write:** only then does the browser receive a correlated 500 `INTERNAL_ERROR` instead of
   the real 200.
3. **Uncertainty kept:**
   - the banner shows "ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ" with the request id;
   - localStorage holds the intent with state `UNKNOWN`;
   - there is no settlement notice;
   - exactly one PATCH was sent.
4. **Next history read:**
   - this is the client's own re-read after an uncertain outcome;
   - it is held at the browser boundary while step 3 is asserted, then forwarded to the isolated backend;
   - its real response is delivered unmodified: 200, `CONSISTENT`, items' request ids = `[that id]`.
5. **Settlement:**
   - the banner disappears;
   - the notice "ตรวจสอบจากประวัติแล้ว … (<request id>)" appears;
   - the intent is gone from localStorage;
   - still exactly one PATCH was sent: there was no automatic resend.

The 7O2b/7O2c mocked-network I-OC-01 tests and the backend `test_b_oc_02_*` tests (both families) remain unchanged.

**Result: PASS.** 5/5, then 15/15 with `--repeat-each 3`, and within the full suite.

## 10. Stop state

- Uncommitted review candidate on `review/phase7-batch7o2d-integration-acceptance`. HEAD is `5f8069f`; the index is
  empty.
- No production source changed.
- No live Sheets access, no PostgreSQL, no R2.
- Nothing committed, pushed, merged or tagged.
