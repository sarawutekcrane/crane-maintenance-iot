# R4-B1 — PM Master Foundation (Mock only) — Result

Status: B1 CANDIDATE / UNCOMMITTED / LOCAL ONLY. Ready for Owner code review. This is not
Production readiness and not authorization to push, merge or deploy.

Instruction: `CLAUDE_CODE_R4_B1_MOCK_IMPLEMENTATION_PACKAGE_2026-10-21.md` (Owner-supplied in session).
The supporting R4 documents it cites (FC-1 contract candidate, B1 execution specification, decision
register V4, cleanup review plan) are not in this repository or environment; the package itself was
used as the controlling bounded scope.

## 1. Base, branch, preflight
| Gate | Result |
|---|---|
| Base branch | `feature/access-management-l11-mock` |
| Base HEAD | `753f389de7e3328d0104c1ede515714d664bad39` (exact match) |
| Working tree before work | clean (0 entries) |
| Working branch | `feature/r4-pm-master-b1-mock`, created locally from the verified base; did not exist locally or on `origin` |
| Commit / push / PR | none |
| Baseline narrow tests (before any edit) | 326 passed, 0 failed (PM, R3, AM, V2, vehicle-model suites) |

No preflight deviation.

## 2. Files
New: 4. Modified: 0. Removed: 0.

| Path | Kind | Classification | Reason / consumers / rollback |
|---|---|---|---|
| `backend/app/domain/pm_source_preview.py` | new | RETAIN (new, B1) | D1 read-only preview. Pure, no I/O. No runtime consumer (verified by the import scan in B1-17). Rollback: delete the file. |
| `backend/app/domain/pm_master.py` | new | RETAIN (new, B1) | D2–D5 Mock Master, assignment, firewall, fail-closed authorizer. No runtime consumer. Rollback: delete the file. |
| `backend/tests/test_pm_master_b1_mock.py` | new | RETAIN (new, B1) | 21 Mock-only tests. Rollback: delete the file. |
| `docs/phase-results/r4-b1-pm-master-foundation-mock-result.md` | new | RETAIN (new, B1) | This report. |

Existing symbols inspected, NOT touched:

| Symbol | Classification | Evidence |
|---|---|---|
| `VehicleModel.assigned_pm_plan_id` | RETAIN | Consumers: `PmService.list_applicable_plan_status` and `open_work_order` (`backend/app/domain/pm_service.py:91,188`), Sheets adapter (`google_sheets/repository.py:367`, `schemas.py:106`), `api/v1/vehicle_schemas.py:23`, `frontend/src/lib/types.ts:65`, 4 backend test files. Not reinterpreted. The B1 resolver returns it only as `legacy_model_plan_id` (non-authoritative). |
| `PmPlan`, `PmTaskRevision`, `PmTask`, `PmWorkOrder`, `PmWorkResult.completed: bool`, `PmWorkOrderStatus{OPEN,CLOSED}` | RETAIN | The current runtime PM flow. B1 does not feed into it (D4). |
| `SEED_PM_PLANS` / `PMREV-0001` / `PMT-0001..0003` | RETAIN, non-authoritative placeholders | Asserted unchanged by B1-18. Not activated, not deleted. |
| `GET /pm/work-orders/my-work` (410) | RETAIN | Asserted by B1-18. |
| `PmTriggerType.CALENDAR` | DEFER | Still used by the legacy model. The B1 Master refuses it (no calendar substitute). |
| `authz.CAN_MANAGE_PM` | RETAIN | It is the E01 Work Order capability, NOT Master authority (see §4). |
| `request_replay.request_fingerprint` / `find_replay` / `canonical_json` | RETAIN (reused) | Reused by B1 for replay and digests. Unchanged. |

No REMOVE candidate was found or proposed.

## 3. Source preview: counts, ledger, digest
`MAINTENANCE.xlsx` is **not available** in this environment. It was not requested, uploaded or read.
Full-workbook row accounting is therefore **UNVERIFIED**:

| Source tab | Package reference expectation | Observed |
|---|---|---|
| `source_pm_cycles` | 260 (PLAN1 62, PLAN2 18, PLAN3 60, PLAN4 120; 231 hour, 29 km) | UNVERIFIED (not read) |
| `source_pm_items` | 1,146 (CARRIER 374, CRANE 290, NOT_SEPARATED_IN_FORM 482) | UNVERIFIED |
| `source_pm_standard` | 49 (44 usable, 4 blank templates, 1 cancelled) | UNVERIFIED |
| `vehicle_pm_mapping` | 235 (183 mapped candidates, 52 no Plan) | UNVERIFIED |
| `replacement_policy` / `replacement_items` | 13 / 38 | UNVERIFIED |

The header names the preview expects (`REQUIRED_COLUMNS` in `pm_source_preview.py`) are a B1 contract
and are UNVERIFIED against the real workbook. A real header that differs makes rows REVIEW; it is
never guessed.

Synthetic fixture accounting (proved by tests B1-02..B1-06):

| Tab | Total | Accept | Review | Exclude |
|---|---:|---:|---:|---:|
| `source_pm_cycles` | 13 | 4 | 9 | 0 |
| `source_pm_items` | 13 | 6 | 7 | 0 |
| `source_pm_standard` | 4 | 2 | 0 | 2 |
| `vehicle_pm_mapping` | 6 | 5 | 1 | 0 |
| `replacement_policy` / `replacement_items` | 2 / 1 | 0 | 0 | 2 / 1 |
| unknown tab | 1 ledger entry `SHEET_OUT_OF_B1_SCOPE` | | | |

Ledger issue codes: `MISSING_REQUIRED_VALUE`, `AMBIGUOUS_RAW_35`, `UNKNOWN_SECTION`,
`DRIVING_COMPONENT_ABSENT`, `METER_NOT_EXPLICIT`, `UNIT_METER_MISMATCH`, `INVALID_INTERVAL`,
`DUPLICATE_SET_IDENTITY`, `DUPLICATE_ITEM_KEY`, `DUPLICATE_DOC_CODE`, `DUPLICATE_VEHICLE_REF`,
`INVALID_SEQUENCE`, `SET_NOT_ACCEPTED`, `REFERENCES_NONCURRENT_DOC`, `UNRESOLVED_SOURCE_DOC`,
`UNKNOWN_DOC_STATUS`, `DOC_CANCELLED`, `DOC_BLANK_TEMPLATE`, `REFERENCE_ONLY_IN_B1`,
`SHEET_OUT_OF_B1_SCOPE`.

Every ledger entry carries `source_file, sheet, row_or_key, column, raw_reference, issue, reason,
action, evidence, reviewer, reviewed_at` (plus `plan_code`). An unresolved REVIEW (empty reviewer)
blocks publish for its Plan.

Digest: SHA-256 of the canonical JSON of the accounts, ledger and candidates. It is identical across
repeated runs and tab orders, and changes when any source text changes (B1-01). The real-workbook
digest is UNVERIFIED.

## 4. Access Management: Master write authority NOT proven (gate VAL-AM, fail closed)
Evidence: the AM catalog (`access_management.py` `CATALOG`) describes `can_manage_pm` as
"เปิด กำหนดขอบเขต มอบหมาย/ถอนช่าง และปิดใบงาน PM": Work Order operations only. No capability
authorizes writing the PM Master. Root and delegated permission administration is explicitly not a
functional capability.

So:
- The only application authorizer, `deny_unproven_master_authority`, refuses every write: 403
  `PM_MASTER_AUTHORITY_UNPROVEN`, `details.gate = "VAL-AM"`.
- No capability was added, and no role or position was given the power.
- No API route was exposed, for read or write.
- Reads require the existing `can_view`.
- Publish and assignment semantics are exercised only with a test-only authorizer defined inside the
  test file.

AM negative tests (B1-13, real `AccessService.effective_context` on the AM Mock seed):

| Actor | Read | Write |
|---|---|---|
| Root holder with `can_view` + `can_manage_pm` | allowed | denied |
| `can_manage_pm` only | denied | denied |
| Revoked `can_view` | denied | denied |
| Department transfer (period ended) | denied | denied |
| Out-of-department delegate grant | refused by AM; target denied | denied |
| Inactive employee | denied | denied |
| Unknown account with dev ADMIN role | denied | denied |
| Legacy-mode ADMIN with every capability plus forged capability names | n/a | denied |

