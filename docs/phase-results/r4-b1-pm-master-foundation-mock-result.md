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

---

## Addendum — 2026-10-21: preservation commit and correction batch (RV-B1-01..06)

Sections 1–8 above are kept as the historic B1 candidate report. Where this addendum differs, it
supersedes them. In particular, the original publish path that accepted caller-built Sets and an
optional review list is replaced (RV-B1-02).

### A. Verified Git status
- **Preservation commit:** `90d4d0765fc9eee51206db8b60d88c94bed29e6b`, parent
  `753f389de7e3328d0104c1ede515714d664bad39`. It holds the original 4-file B1 candidate. It was
  committed and pushed once to the existing branch `origin/feature/r4-pm-master-b1-mock` under the
  Owner's preservation-only authorization, and the remote SHA was verified. It is not B1 acceptance.
- **Correction batch:** UNCOMMITTED. It is a local working-tree change on top of `90d4d07`,
  pending independent review. It is not committed and not pushed. No PR, merge or deployment.
- The correction touches only the same 4 files. No file was added or removed.

### B. Fact classes (kept distinct)
| Class | Content |
|---|---|
| Source facts, independently reviewed (not read in this environment) | Tab names and the partial header and enum examples in `SOURCE_COLUMNS`: `HOUR`/`KM`, `SOURCE_STANDARD`/`EMPTY_TEMPLATE`/`CANCELLED`, `MATCHED_PENDING_IMPLEMENTATION`/`PENDING_PM_PLAN`, and the CARRIER/CRANE/NOT_SEPARATED_IN_FORM sections. |
| UNVERIFIED | **FULL REAL HEADER INVENTORY UNVERIFIED.** Actual-source reconciliation **260 / 1,146 / 49 / 235 / 13 / 38** is UNVERIFIED, because `MAINTENANCE.xlsx` was not available, read, uploaded or committed. Real model aliases, real section meters, real item keys and real row counts are all unresolved. |
| Test-fixture facts (synthetic only) | The source-shaped fixture `source_workbook()` in the test file has 4 / 14 / 11 / 6 / 2 / 1 rows (standard / cycles / items / mapping / replacement policy / replacement items) plus 1 out-of-scope tab. These are not source counts. |
| Open gates | **VAL-AM OPEN:** every Master write (preview registration, review resolution, publish, assignment) is refused for every actor with `PM_MASTER_AUTHORITY_UNPROVEN`. Real-source validation is open. B2 and Production are not started and not authorized. |

### C. Findings
| Finding | Status | Correction |
|---|---|---|
| RV-B1-01 | FIXED (contract); real headers UNVERIFIED | New pure adapter `preview_maintenance_source` reads the reviewed real headers. Plan identity is the raw `source_sheet`; a Set is (sheet, `model_label_corrected`, `component_section`, `task_group`); an Item is only its source pointer `source_sheet!source_row`. `HOUR` → REVIEW `METER_COMPONENT_UNRESOLVED` (never guessed). `KM` → ODOMETER / VEHICLE is the only unit derivation, and it is a REVIEW point for the Owner. Raw form cells (`check_cell_raw` and the other two) are preserved raw and never mapped; a raw `35` → REVIEW. Every candidate keeps its raw cells and source coordinates. The old normalized `preview_source` is kept for its synthetic contract tests only and cannot be published. |
| RV-B1-02 | FIXED | `publish` takes no Sets and no review list. It rebuilds the candidate from a registered preview (`register_preview`; only the latest per source file is current), the matching `expected_source_digest`, and resolutions recorded with `record_review`. Each resolution is bound to one ledger `entry_id` of that preview, with an allowed outcome, valid values and substantive evidence; it is append-only, and a second resolution of the same entry is refused. Omitted, forged, stale, mismatched, unresolved and fake-reviewed proofs are refused before mutation. |
| RV-B1-03 | FIXED | `resolve_lineage`: an Item is RETAINED only with the same pointer and identical content. CONTINUES and DECLARED_NEW need an evidenced `LineageDecision`. Anything else is `AMBIGUOUS_LINEAGE` and refuses publish. Also refused: a predecessor outside the same previous Set, continued twice, still retained, a duplicate or unknown decision, weak evidence, and any lineage on a first revision. Decisions are stored on the revision. |
| RV-B1-04 | FIXED | Stored events are read-only mappings (`MappingProxyType`), and `audit()` returns read-only copies. |
| RV-B1-05 | FIXED | `set_assignment` requires `MockVehicleResolver`, which accepts only the in-memory Mock repository. Unknown or blank vehicles are refused, as are invalid assemblies and assemblies the model does not declare: CARRIER needs `CARRIER_ENGINE`, CRANE needs `CRANE_ENGINE` (UNVERIFIED mapping, fail closed). Nothing is created. |
| RV-B1-06 | FIXED | This addendum. |

