# R2 Batch R2f-h4 B2 — Scope-aware Technician Picker + Synthetic TEST Fixtures — Result

Status: IMPLEMENTED / UNCOMMITTED / READY FOR INDEPENDENT REVIEW. This is not self-certified.

Contract: C1 Amendment A1 (`docs/project-governance/c1-amendment-a1-v2-only.md`), §15 and §23, owner decision O4.

Baseline:
- `web/phase7-dashboard-search-reporting` @ `0ba3dd6f26a0b836d7259fbe3e58eb76ee3821a9`
  (tree `549e9859c3c4690fc6b008da357c8e6f67a10e92`);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Local branch: `review/r2-batch-r2f-h4-b2-scope-aware-technicians` (no remote).

Mock / fake only:
- no live Google Sheet was read or written;
- no schema, role, capability or production setting changed;
- the V2 cutover stays OFF by default.

**B4 has not been implemented. No frontend mock E2E exists or has passed.**

## 1. Scope rule (A1-§15)

`GET /api/v1/technicians` and `GET /api/v1/technicians/{technician_id}`:

| Server context | Rows |
|---|---|
| REAL | rows the repository proves REAL only (every live row) |
| TEST (with a batch) | rows the repository proves TEST-scoped AND of exactly the server batch (`REGISTRY_TEST_BATCH_ID`; mock: `MOCK-7O2B-SYNTHETIC`). Live TEST: the live master is untagged REAL, so the result is empty. |
| UNCONFIGURED, or TEST without a batch | 503 `REGISTRY_DATA_CONTEXT_NOT_CONFIGURED`, before any repository read |

- **Server-derived scope.** `Settings.registry_context_effective` plus `effective_test_batch_id`, the same inputs and
  the same guard (`require_write_context`) as the relationship routes. The rule (`technician.in_server_scope`) is
  pinned by a parity test to `personnel_relationship.same_scope`. That function could not be imported directly,
  because `personnel_relationship` imports `technician`.
- **No client scope.** No query parameter selects a scope: unknown parameters are ignored, and the OpenAPI
  parameters are only `page`, `page_size` and `technician_id`.
- **Unchanged:**
  - `can_view`, checked before the context check and before any read;
  - paging (`page >= 1`, `page_size` 1–200, default 20);
  - sort by `technician_id`;
  - the response shape;
  - the identity-integrity fail-closed behaviour (500 `TECHNICIAN_MASTER_DATA_INVALID` with counts only; 409
    `TECHNICIAN_ID_AMBIGUOUS`), now evaluated over the returned scope. A defect confined to another scope never
    blocks this scope.
- **Not changed:** `GET /technicians/{id}/personnel` and `/equipment` were already scope-aware. There were no
  repository, schema or other API changes.

## 2. Synthetic mock fixtures (O4)

Added to `app/repositories/mock/seed_data.py`. All rows are synthetic, of the mock server batch, and exactly ACTIVE:

| Personnel (TEST, mock batch) | technician_id → Technician (TEST, mock batch) | user_id → Account (TEST, mock batch) |
|---|---|---|
| `PER-TEST-911` | `TEC-TEST-911` | `USR-TEST-911` |
| `PER-TEST-912` | `TEC-TEST-912` | `USR-TEST-912` |

- **New ids only.** Every existing fixture and id is unchanged:
  - `TEC-TEST-001` / `-002` (REAL), `TEC-TEST-901` (TEST, still unlinked), `USR-TEST-001` / `-901`;
  - `PER-TEST-001..003` and `PER-TEST-901` (batch `MOCK-SEED-R2C1`);
  - the R2c-1 operational personnel list (3 rows).
- **Proven by tests:**
  - both chains resolve both ways (`/personnel/{id}/relationships`, `/technicians/{id}/personnel`);
  - both pass the unchanged R2f-h1 BOTH-ACTIVE gate (PRIMARY 911, COLLABORATOR 912) on mock TEST V2 Repair and PM
    jobs;
  - V2 My Work (`GET /my-work`) resolves for `USR-TEST-911` (PRIMARY) and `USR-TEST-912` (COLLABORATOR).
- **Test-only setting.** The dedicated mock test process with `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` (O4) belongs to
  B4. Nothing in B2 enables it.

## 3. Deliberate R2f-a test amendments (A1-§23 item 1)

All are in `tests/test_relationship_read_batch_r2f_a.py` and marked "R2 Batch R2f-h4 B2 (deliberate evolution)":
1. **`test_r2fa_01_list_is_sorted_real_scope_only_and_bounded`:** the fixtures become mock-batch TEST rows.
   - Kept: an other-batch TEST row and a REAL row, which must not be listed in TEST.
   - Added: an explicit REAL-context assertion that lists only the REAL row.
2. **`test_r2fa_01_detail_exact_id_missing_and_duplicate`:** in-scope (mock-batch TEST) fixtures, plus a REAL row that
   must 404 in TEST.
3. **`test_r2fa_01_list_fails_closed_on_duplicate_or_blank_id`:** in-scope fixtures.
4. **`test_r2fa_09_every_r2f_a_route_performs_zero_writes`:** the detail probe id changes from `TEC-TEST-001` (a REAL
   seed row, now correctly 404 in TEST) to `TEC-TEST-901` (the seed TEST technician of the mock batch). Its
   zero-write and read-only assertions are unchanged.

   This amendment is covered by A1-§23 item 1, as clarified by the B2 governance correction to explicitly name
   `test_r2fa_09` and explain its single probe-id change. It is the same O4 consequence, and its intent is
   preserved.

The Sheets R2f-a suite (REAL context) is unchanged and passes. No other existing test changed.

## 4. Compatibility impact

- **REAL (live Sheets):** no change.
- **TEST in mock:** the list now shows the mock-batch TEST technicians (`TEC-TEST-901`, `-911`, `-912`) instead of
  the REAL-scoped seed rows. The frontend does not call `/technicians` today, so no current consumer breaks.
- **Live with `REGISTRY_DATA_CONTEXT` unset:** the routes now answer 503 instead of REAL rows. The live deployment must
  set the context; this is a deployment verification item, not a change made here.

## 5. Tests

**New `tests/test_technicians_scope_batch_r2f_h4_b2.py`** (18 tests):
- REAL list/detail;
- TEST list/detail;
- other-batch exclusion, plus the parity of the scope rule with `same_scope`;
- UNCONFIGURED and TEST-without-batch → 503 with zero reads;
- 403 before context and reads, and `can_view` roles unchanged;
- integrity over the returned scope;
- paging, sorting and shape;
- no client-selectable scope (seven query variants, plus the OpenAPI parameters);
- fixture rows, both-way resolution, the BOTH-ACTIVE gate with V2 assignment, V2 My Work;
- existing seed ids and behaviour preserved;
- compatibility with the V2 reads and read signals.

**Fix-removal mutations:** 10 of 10 caught (B01–B10):
- the context check removed;
- the batch ignored;
- REAL admitting TEST;
- a revert to REAL-only;
- a hard-coded route context;
- the detail ignoring scope;
- integrity evaluated over all scopes;
- a fixture technician unlinked;
- a fixture in another batch;
- a fixture not ACTIVE.

## 6. Remaining dependencies

- **B3:** the U1 waiting routes.
- **B4:** the V2 frontend and the mock E2E in a dedicated mock process with the setting ON.
- **B5:** legacy UI removal.
- **B6:** legacy backend cleanup, separately authorized.
- **Live:** set `REGISTRY_DATA_CONTEXT` in live (verification); R11, links, the live schema and Go-live each need
  their own approval.
- **Unchanged:** D5 PENDING; H3-01 fail-closed.