The Master store was byte-identical afterwards.

## 5. Revision immutability, history firewall, optional assignment
- **Revisions:** published revisions are frozen pydantic models, and Rev N is unchanged after N+1
  (B1-09). Publish is atomic (copy-then-assign commit of revision + event), revision-checked
  (`PM_MASTER_STALE_REVISION`), refuses identical content (`PM_MASTER_UNCHANGED`) and refuses
  invalid candidates with no residue.
- **Concurrency:** 5 concurrent publishes give 1 revision and 1 audit event; 4 are refused as stale
  (B1-14). The Mock lock is single-process only (not R11 production atomicity).
- **Replay:** the same actor + request id + payload replays. A different payload or operation with
  the same id gets `REQUEST_ID_REUSED`. Authority is checked before any replay is disclosed (B1-15).
- **Work Order snapshots:** a frozen selection of Rev 1 is unchanged after Rev 2 and Rev 3. Runtime
  `OPEN` and `CLOSED` PM Work Orders (`PMREV-0001`) are byte-identical through Master publishes
  (B1-10). No E01 state is represented or invented. A frozen selection is a value; B1 stores no Work
  Order.
- **Assignment:** `NONE` (explicit unassignment) is distinct from `ABSENT`. Assign / change /
  unassign / new Plan each have a reason, a version check and an audit event, and history is kept
  (B1-11). An explicit NONE is never overridden by `assigned_pm_plan_id`. The legacy route, the
  model API and Work Order opening are unchanged (B1-12).
- **Assemblies:** CARRIER and CRANE are assemblies of the same `vehicle_id`, with distinct driving
  components and intervals (B1-07).
- **Item lineage:** follows the stable item key (reorder and reword keep lineage) or an evidenced
  `supersedes_item_key`. Identical text under a new key is `AMBIGUOUS_UNVERIFIED`. Supersession
  without evidence is refused (B1-16).

Integration of the new assignment into `PmService` / `assigned_pm_plan_id`: **BLOCKED / not
attempted**. Compatible rollout needs B2 authorization and the VAL-AM decision.

## 6. Tests
Commands (from `backend/`; dev deps were installed in the container because pytest was missing):
- `python -m pytest -q -p no:cacheprovider tests/test_pm_master_b1_mock.py` → **21 passed, 0 failed,
  0 skipped**.
- Baseline narrow regression, before the change → 326 passed, 0 failed.
- Full backend suite, after the change → **5,060 passed, 0 failed, 0 skipped** (947 warnings, 24m28s). The AM record baseline was 5,039; the +21 are the B1 tests.

Not run: frontend Vitest, typecheck, build, lint and Playwright. No frontend file changed.

B1 acceptance → tests: B1-01..B1-18 map 1:1 to `test_b1_01..test_b1_18`. The additional negatives are:
- `test_forged_master_publish_is_refused_even_with_every_legacy_capability`
- `test_negative_checks_no_e01_due_safety_or_outcome_changes`
- `test_negative_missing_meter_values_are_unknown_never_zero`

## 7. Not implemented (by design)
- B2 Work Order lifecycle and outcomes, Repair evidence linkage, Due / Unscheduled, Outstanding
  Subitems, E02/E03 thresholds and advisories, IoT, TEST/REAL or Google Sheets persistence, API
  routes and UI.
- No safety-critical classification, no Technician V2 toggle, no historical WO migration.

Mock activation firewall: nothing in `backend/app` imports the two new modules (asserted). Rollback
is deleting the four new files.

## 8. Recommendation
`B1 review status = GO_FOR_OWNER_CODE_REVIEW` (Mock only; never Production GO).

Open gates and Owner actions:
1. **VAL-AM:** decide which existing authority (if any) may publish the Master and assign Plans.
   Until then, writes stay fail-closed.
2. **Source:** authorize a local, read-only preview of `MAINTENANCE.xlsx` and confirm its real
   header names; the 260 / 1,146 / 49 / 235 / 13 / 38 accounting is UNVERIFIED until then.
3. Review and approve commit / push of this local candidate (nothing is committed).
4. B2 activation and the `assigned_pm_plan_id` rollout plan are separate approvals.
