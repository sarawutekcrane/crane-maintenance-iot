# R8 PRE-UAT — Whole-Web Completion Result (final correction)

STATUS: **IMPLEMENTATION REVIEW CANDIDATE — NOT ACCEPTED**

**Scope**
- Branch `feature/r8-whole-phase`, base `894d4ea5e225eb6f33aa57a050c3d64ef2e6da27`, **uncommitted** working tree.
- Owner approvals:
  - R8 PRE-UAT Whole-Web Completion Rev 1 (93 paths; A2 capabilities; fail-closed D-2…D-8; D-9 not approved);
  - Consolidated Source Expansion Gate of 2026-11-18: SG-PM approved (#94–#96), PG-5 option P-A selected (`can_test_manage_parts`, #97). The exact allowlist is now 97 paths.

**What this report is not**
- Not an R8 or Phase 7 acceptance.
- Not PostgreSQL evidence and not production readiness.
- R9 has not started.

Google Sheets is TEST-only and was never written. **A Mock pass is not a PostgreSQL pass.**

## 1. Disposition per item

| Item | Result | Status |
|---|---|---|
| A — TEST master records | Create / edit for 7 entities; TEST-scoped IDs; record + audit committed as one Mock unit (no ghost audit); replay, duplicates, REAL 409, Sheets 501; UI on the list / detail pages and `/master-data` | IMPLEMENTED (Mock/TEST) |
| **B — PM Master TEST (SG-PM)** | `PM_MASTER_TEST_PROFILE=true` (Mock + AM + non-production only) registers 9 `/api/v1/pm-master-test/*` routes from `app.main`. Flow: built-in synthetic source → REVIEW meter decision → publish → model-variant approval → assignment → vehicle Due → open a Master-sourced E01 PM Work Order. Authority only from `can_test_pm_master_publish` / `can_test_pm_master_assign` (verified AM employee). The default application never loads the Master. Protected PM domain files unchanged. UI: `/pm-master-test` and the TEST panel on the vehicle PM Due page | IMPLEMENTED (Mock/TEST) |
| D — Store (Decision 1) | Request → approve / deny → issue → use → declare return → accept return → reconcile, **per physical identity** (part + instance). Tracked instances are issued once, move one whole unit at a time, and only when their lifecycle status allows. No stock ledger; future event contract with a reference consumer. Request recovery keyed on the request id (intent journal) | IMPLEMENTED (Mock/TEST) |
| E — Repair classification (Decision 2) | TEST-CANDIDATE-R1 (24 relationships); stage / finalize only when the repair is closed and the Store reconciled (re-checked right before the write); every invalid code refused; never REAL | IMPLEMENTED (Mock/TEST) |
| F — Parts (PG-5 P-A) | Part-set editor and maintenance events against INSPECT / REPAIR rules, in AM mode for `can_test_manage_parts` holders. The other 7 R6 part writes stay unresolved. No direct new-cycle control (R6 A-2(ii)) | IMPLEMENTED (Mock/TEST) |
| Fixture profile | `uat_r8`: `UAT8-` fleet, people, certificates, counters, locations; one tracked part instance with synthetic INSPECT / REPAIR rules | IMPLEMENTED |
| D-9 | No workbook write; separate UAT result report in the export pack | AS INSTRUCTED |

## 2. Independent reviews and fixes (all fixed, with regression tests)

### Review 1 (9 findings)

- **Store quantities:** use and return-acceptance cross-guards, so balances never go negative.
- **Store requests:** orphaned material-request append.
- **Classification:** finalizing with unsaved rows; the fingerprint exposed in the view; reconciliation re-checked before the classification write.
- **UI:** request id kept after cancel / reopen on an uncertain failure; decimal quantity input; panels hidden on 501 / 403.
- **Catalogue:** extract hash pinned in code.

### Deep review (memo of 2026-11-18)

- RETURN events now carry the actual part identity, with per-identity guards.
- Master record and audit are written atomically.
- Store request recovery is in place.

### Review 3 (6 findings)

1. **Part-set create / revision have no server replay.** Those routes are outside the allowlist, so the UI no longer promises a safe resend; see the limitation in §3.
2. **Recovery after close:** fixed. Recovery is keyed on the request id through an intent journal and works after technical close.
3. **A different request adopting an in-flight material request:** fixed. Adoption is keyed on the request id, with the CREATED marker and an exact-lines fallback.
4. **Fractional moves of a tracked instance, and unavailable instances:** fixed. Instances move one whole unit at a time, and INSTALLED / IN_REPAIR / SCRAPPED instances cannot be issued.
5. **Grant descriptions disagreed with the code:** the catalogue text now says that variant decisions belong to the publish grant.
6. **Firewall exemptions by bare file name:** now by exact path. `test_23c` restates the skipped checks and proves no other file carries those names.

## 3. Remaining limitations (stated, not hidden)

- **Part-set provenance and replay.** `POST /part-sets` and `/revisions` (existing handlers, outside the allowlist) record no actor (`created_by`) and have no request-id replay. D6 guarantees the writer is a verified employee holding `can_test_manage_parts`, but the rows carry no provenance, and a resend after a lost answer can duplicate.
- **PM completion meters.** The application has no IoT meter source (R9), so a completed PM Set stays UNKNOWN in the app. The 650 h + 600 h → 1250 h rule is proven at service level with a TEST-only fake verified source.
- **PM alerts and thresholds.** PM alerts from the TEST Master are not wired into the R7 evaluator. Near-due and calendar conventions wait on Owner D-4.
- **Instance custody after use.** An instance confirmed as USED stays out of Store custody. Returning it to stock after a later removal is a future stock / exception-policy matter (OPEN-003).
- **One-process Mock guarantees (R11).** These are not database transactions: journal `expected_count` guards, the Store request's two writes (intent journal, recovery and freeze), the master record + audit commit, and the classification late re-check. A material request whose header was written without all of its lines (in the existing material-request service) would stay frozen.
- **Carried Owner gates.** SG-1, A-5, H03, OPEN-003, D-4, D-6. External messages unsupported. Real devices and other browsers not run.
- **Manual browser UAT.** Not executed (the matrix has PASS_MANUAL 0). It is the Owner's next gate.

## 4. Tests — one final snapshot

Code fingerprint (SHA-256 over the sorted per-file hashes of all changed non-doc paths): see `R8_PREUAT_FINAL_TEST_EVIDENCE.md`.

| Suite | Result |
|---|---|
| Backend full (4 parallel file shards; includes all PM Master firewall suites) | 6648 passed, 4 skipped, 0 failed (1263 + 2158 + 1501 + 1726) |
| Frontend `tsc -b` / oxlint / build | clean / 29 warnings = baseline, 0 errors / passed |
| Frontend Vitest | 108 files, 1319 passed |
| Playwright default (5 viewports + responsive-photo) | 754 passed, 235 skipped (viewport / mode gated), 0 failed |
| Playwright `PREUAT_E2E=1` (AM + `uat_r8` + PM Master TEST profile) | 21 passed, 54 skipped (writes on desktop only), 0 failed |
| Playwright `ACCESS_MANAGEMENT_E2E=1` | 10 passed, 20 skipped, 0 failed |
| Mutation checks (30 guards, one at a time in a scratch copy) | 30 / 30 killed (3 first survived; their tests were strengthened and the 3 re-run killed) |
| UAT matrix | 67 scenarios: 60 PASS_AUTO, 4 NOT_APPLICABLE, 2 BLOCKED_BY_OWNER_POLICY, 1 NOT_RUN, 0 PASS_MANUAL, 0 FAIL |

## 5. Git

Nothing staged, committed or pushed. No PR, merge or deploy; no Sheets / REAL / production change. The changed paths are
96 of the 97 approved (`seed_data.py` unchanged, as approved). The repair-catalogue JSON sits under `.gitignore` `data/`:
a future, separately approved Git gate needs `git add -f` for exactly that path.

## 6. Follow-up 2026-11-19 (cloud browser evidence)

- **ISS-01 fixed** in `RepairDetailPage.tsx` (+ `StoreRequestPanel.tsx` refresh signal, tests). The "อะไหล่ที่ใช้จริง" card now shows two separately labelled sources:
  - confirmed Store uses (USE_CONFIRMED, read-only, with part / instance / quantity / unit / position / source event);
  - the manually entered repair parts, unchanged.

  Nothing is copied or merged. No permission, a repository without the workflow, and a failed or malformed read are each stated, never shown as zero. The Store panel now also treats a malformed reconciliation body as an error.
- **Manual browser UAT access: BLOCKED.** The cloud container's 127.0.0.1 is not the Owner's computer, and no approved authenticated route exists. Owner decision options are in the follow-up pack. PASS_MANUAL stays false for all 67 scenarios.
- **Final follow-up snapshot** `ad703e387fe9141f77f4db318631b0d951c4599353377409b291d0bb66b00d8a`:
  - backend 6648 passed, 4 skipped, 0 failed;
  - Vitest 108 files, 1331 passed;
  - tsc clean; lint 29 = baseline; build passed;
  - Playwright default 754 passed / PRE-UAT 21 passed / Access Management 10 passed, 0 failed;
  - live browser run2: 38/38 (30 UI, 7 API, 1 API+UI readback).

## 7. H1-DIRECT hosted TEST identity — source Gate A (2026-11-19)

- **Owner source approval Gate A:**
  - new paths #98 `backend/app/context.py`, #99 `backend/app/domain/test_identity_proxy.py`,
    #100 `backend/tests/test_preuat_identity_proxy.py`, #101 `deploy/uat-r8/Dockerfile`,
    #102 `deploy/uat-r8/Dockerfile.dockerignore`;
  - TEST-gated edits to the approved `config.py`, `main.py`, the UAT guide (§7), `CHANGELOG.md` and this file;
  - exact allowlist: 102 paths.
- **Not approved:** Gate B (Git) and Gate C (deployment / IAM / billing). Nothing is staged, committed,
  pushed or deployed.
- **Manual browser UAT:** still not executed (PASS_MANUAL false for all 67 scenarios).
- **Evidence** (tests, local image build and smoke, mutation checks, independent review) is in the Gate A export
  pack.

