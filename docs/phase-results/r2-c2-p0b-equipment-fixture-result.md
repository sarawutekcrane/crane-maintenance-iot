# R2-C2-P0b — Mock/TEST Equipment Fixture — Result

Status: **Implemented and tested; committed and pushed to review branch. Integration not yet authorized as of this
documentation update.**
- P0b implementation commit `53efc97a247ea8ae5e495ee0673894d58808a277`, pushed (owner-authorized) to
  `review/r2-c2-p0b-equipment-fixture`; a documentation-only alignment (comments and this status) followed on the same
  branch.
- Integration merge has NOT been performed and requires separate owner approval.

Mock / tests only. No API, route, schema, authorization, scope rule, Google Sheets, production or REAL-data change.
R2-C2a and R2-C2b have NOT started. Personnel scope remains unresolved (§8).

## 1. Baseline

| Item | Value |
|---|---|
| Integration branch / HEAD | `web/phase7-dashboard-search-reporting` @ `44babb15ebc29ad4e43f4d40da25e232a9095485` (R2-C2-P0 integrated) |
| Tree | `4728c87e3bb8420257d24796024a8c8ca320674b` |
| Main | `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (unchanged) |
| Backend suite at this HEAD, clean tree (executed in this session) | **4845 passed, 0 failed** |

## 2. Source change

`backend/app/repositories/mock/seed_data.py`, `SEED_EQUIPMENT_REFERENCE` — one entry changed (plus a comment):

```
-    ({"equipment_id": "EQP-0002"}, "REAL", ""),
+    ({"equipment_id": "EQP-0002"}, "TEST", _seed_test_batch()),
```

`mock/repository.py` is unchanged: it already projects this explicit list (`self._equipment_reference`).

## 3. Equipment reference classification

| Equipment | Before | After |
|---|---|---|
| EQP-0001 | REAL | REAL |
| **EQP-0002** | REAL | **TEST** (mock batch) |
| EQP-0003 | REAL | REAL |
| EQP-TEST-901 | TEST (reference only) | TEST (unchanged) |

Scope comes from the explicit entry, never from the id spelling. The Equipment Master (list / detail / status /
history) is unchanged and still holds exactly EQP-0001, EQP-0002, EQP-0003.

## 4. Why EQP-0002

The read-only P0b preflight simulated each candidate at runtime against the full suite:

| Candidate | Result |
|---|---|
| EQP-0001 | 1 failure (`test_go_live_readiness_batch_r2f_h3::…test_caretaker_on_real_equipment`: used as the REAL equipment); referenced by 21 test files |
| **EQP-0002** | **4845 passed, 0 failed; warning count unchanged**; no caretaker test depends on it |
| EQP-0003 | 4845 passed but +18 warnings (an existing path changes behaviour) |

## 5. Verification

`backend/tests/test_r2_c2_p0b_equipment_fixture_batch.py` — 14 tests (isolated MockRepository per state-changing case;
no caretaker history seeded):

| Group | Proves |
|---|---|
| P0B-MASTER | Equipment list is exactly EQP-0001..0003 (`total_items` 3); `GET /equipment/EQP-0002` 200 with its seed master data unchanged |
| P0B-PROJ | the reference projection is exactly EQP-0001 REAL, EQP-0002 TEST (mock batch), EQP-0003 REAL, EQP-TEST-901 TEST — each once |
| P0B-CARE | `GET /equipment/EQP-0002/caretakers` in TEST; TRANSFER ×2, INSERTION, CORRECTION, CANCELLATION and END with TEST technicians TEC-TEST-911 / -912; revision stale guard (`CARETAKER_HISTORY_STALE`); expected-current stale guard; history in-force flags, revision numbers, `recorded_by`; effective time distinct from recorded time; `GET /technicians/{id}/equipment` lists EQP-0002 while current and not after END |
| P0B-ISO | EQP-0001 / EQP-0003: caretaker read and write → 422 `EQUIPMENT_SCOPE_UNPROVEN`, nothing written; EQP-0002 never resolves in the REAL context; a REAL technician on EQP-0002 → 422 `TECHNICIAN_SCOPE_UNPROVEN`; a duplicated reference → 409 `EQUIPMENT_ID_AMBIGUOUS`; TECHNICIAN / DRIVER / SUPERVISOR / DRIVER_DEPARTMENT_MANAGER still refused (403, nothing written) and still able to read (can_view) |

## 6. Test results (executed)

| Run | Result |
|---|---|
| P0b tests | **14 passed** |
| Groups B–G: Equipment Master, status, text preservation (+Sheets), branch history / writes, R2f-d caretaker (+Sheets), technician scope, R2f-a relationships, go-live readiness (+Sheets), health, read signals, Technician V2-only, R2-C2-P0 fixtures (18 files incl. P0b) | **629 passed, 0 failed** |
| Full backend suite | **4859 passed, 0 failed** (= 4845 baseline + 14 P0b; 0:15:40) |
| Frontend Vitest | **798 passed** (66 files) |
| Frontend lint (`oxlint`) | exit 0 (pre-existing warnings only) |
| Frontend build | passed |
| Playwright: `equipment-status-change`, `vehicle-equipment` (live mock backend), `equipment-search-completeness`; 5 viewport projects | **80 passed, 0 failed** |

The full Playwright suite (28 specs) was not run — only the specs that read equipment data.

## 7. Diff and allowlist

Exactly three paths: `backend/app/repositories/mock/seed_data.py` (M), the new test file (A) and this document (A).
`mock/repository.py`, domain logic, routes, schemas, authorization, TEST/REAL configuration, Google Sheets
repositories, Personnel, Technician V2, legacy driver code, frontend and governance are untouched.

## 8. Limitations

- **Personnel scope is NOT resolved and is outside P0b.** R2c-1 Personnel list / detail are operational-only in
  every context, while R2e / R2f personnel reads follow the server context; in mock (TEST) no personnel page can show
  working R2f-a/b/c/e/g data. Closing it needs a separate owner-approved R2c-1 scope change (O4 / A1-§15 precedent).
- EQP-TEST-901 remains a reference-only TEST equipment (unchanged).
- The Equipment Master pages have no scope column; the TEST status shows through the R2 panels' data-context banner
  (R2-C2a).

## 9. Next

Commit / push to `review/r2-c2-p0b-equipment-fixture` is done (`53efc97a`, then the documentation-only alignment).
Integration (fast-forward of `web/phase7-dashboard-search-reporting`), the Personnel scope correction, R2-C2a and
R2-C2b each still need their own owner authorization.
