# R2 — Formal Owner Acceptance Record

Status: **R2 — ACCEPTED WITH APPROVED R11 DEFERRAL & PRODUCTION RESTRICTIONS** (formal owner decision, recorded in
"R2 — Formal Owner Acceptance Record — OWNER ACCEPTED — DOCUMENTATION ONLY", 2026-10-18).

This record covers documentation only. It does not authorize a main merge, deployment, REAL or production E2 use,
any Live Google Sheets operation, or R3 work. Earlier phase-result documents are kept unchanged as historical
evidence; their own status lines describe the state at the time they were written.

## 1. Acceptance baseline

| Item | Value |
|---|---|
| Integration branch | `web/phase7-dashboard-search-reporting` |
| Acceptance baseline HEAD | `88d14a813cefb0bc83df402b8632e9b5f5e41d17` (R2-C4 integrated) |
| Main at acceptance | `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (unchanged; not part of this acceptance) |
| Governance | `docs/project-governance/c1-amendment-a2-driver-responsibility.md`, A2-10 "Acceptance and Sequencing" |
| Acceptance matrix | REV5 `R2_Temporary_Driver_Contract_Amendment_REV5_OWNER_REVIEW_DRAFT.txt` (owner-supplied, not in the repository), SHA-256 `f15415d63936539546723c75dbb421e64edce7e8ba6e2d90cd9de7177a03dc35` |

## 2. Scope accepted: R2-C0 through R2-C4

All R2 implementation and acceptance corrections below are integrated in the baseline above.

| Batch | Integrated commit(s) | Evidence |
|---|---|---|
| R2-C0 — A2 governance amendment | `6cf76173e32ee373bad8a03e240b20b64d5d646e` | `docs/project-governance/c1-amendment-a2-driver-responsibility.md` |
| R2-C1 — mock E2 backend | `b885bffb93d2edd169c948e9f01b8090ceed6b8d` | `r2-c1-e2-backend-result.md` |
| R2-C2 preparatory (P0, P0b, Option S) | `44babb15…`, `53efc97a…`, `d7659186…`, `d09d8958…` | `r2-c2-p0-test-fixture-result.md`, `r2-c2-p0b-equipment-fixture-result.md`, `r2-c2-personnel-scope-option-s-result.md` |
| R2-C2a — relationship and history panels | `f931f2db29d0e2a8875a5f841758c85fd7a01c82` | `r2-c2a-frontend-result.md` |
| R2-C2b — E2 frontend | `3a3d4bf3691884c1a756807001d8435b1c54e9b1` | `r2-c2b-e2-frontend-result.md` |
| R2-C3 — legacy vehicle-driver cutover | `19a9a3d66a6c00c71663959a7c49f1e413a46041` | `r2-c3-legacy-cutover-result.md` |
| R2-C4 — final acceptance corrections | `88d14a813cefb0bc83df402b8632e9b5f5e41d17` | `r2-c4-final-acceptance-result.md` |

Result documents are in `docs/phase-results/`.

## 3. REV5 B01–B30 acceptance matrix

The full per-item evidence is in `r2-c4-final-acceptance-result.md` §4.

| Outcome | Count | Items |
|---|---|---|
| PASS | 29 | B01–B27, B29, B30 |
| DEFERRED | 1 | **B28 → R11** (production concurrency: one winner) |
| BLOCKED | 0 | — |
| UNVERIFIED | 0 | — within the matrix |

Last recorded test evidence on the accepted code (from the R2-C3 and R2-C4 results; not re-run for this record):

- backend 4898 passed;
- full frontend Vitest 974 passed;
- Playwright read-only 75 passed;
- R2-C2b isolated mutation run 5 passed;
- TypeScript, lint and build passed.

## 4. Approved deferral and restrictions (binding)

1. **B28 is a mandatory R11 dependency.** The mock version guard proves single-process behaviour only. It is not
   production concurrency or atomicity, and R2 makes no such claim.
2. **E2 REAL and production use remain prohibited before R11.** REAL writes are refused (409
   `E2_REAL_WRITES_NOT_ENABLED`), and Google Sheets mode answers 501.
3. **External consumers of the retired legacy APIs remain UNVERIFIED.** They must be investigated (for example
   through production access logs) before any deployment.
4. **Pending UNKNOWN / CONFLICT requests** fail closed by design. They may require an authorized manual
   investigation.
5. **Fleet-wide date-only search** is outside the approved R2 scope. Search is per vehicle and per driver only.
6. **Live Google Sheets and historical data remain protected.** R2 made no Live Sheets access and no REAL data
   operation. The live `driver_master` and `vehicle_driver` tabs were not modified, deleted, renamed, recreated,
   migrated or seeded.
7. **Not executed in R2:** the full Playwright suite (all specs) and browsers other than Chromium.

## 5. What this acceptance does not claim or authorize

- R11, B7 readiness, D5, H3 (A2-10) and production readiness are **not complete**. This record does not claim
  otherwise.
- R3 (inspection and follow-up) is the next planned phase. It is **not authorized** by this acceptance and needs its
  own owner authorization.
- **No main merge and no deployment** are authorized.