### D. Tests (correction batch)
See the session correction report for the exact commands and counts of this run. The earlier
5,060-test full run belongs to the `90d4d07` candidate. It is not claimed as a rerun for this
correction unless the correction report states a new run.

### E. Round 2 — independent review verdict RV-B1-R2-01..04 (2026-10-21), UNCOMMITTED

The independent review of patch `bdbb24a0…` returned CHANGES REQUIRED. This round corrects only
the four blockers, on top of the same uncommitted correction, within the same four files. It
applies the Owner clarification: `source_sheet` is provenance, not a Plan ID or an Item ID, and
differing names are expected. Where this round differs from table C, it supersedes it; in
particular, the RV-B1-01 note that "Plan identity is the raw `source_sheet`" no longer holds.

| Finding | Status | Correction |
|---|---|---|
| RV-B1-R2-01 | FIXED for the contract; real joins UNVERIFIED | Planning tabs (`source_pm_cycles.source_sheet`) and inspection documents (`source_pm_items` / `source_pm_standard` `source_sheet`) are never equated. A Set is (planning tab, model, section, task group). It links to a document only through matched `vehicle_pm_mapping` rows with the same `source_plan` and `plan_model`. The document comes from `carrier_or_main_source_sheet` for CARRIER and NOT_SEPARATED_IN_PLAN, and from `crane_source_sheet` for CRANE. It must be a current `SOURCE_STANDARD`. Label differences are bridged only by explicit, evidenced PLAN/MODEL aliases supplied at `register_preview`; they are part of the digest. Refused as REVIEW: no evidence (SET_NOT_MAPPED), disagreeing rows (MAPPING_CONFIGURATION_CONFLICT, SET_DOCUMENT_AMBIGUOUS), and documents that are missing, not current or under review. |
| RV-B1-R2-02 | FIXED | Planning sections are CARRIER / CRANE / `NOT_SEPARATED_IN_PLAN`; form sections are CARRIER / CRANE / `NOT_SEPARATED_IN_FORM`; raw labels are kept. Mapping `component_configuration` gives the source topology: CARRIER_AND_CRANE → DUAL, NOT_SEPARATED_IN_PLAN → SINGLE, UNKNOWN → UNKNOWN (never guessed). Under the Owner rule (IoT addendum A/H1), HOUR resolves to ENGINE_HOUR as follows: DUAL CARRIER → CARRIER_ENGINE, DUAL CRANE → CRANE_ENGINE, SINGLE → one CARRIER_ENGINE (no CRANE_ENGINE invented; PTO is not an engine). This applies only when section and configuration agree; otherwise SECTION_CONFIGURATION_CONFLICT. An UNKNOWN configuration keeps HOUR in REVIEW. KM is the single vehicle odometer. No component, device or installation is created. |
| RV-B1-R2-03 | FIXED | Sets are keyed by plan, model, section and task group, and carry their mapped document. An Item is linked only to the Sets whose document, matching section and task group equal its own; two models that share Set "A" get only their own document's tasks. The derived SET_PENDING_REVIEW waiver is removed. A finding blocks exactly the Plans of the Sets its row links to (`plan_scope`); another model's Set can never clear it. |
| RV-B1-R2-04 | FIXED | Raw `35` handling depends on the field. In a column whose meaning is used, it is an AMBIGUOUS_RAW_35 REVIEW. In form action cells, URLs and other metadata, it is a non-blocking `RAW_35_PRESERVED_UNINTERPRETED` ledger note, with the raw value kept. Standard lifecycle (SOURCE_STANDARD / EMPTY_TEMPLATE / CANCELLED) is now counted independently of that note. No action, part, quantity or meter value is ever derived from it. |

Owner clarification, applied:
- No spare-part code, quantity or unit is created or populated.
- Corrected or completed standards can arrive later as a new registered preview and Master
  revision. Existing revisions and Work Order snapshots stay unchanged (B1-09 / B1-10).
- Cancelled, blank-template, ambiguous and unlinked rows stay in the ledger. Unlinked rows block
  no Plan.

Real-source status: **UNVERIFIED.** `MAINTENANCE.xlsx` was not available, and the connected Google
Sheet was not read. Reference reconciliation `reconcile_reference()` (cycles 260 = 80 / 107 / 73;
items 1,146 = 482 / 374 / 290; standards 49 = 44 / 4 / 1; mapping 235 = 183 / 52 with topology
130 single / 53 dual / 52 unknown; replacement 13 / 38) is implemented but reports MISMATCH on
synthetic data. The opt-in read-only test `test_r2_real_workbook_read_only_reconciliation`
(`MAINTENANCE_XLSX=/path pytest …`) was SKIPPED in this environment. The real alias set,
section-to-document joins and the 183-row join coverage remain UNVERIFIED.

Remaining gates: VAL-AM OPEN; real-source reconciliation UNVERIFIED; the Owner should confirm the
SINGLE → CARRIER_ENGINE convention and the KM → vehicle odometer rule; the CARRIER/CRANE
assignment guard still needs model engine roles, which are blank in the live Sheet; B2, Phase 8,
IoT and Production are not authorized. This round is UNCOMMITTED; it is not committed and not
pushed.

### F. Round 3 — independent review RV-B1-R3-01 / R3-02 (2026-10-21), UNCOMMITTED

The R2 patch (`b59710f9…`) was reviewed as CHANGES REQUIRED with two fail-closed defects. Both
were reproduced against the R2 code before being fixed. Same four files; still UNCOMMITTED; not
committed and not pushed.

| Finding | Status | Correction |
|---|---|---|
| RV-B1-R3-01 | FIXED | Every REVIEW entry now has a conservative `plan_scope`. **Item findings:** they block the Plans of the Sets the Item links to, plus every Plan whose verified (accepted, matched) mapping rows reference the Item's document. A mistyped group or section therefore still blocks the Plans that use that document. **Mapping-row findings:** they block the Plan the row names. A malformed row that names no Plan and is not PENDING_PM_PLAN falls under the global gate. **Cycle rows without a planning tab:** global gate. **Standard rows:** they block the Plans mapping that document; unselected documents block nothing. **Global gate:** a finding whose scope cannot be proven gets `GLOBAL_PLAN_SCOPE`, an unresolved-source gate that blocks every Plan until it is explicitly excluded with evidence. **Not over-blocked:** valid PENDING_PM_PLAN rows have no finding, and Items of unselected EMPTY_TEMPLATE/CANCELLED documents stay non-blocking. **Mapping order:** mapping evidence is now read before standards so document scopes are known. |
| RV-B1-R3-02 | FIXED | `RETAIN_RAW_UNINTERPRETED` is no longer an allowed resolution for any finding, so a semantic raw `35` can only be excluded; a corrected value must arrive in a new registered source preview. As defence in depth, `validate_candidate` refuses `35` in any projected Master field: Set `model_variant`, `section`, `set_code`, `independent_group`, `source_doc`, and Item `task_text`, `method`, `standard`. Raw evidence stays visible in the ledger, in the preview's `raw` cells and in the resolution record. Provenance-only form cells may still carry `35` in `raw`, and that is never projected. |

Test evidence for this round (Mock only):
- **New tests:** `test_r3_01_*` and `test_r3_02_*`. Both FAILED when run against the reviewed R2
  code (in a throwaway worktree with only a constant shim) and PASS on this code.
- **Updated expectations:** the synthetic Set `K35` (`group_rule` = raw `35`) is no longer
  published, and FIX-03 also refuses RETAIN on a raw-35 entry.
- **Focused B1 suite:** 35 passed, 1 skipped (the opt-in real-workbook test). See the session
  report for the full-suite run.

Real-source status:
- The reviewer independently compared the joins read-only against the connected MAINTENANCE Sheet:
  260/260 cycles and 1,146/1,146 items link through mapping evidence.
- That is the reviewer's evidence. **This code was NOT executed against the real workbook here**
  (not supplied), and real-workbook reconciliation of this Python preview remains UNVERIFIED.

Remaining gates are unchanged: VAL-AM OPEN; Owner confirmation of SINGLE → CARRIER_ENGINE and
KM → vehicle odometer; assembly guard pending model engine roles; no B2 / Phase 8 / IoT /
Production / TEST / REAL.
