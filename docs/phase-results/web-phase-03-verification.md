# Web/API Phase 3 — Post-Phase Verification Report

STATUS: AUDIT ONLY. No Phase 3 code was reimplemented, no Phase 4 work was
started, no frozen Phase 1/2 contract was changed, and no open governance
decision (D01–D04 or otherwise) was resolved as part of this verification.

Verified against branch `web/phase-03-inspection`, commit `e5f1a5e`
("Implement Web/API Phase 3: inspection, checklist revision, history, and
findings"), on top of `7e51f24` ("Resolve C02: give Equipment its own
approved status vocabulary" — the tip of the approved `main`/Phase 2 line).

**Process note:** at the start of this verification, the local checkout of
`web/phase-03-inspection` was one commit behind `origin` and contained no
Phase 3 code and no `web-phase-03-result.md` at all (only Phases 1–2). A
`git pull origin web/phase-03-inspection` fast-forwarded the branch to
`e5f1a5e`, which is the actual Phase 3 implementation commit. All findings
below are against that pulled commit.

Documents read in full before verifying, as required:
- `docs/project-governance/PROJECT_CROSS_SYSTEM_GUARDRAILS_EN.txt`
- `docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`
- `docs/project-governance/CROSS_SYSTEM_CONTRACT_FREEZE_CHECKPOINTS_EN.txt`
- `docs/claude-prompts/web-api/00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`
- `docs/claude-prompts/web-api/00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt`
- `docs/claude-prompts/web-api/03_PHASE3_INSPECTION_CHECKLIST_HISTORY_EN.txt`
- `docs/phase-results/web-phase-01-result.md`, `web-phase-01-verification.md`
- `docs/phase-results/web-phase-02-result.md`, `web-phase-02-verification.md`
- `docs/phase-results/web-phase-03-result.md`

Plus direct inspection of every backend/frontend file the Phase 3 commit
added or changed, and re-execution of every automated test suite in this
session (exact commands/results in Section O).

---

## A. Requirement Traceability

| Requirement (Phase 3 scope) | Implemented | Evidence file/module | Automated test evidence | Manual test needed | Notes |
|---|---|---|---|---|---|
| Revision-controlled checklist master/revision/item | YES | `backend/app/domain/checklist.py` | `test_mock_repository_inspection.py` (revision isolation/immutability tests) | No | |
| Effective-date auto-selection of active revision, no manual picker | YES | `Repository.get_active_checklist_revision`, `MockRepository.get_active_checklist_revision` | `test_active_checklist_selection_picks_latest_effective_revision`; `GET /checklists/active` tests | No | Selects latest `(effective_date, revision_number)` ≤ today |
| Checklist item fields (title, point, ref image, method, standard, instruction, frequency, display order) | YES | `ChecklistItem` model | `test_inspections_api.py` (checklist read tests) | No | `method`/`standard`/`instruction`/`frequency`/reference image all blank in seed data — see Section G |
| PASS/FAIL/N/A | YES | `InspectionResultValue` enum, English codes; Thai labels in `frontend/src/lib/labels.ts` | `test_submit_inspection_all_pass_for_vehicle`, `test_submit_inspection_accepts_na`, `ChecklistItemCard.test.tsx` | No | |
| Remark | YES | `InspectionItemResult.remark` / `NewInspectionItemInput.remark` | see Section C | No | See Section C — remark-required-on-FAIL is unconditional, flagged below |
| Inspection evidence photo | YES | `Attachment`/`AttachmentPurpose.INSPECTION_EVIDENCE`, `POST /attachments` | `test_submit_inspection_fail_creates_finding` (with evidence), Playwright `setInputFiles` test | No | |
| Required-photo-on-fail rule | YES | `ChecklistItem.required_photo_on_fail` (per-item, default `False`) | `test_submit_inspection_fail_without_required_photo_is_rejected` | No | Correctly item-configurable, not a global hardcode — see Section C |
| Immutable inspection history | YES | `InspectionDetail`/`InspectionHeader`/`InspectionItemResult`; no update/void endpoint anywhere | `test_new_checklist_revision_does_not_mutate_a_previously_submitted_inspection` | No | See Section E |
| Inspection header/results | YES | `InspectionHeader`, `InspectionItemResult` | API + repo tests | No | |
| Counter snapshot when available | NOT_APPLICABLE | — | — | No | No meter/counter fields exist on `Vehicle`/`Equipment` yet (IoT phases not implemented); nothing to snapshot. Not a Phase 3 gap. |
| Normal abnormal finding | YES | `InspectionFinding`, `FindingStatus.OPEN` | `test_submit_inspection_fail_creates_finding` | No | |
| Critical-item rule integration point | YES (architecture only, correctly inert) | `is_critical` on item/result/finding, always `False` in seed data | `test_equipment_status.py`-style pattern N/A; verified by seed data read | No | See Section B (D03) |
| Thai inspection UI | YES | `InspectionFormPage`, `ChecklistItemCard`, `InspectionDetailPage`, `InspectionHistoryPage` | Vitest + Playwright (Thai strings asserted) | Yes — native-speaker read-through | |
| History detail | YES | `InspectionDetailPage`, `GET /inspections/{id}` | `InspectionDetailPage.test.tsx` | No | |
| Attachment integration via StorageProvider | YES | `InspectionService.upload_attachment` → `StorageProvider.save`; no binary in repository | `test_inspections_api.py` (attachment upload/download round-trip) | No | See Section M for a gap in MIME/size validation |
| Reference image vs evidence photo kept separate | YES | `AttachmentPurpose` discriminator; service rejects wrong-purpose evidence IDs | `test_submit_inspection_unknown_evidence_attachment_is_rejected`; `ChecklistItemCard.test.tsx` "renders the reference image separately from evidence photos" | No | See Section H |
| Same engine for VEHICLE and EQUIPMENT | YES | One `InspectionService`/`InspectionFormPage` branches only on route param | Playwright "the same inspection engine supports workshop equipment" | No | |
| Correct checklist loads automatically (no manual revision choice) | YES | `GET /checklists/active?asset_type=` | Playwright "ตรวจเช็ค loads the active checklist automatically..." | No | |
| PASS/FAIL/N/A persist | YES | as above | as above | No | |
| Required FAIL details validate | PARTIAL — see Section C | `inspection_service.py` FAIL branch | `test_submit_inspection_fail_without_remark_is_rejected`, `..._without_required_photo_is_rejected` | No | Remark-required is unconditional/hardcoded rather than sourced from an explicit scope line — flagged, not blocking |
| Submitted history immutable | YES | no update/void/supersede endpoint at any layer | Section E tests | No | |
| Historical result retains old revision | YES | item text/is_critical snapshotted at submission | `test_new_checklist_revision_does_not_mutate_a_previously_submitted_inspection` | No | |
| FAIL creates finding per rule | YES | as above | `test_submit_inspection_fail_creates_finding` | No | |

**Traceability verdict:** every mandatory Phase 3 scope item is present and
evidenced by a real, re-executed automated test. The one PARTIAL is the
FAIL-remark rule's textual sourcing, covered in Section C — it does not
mean the feature doesn't work; it means its origin as a permanent rule is
under-documented.

---

## B. Open-Decision / Guessing Audit

| Decision ID | Current implementation behavior | Permanent rule or placeholder? | Explicitly approved? | Risk | Required action |
|---|---|---|---|---|---|
| **D01 — Checklist Assignment Rules** | Exactly one active `ChecklistMaster` per `AssetType` (VEHICLE, EQUIPMENT); `get_active_checklist_revision(asset_type)` returns the first checklist matching that `asset_type`. No asset/model/type → checklist matrix. | Explicitly documented placeholder (module docstring in `checklist.py`, seed_data.py comments, result report Section 14) — "the narrowest placeholder that does not require an assignment policy." Reversible: see Section D of this report for the structural check. | NO — and correctly not claimed as approved. | Low today (only one checklist family exists per type, so D01's own stated trigger — "before multiple checklist families" — has not occurred). Real risk is only if a future phase silently keeps using `next(... asset_type ...)`'s first-match semantics once a second checklist family per type is added without first resolving D01. | None for Phase 3 itself. Before any future phase adds a second checklist family per asset type (e.g., per vehicle model), D01 must be answered and `get_active_checklist_revision`/`GET /checklists/active` extended with an explicit selector — see Section D. |
| **D02 — Daily vs Weekly Scheduling** | No automatic due/scheduling logic anywhere. `ChecklistItem.frequency: str \| None` exists as free-text metadata, left unset by every seed item, and is never read by any code path. "ตรวจเช็ค" is a fully manual, on-demand action. | Interface/metadata-only placeholder, correctly inert. | N/A — nothing was decided; nothing needed deciding for this scope. | None. | None. |
| **D03 — Critical Inspection Item Rules** | `is_critical: bool = False` on `ChecklistItem`, snapshotted onto `InspectionItemResult` and `InspectionFinding`. Every seed item is `is_critical=False`. No code path computes or infers criticality from anything. | Architecture-only placeholder; correctly never populated with invented data. | N/A — no source data exists, none was fabricated. | None found. | None for Phase 3. Do not let a future phase set `is_critical=True` without an explicit, named, approved source. |
| **D04 — Inspection Correction Policy** | `POST /api/v1/inspections` (create) + two `GET` routes are the entire write/read surface. No update, void, supersede, or delete endpoint exists at the API, service, or repository layer. | Deliberately left unresolved — the "strictest possible reading" of immutability, per the result report. | N/A — correctly not decided; nothing here needed the user's input because nothing was built that would require it. | None found — no half-built correction mechanism exists to create ambiguity later. | None for Phase 3. D04 must still be answered before any correction/void/supersede feature is built. |

**Also checked, already-approved decisions reused without change:**
- **C02 (Equipment status vocabulary)** — `EquipmentOperationalStatus` is
  read only for display on `EquipmentDetailPage`; no inspection code
  reads or writes vehicle/equipment operational status. Compliant.
- **A10 (`/api/v1` partially frozen)** — new routes follow the existing
  prefix/error-envelope convention; no compatibility-policy question was
  reached. Compliant.
- **A01 (transaction ID strategy)** — see Section L.
- **M07 (file upload limits/MIME/malware scanning)** — see Section M; this
  is the first phase to actually ship an upload endpoint, and the
  pre-condition Phase 1's verification flagged for exactly this moment
  was not carried forward. See Section M for the finding.

**Conclusion for Section B:** D01–D04 were correctly left open, with
placeholders that are documented as temporary and are structurally
reversible (verified independently in Section D, not just taken on the
report's word). No decision in the D-series (or C-series) was silently
resolved as a permanent business rule. **One adjacent, non-D-series issue
was found and is carried into the final verdict — see Section C.**

---

## C. Special Audit — FAIL Validation Rules

Checked every "FAIL requires X" / "N/A requires X" / "any result requires
photo" style rule against the approved Phase 3 spec, the baseline, and the
open-decisions register, per the task's explicit instruction not to assume
a reasonable-sounding rule is approved.

### Rule 1 — "FAIL requires a non-empty remark" (unconditional, every item)

**Enforced at:**
- Backend: `backend/app/domain/inspection_service.py:177-184` —
  `if answer.result == FAIL: if not answer.remark or not answer.remark.strip(): raise ApiError(...)`.
  This runs for **every** checklist item, with no per-item flag to turn it
  off (unlike the photo rule below).
- Frontend: `frontend/src/pages/InspectionFormPage.tsx:143-148` (client-side
  pre-submit check, Thai message "กรุณาระบุหมายเหตุเมื่อผลตรวจไม่ผ่าน") and
  `frontend/src/components/ChecklistItemCard.tsx:92` (label "หมายเหตุ
  (จำเป็นเมื่อไม่ผ่าน)" — "remark (required when failed)").
- Tests asserting/relying on this exact behavior: backend
  `test_inspections_api.py::test_submit_inspection_fail_without_remark_is_rejected`;
  frontend `InspectionFormPage.test.tsx` ("FAIL without a remark is blocked
  client-side").

**Source check:**
- `OPEN_DECISIONS_REGISTER_EN.txt` — no D-series (or other) entry names a
  remark-on-FAIL requirement at all; it is simply not a registered open
  decision, so it was not "resolved" in the sense Section B checks, but it
  also has no register entry that authorizes it.
- `03_PHASE3_INSPECTION_CHECKLIST_HISTORY_EN.txt` SCOPE list explicitly
  names **"required-photo-on-fail rules"** as its own bullet, but does
  **not** separately name a required-remark-on-fail rule.
- Its ACCEPTANCE TESTS list only "required FAIL details validate" —
  worded generally enough to plausibly cover a remark rule, but not an
  explicit, unambiguous mandate.
- Baseline `00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt`, MOBILE INSPECTION
  section: *"If FAIL is selected: required remark/photo rules should
  appear immediately"* — this presupposes that *some* required
  remark/photo rule exists and only prescribes how it should surface in
  the UI; it does not itself mandate that remark is unconditionally
  required for every item.
- Baseline section 8 lists `remark` as one of several fields an inspection
  item "may contain" — not as mandatory.

**Verdict on Rule 1:** this is a real, hardcoded, permanent business rule
(applied identically to every checklist item, for both VEHICLE and
EQUIPMENT, with no source-data-driven per-item toggle) that has only
indirect, generally-worded textual support, not an explicit unambiguous
mandate, and is not tied to any OPEN_DECISIONS_REGISTER entry or a
recorded user approval. The Phase 3 result report's own "Open Decisions
Encountered" section (Section 13) does not disclose this as a decision it
made — it is presented as a given, not flagged for confirmation. This
matches the audit brief's warning almost exactly ("Do not assume a
reasonable operational rule is approved").

This is a **moderate, narrow finding**, not a fabricated technical/safety
rule: it does not invent a standard, a critical-item classification, or a
scheduling rule, and it does not corrupt data, mutate history, or violate
a frozen contract. It is best read as basic data-quality validation
("a FAIL needs *some* stated reason") rather than an invented operational
policy — but per the audit's explicit instruction, it must still be
surfaced rather than passed over, and it is why this report's final
verdict is **PASS WITH KNOWN LIMITATIONS** rather than plain PASS. See
Section Q.

**Required action:** obtain explicit user confirmation that "FAIL always
requires a non-empty remark, for every item, with no exception" is the
intended permanent rule; if the user wants this to be
source-data-configurable (the same way `required_photo_on_fail` already
is per item), that requires a small, additive schema change
(`ChecklistItem.required_remark_on_fail: bool = True`, defaulting to the
current behavior) rather than a redesign.

### Rule 2 — "FAIL requires an evidence photo" (per-item, `required_photo_on_fail`)

**Enforced at:** `inspection_service.py:185-191`, only when the specific
`ChecklistItem.required_photo_on_fail` flag is `True` for that item.

**Source check:** explicitly named in the Phase 3 SCOPE list
("required-photo-on-fail rules"), and explicitly architected as
source-data-driven (defaults to `False`; seed data sets it `True` on
exactly one item per checklist purely to exercise the mechanism — see
Section G for whether that placeholder choice itself is a concern, which
it is not, since it carries no invented technical/safety meaning).

**Verdict on Rule 2:** explicitly authorized by the Phase 3 spec and
correctly implemented as a configurable, off-by-default, per-item flag —
**no finding**.

### Rule 3 — "N/A requires remark", "any result requires photo", "cannot submit without any photo"

**Checked:** no such rules exist anywhere in `inspection_service.py`,
`ChecklistItemCard.tsx`, or the test suite. `N/A` and `PASS` results are
accepted with no remark/photo requirement of any kind
(`test_submit_inspection_accepts_na`, `test_submit_inspection_all_pass_for_vehicle`).

**Verdict:** no finding — no additional unapproved rule was found beyond
Rule 1 above.

---

## D. Special Audit — Checklist Assignment Placeholder (D01)

Verified structurally, not merely by reading the report's claim:

- **Repository/service architecture extensibility:** `get_active_checklist_revision(asset_type: AssetType)` on both `Repository` (abstract) and `MockRepository` takes only `asset_type`. Adding a second selector (e.g., `model_id: str | None = None`) is an additive parameter change, not a breaking one — existing callers (the current API route, which passes only `asset_type`) continue to compile/work unchanged if the new parameter defaults to `None`. **Not a blocking defect.**
- **No uniqueness constraint permanently limits the system to one checklist per asset type.** `MockRepository._checklists` is a plain `dict[str, ChecklistMaster]` keyed by `checklist_id`, not by `asset_type` — nothing prevents inserting a second `ChecklistMaster` with the same `asset_type` today; the only reason exactly one exists per type is that seed data only defines one. The current selection logic (`next(... c.asset_type == asset_type ...)`, first match) would need to change to pick a specific one once a second exists per type, but this is an implementation detail inside one function, not a schema-level constraint. The declared Google Sheets schema (`schemas.py`) likewise has no `UNIQUE(asset_type)`-style constraint — it maps by header name only. **Not a blocking defect.**
- **No API contract makes future multiple checklist families impossible.** `GET /api/v1/checklists/active?asset_type=` can gain an additional optional query parameter later without breaking existing callers (this is exactly the same additive-extension pattern Phase 1/2 already used repeatedly for `Repository`). **Not a blocking defect.**
- **No frontend assumes permanently that only one checklist can exist.** `InspectionFormPage` only calls `GET /checklists/active?asset_type=X` and renders whatever comes back; it has no hardcoded checklist ID, no UI text claiming "there is only one checklist," and would work unchanged if the backend later resolved D01 by returning a different checklist based on additional (currently absent) request context. **Not a blocking defect.**
- **Placeholder is clearly marked as temporary/development behavior.** Confirmed in three independent places: the `checklist.py` module docstring ("GOVERNANCE NOTE... this module therefore does not encode a checklist-assignment matrix"), `seed_data.py`'s inline comments, and — importantly — the **user-facing Thai checklist names themselves** ("ข้อมูลตัวอย่างชั่วคราวสำหรับพัฒนา/ทดสอบระบบ" = "temporary example data for development/testing system"), so even an ordinary user looking at the checklist name sees it is not real content. This is stronger disclosure than most placeholder implementations provide.

**Verdict for Section D: no blocking architecture defect.** D01's
placeholder is genuinely reversible and additive to extend, and is
disclosed at both the code and UI level, not just in the phase report's
prose.

---

## E. Checklist Revision / History Integrity

| Check | Result | Evidence |
|---|---|---|
| Stable checklist identity | YES | `ChecklistMaster.checklist_id` (`CHK-0001`/`CHK-0002`), never regenerated |
| Immutable revision identity | YES | `ChecklistRevision` has no update path anywhere in the repository interface |
| Old revisions remain readable | YES | `test_old_checklist_revision_remains_readable_after_a_newer_one_becomes_active` — re-run, passed; independently re-read the test logic: it writes a second revision directly into the mock store, confirms it becomes active, then confirms `GET /checklists/{id}/revisions/REV-0001` is still byte-for-byte the original |
| Submitted inspection retains exact checklist revision used | YES | `InspectionHeader.revision_id`/`revision_number` stored at submission; `InspectionItemResult` additionally snapshots `title`/`inspection_point`/`method`/`standard`/`instruction`/`is_critical` — a stronger guarantee than a revision reference alone |
| Later checklist revision cannot mutate historical submission | YES | `test_new_checklist_revision_does_not_mutate_a_previously_submitted_inspection` — re-run, passed; independently re-read: writes `REV-0099` with the *same item_id* and a changed title, then confirms the previously submitted inspection's stored title and `revision_id` are unchanged |
| Historical item text/snapshot reconstructable | YES | same snapshot fields as above, returned by `GET /inspections/{id}` |
| Item order retained | YES | `sequence` field on both `ChecklistItem` and `InspectionItemResult`; submission code explicitly iterates `sorted(checklist_detail.items, key=lambda i: i.sequence)` |
| Result history not overwritten | YES | `MockRepository.create_inspection` only ever inserts into `self._inspections[inspection_id]`; no code path re-assigns an existing key |
| No spreadsheet row-number identity | YES | All IDs are prefixed sequential opaque strings generated by the repository (`INS-`, `RES-`, `FND-`, `ATT-`, `CHK-`, `REV-`, `ITM-`); Google Sheets schema maps by header name only (`schemas.py`) |
| No update endpoint edits a submitted inspection in place | YES | `backend/app/api/v1/inspections.py` defines exactly `POST /inspections`, `GET /inspections`, `GET /inspections/{id}` — no `PATCH`/`PUT`/`DELETE` on any inspection path |
| D04 remains unresolved only for correction/void/supersede, not by making history mutable | YES | Confirmed above — the absence of a correction feature is total (no partial/half-built mutation path exists anywhere to create ambiguity) |

**No defect found.** This section's guarantees were re-verified by reading
the actual test bodies and repository code, not by trusting the phase
report's prose summary.

---

## F. Result / Finding Behavior

| Check | Result | Evidence |
|---|---|---|
| PASS accepted | YES | `test_submit_inspection_all_pass_for_vehicle` |
| FAIL accepted | YES | `test_submit_inspection_fail_creates_finding` |
| N/A accepted | YES | `test_submit_inspection_accepts_na` |
| Stable English backend codes | YES | `InspectionResultValue.PASS/FAIL/NA`, `FindingStatus.OPEN`, error codes (`NO_ACTIVE_CHECKLIST`, `CHECKLIST_REVISION_NOT_FOUND`, `ATTACHMENT_NOT_FOUND`, `INSPECTION_NOT_FOUND`, reused `VEHICLE_NOT_FOUND`/`EQUIPMENT_NOT_FOUND`) |
| Thai UI labels | YES | `frontend/src/lib/labels.ts`: `inspectionResultLabel` (ผ่าน/ไม่ผ่าน/ไม่เกี่ยวข้อง), plus new error-code Thai messages |
| FAIL creates/links abnormal finding as required | YES | `InspectionFinding.result_id` links back to the specific `InspectionItemResult`; `test_submit_inspection_fail_creates_finding` asserts the link |
| Repair workflow was NOT implemented | YES | Repo-wide grep found zero repair domain code — only forward-looking comments in docstrings (`asset.py`, `inspection.py`, `inspection_service.py`, `FormField.tsx`) referencing a *future* Phase 4 |
| FAIL does not automatically create a Repair order | YES | No such code path exists; `FindingStatus` has a single member (`OPEN`) by design, with no conversion method |
| Finding identity/history is stable | YES | `finding_id` sequential opaque string (`FND-NNNN`), created once, never mutated |
| No Critical-item behavior was invented | YES | `is_critical` is `False` everywhere in seed data; no code infers it from anything |
| No automatic safety escalation was invented | YES | No alert/severity code path reads `is_critical`; A06 (alert severity model) is untouched |

**No defect found.**

---

## G. Source Data / Placeholder Audit

Read `seed_data.py`'s checklist section in full (`backend/app/repositories/mock/seed_data.py:185-260`).

| Check | Result |
|---|---|
| Unmistakably development/example data | YES — checklist names literally say "(ข้อมูลตัวอย่างชั่วคราวสำหรับพัฒนา/ทดสอบระบบ)" = "(temporary example data for development/testing system)", visible in the UI itself, not just in code comments |
| Does not look like approved company content | YES — item titles are "รายการตรวจสอบตัวอย่างที่ N" ("Example inspection item N"), generic and numbered, not domain-specific crane/equipment terminology |
| No invented standards | YES — `standard` field is `None` for every seed item |
| No invented limits | YES — no numeric threshold/limit fields exist on `ChecklistItem` at all |
| No invented inspection methods | YES — `method` field is `None` for every seed item |
| No invented safety criteria | YES — nothing resembling a safety criterion appears anywhere in seed data |
| No real item classified as critical | YES — `is_critical=False` on every seed item |
| Not presented as authoritative operational data | YES — same evidence as "unmistakably development/example data" above; a Thai-reading user opening the checklist sees it is example/dev data, not a real inspection standard |
| Blank/unknown source fields stay blank | YES — `inspection_point`, `method`, `standard`, `instruction`, `frequency`, `reference_image_attachment_id` are all `None`, never defaulted to a fabricated value |

**No defect found.** This is a strong result: the placeholder data
discloses its own nature in the rendered Thai UI text, not merely in
source comments a non-technical reviewer would never read.

---

## H. Reference Image vs Evidence Image

| Check | Result | Evidence |
|---|---|---|
| Separate metadata/purpose | YES | `AttachmentPurpose.CHECKLIST_REFERENCE_IMAGE` vs `INSPECTION_EVIDENCE`, enforced at write time (`upload_attachment`) and cross-checked at submission time (an evidence ID pointing to a reference-purpose attachment, or vice versa, is rejected — `test_submit_inspection_unknown_evidence_attachment_is_rejected`) |
| Separate storage reference meaning | YES | Both share the same `Attachment` shape but `purpose` is a required discriminator; nothing merges the two concepts into one field |
| No binary data stored directly in DB/Google Sheets | YES | `Attachment.storage_ref` is a string; actual bytes only ever touch `StorageProvider.save/read`; declared Google Sheets `attachments` tab schema stores metadata columns only |
| StorageProvider abstraction used | YES | `InspectionService.upload_attachment`/`read_attachment_bytes` call only `self._storage: StorageProvider`, never a concrete implementation |
| Historical evidence linked to the submitted inspection | YES | `InspectionItemResult.evidence_attachment_ids: list[str]`, immutable once created |
| Frontend clearly distinguishes the two | YES | `ChecklistItemCard.tsx`: reference image rendered above the PASS/FAIL/N/A controls under caption "ภาพอ้างอิง (ตัวอย่างจุดตรวจ)"; evidence photos rendered only inside the FAIL-only block under caption "รูปถ่ายหลักฐาน" — verified by `ChecklistItemCard.test.tsx`'s dedicated separation test |

**No defect found.**

---

## I. Vehicle / Equipment Asset Integrity

| Check | Result | Evidence |
|---|---|---|
| Inspection supports VEHICLE | YES | `/vehicle/:vehicleId/inspect` route, `AssetType.VEHICLE` path |
| Inspection supports EQUIPMENT | YES | `/equipment/:equipmentId/inspect` route, `AssetType.EQUIPMENT` path |
| Shared asset reference does not merge identities | YES | `InspectionService._require_asset` branches to `get_vehicle`/`get_equipment` and preserves the distinct `VEHICLE_NOT_FOUND`/`EQUIPMENT_NOT_FOUND` codes rather than a merged "asset not found" |
| `vehicle_master`/`equipment_master` remain separate | YES | Unchanged from Phase 2 — no schema merge, no Phase 3 code touches `Vehicle`/`Equipment` models |
| Controlled 404 for invalid asset ID | PARTIAL — see finding below | `test_submit_inspection_for_unknown_vehicle_returns_controlled_404`/`..._equipment_...` (backend, at submit time) confirm the API is safe; the *inspection form page itself* does not show an immediate 404 for a nonexistent asset before submission |
| Asset type mismatch rejected | YES | `_require_asset` looks up strictly by the asset type in the request; a `VEHICLE` submission for an `EQP-` ID would fail `get_vehicle(asset_id) is None` → `VEHICLE_NOT_FOUND`, since equipment IDs are never present in the vehicle table (Phase 2 invariant, still intact) |
| `EquipmentOperationalStatus` remains separate from Vehicle's | YES | Inspection code never reads/writes either; both remain Phase 2's separate enums |
| Permanent QR routes unchanged | YES | `App.tsx`: `/vehicle/:vehicleId` and `/equipment/:equipmentId` route elements are byte-for-byte the Phase 2 routes; new inspection routes are separate nested paths (`/vehicle/:vehicleId/inspect`, `/vehicle/:vehicleId/inspections`) |
| Inspection/checklist IDs do not replace permanent QR identity | YES | No inspection/checklist ID appears anywhere in the `/vehicle/{id}` or `/equipment/{id}` path pattern |

**Finding (minor, non-blocking):** `InspectionFormPage.load()`
(`frontend/src/pages/InspectionFormPage.tsx:43-79`) fetches the checklist
and the asset in parallel; if the checklist fetch succeeds but the asset
fetch fails (e.g., a user navigates directly to
`/vehicle/VEH-9999/inspect` for a vehicle that does not exist), the code
does **not** show an error state — it silently falls back to using the raw
asset ID as the display label and still renders the full checklist form.
The user can fill out the entire checklist; only at submission time does
the backend correctly reject it with `VEHICLE_NOT_FOUND`/`EQUIPMENT_NOT_FOUND`
(422/404, verified by the backend tests above). **Data integrity is not at
risk** — no inspection can actually be created for a nonexistent asset —
but this is a UX gap relative to the "controlled 404 for invalid asset ID"
expectation applied to the inspection entry point specifically (Vehicle/
Equipment Detail pages themselves already show a correct 404, per Phase
2, unaffected by this finding). Recommend: check the asset fetch result in
`load()` and render `ErrorState` if it fails, mirroring the pattern
already used in `VehicleDetailPage`/`EquipmentDetailPage`.

---

## J. Daily / Weekly Scheduling Audit (D02)

Confirmed no autonomous behavior of any kind was introduced:
- No weekly weekday, week boundary, or daily cutoff time exists anywhere.
- No code path checks "has this been inspected today/this week."
- No overdue/missed/carry-forward logic exists.
- `frequency` exists only as an unread, unset `str | None` field — grepped
  the entire `backend/app` and `frontend/src` trees for reads of
  `.frequency`; the only occurrences are the field's own definition
  (`ChecklistItem`), its response-schema mirror
  (`ChecklistItemResponse.frequency`), and its (always-`None`) seed value.
  Nothing branches on its value.

**No defect found.**

---

## K. API / Architecture Review

| Check | Result | Evidence |
|---|---|---|
| `/api/v1` convention | YES | All 7 new routes registered under the existing `api_v1_router` |
| Common error envelope | YES | `ApiError` raised throughout `InspectionService`; same `{error:{code,message,details,request_id}}` shape as Phase 1/2, `details` additionally carrying structured validation info (`missing_item_ids`, `unknown_item_ids`, `item_id`) for the FAIL/validation cases |
| Stable IDs | YES | See Section L |
| Timezone-aware timestamps | YES | `InspectionHeader.submitted_at`, `Attachment.uploaded_at`, `ChecklistRevision.created_at` all use the existing `utc_now()` convention |
| English backend/domain codes, Thai UI | YES | Confirmed throughout Sections A/F |
| Repository abstraction | YES | `InspectionService` depends only on `Repository`/`StorageProvider` ABCs |
| StorageProvider abstraction | YES | See Section H |
| Browser does not access Google Sheets directly | YES | No Google API code in `frontend/` |
| Browser does not access ESP32 directly | YES (trivially) | No such code path exists in this phase |
| Backend remains authoritative | YES | All FAIL/remark/photo/finding rules live in `InspectionService`; frontend duplicates the same checks only as pre-submit UX (still re-validated server-side, confirmed by the 422 tests) |
| MockRepository works locally | YES | Full in-memory implementation, 72/72 backend tests pass with `DATA_REPOSITORY=mock` |
| GoogleSheetsRepository stays behind repository boundary | YES | `InspectionService` never imports a concrete repository class |
| PostgreSQL migration remains feasible | YES | No code path anywhere depends on dict/in-memory semantics beyond the `MockRepository` implementation itself; the `Repository` ABC is what all callers depend on |
| No Phase 1/2 frozen contract changed without approval | YES, with one file list below | |

**Approved prior-phase files touched by Phase 3, and why:**

| File | Change | Assessment |
|---|---|---|
| `backend/app/repositories/base.py` | +8 new abstract methods (checklist/attachment/inspection) | Additive only — `mode`, `check_ready`, and every Phase 2 vehicle/equipment method's signature is unchanged. This is exactly the extension pattern Phase 1's own docstring anticipated and Phase 2 already used once. |
| `backend/app/repositories/mock/repository.py`, `seed_data.py` | New in-memory storage + seed checklists | Additive — existing vehicle/equipment/status-history state and methods untouched (all 47 pre-existing backend tests re-run and pass unmodified as a subset of 72). |
| `backend/app/repositories/google_sheets/repository.py`, `schemas.py` | New declared tab schemas + controlled-error methods | Additive, same pattern as Phase 2's equivalent methods. |
| `backend/app/dependencies.py` | +`get_inspection_service` provider | Additive composition-root entry. |
| `backend/app/api/v1/router.py` | Registers the new inspections router | Additive. |
| `backend/pyproject.toml`, `requirements.txt` | +`python-multipart` dependency | Required by FastAPI for multipart file upload; does not affect existing routes. |
| `frontend/src/lib/apiClient.ts` | +`apiPost`, +`apiUpload` | Additive — `apiGet`/`apiPatch`'s behavior and `ApiError`/`ApiResult<T>` shapes are unchanged (confirmed by reading `performRequest`'s shared implementation). |
| `frontend/src/lib/types.ts`, `labels.ts` | +inspection/checklist/attachment types and Thai labels | Additive. |
| `frontend/src/App.tsx` | +5 new routes | The existing `/vehicle/:vehicleId` and `/equipment/:equipmentId` route elements are unchanged; new routes are separate nested paths. |
| `frontend/src/pages/VehicleDetailPage.tsx`, `EquipmentDetailPage.tsx` | +"ตรวจเช็ค"/"ประวัติการตรวจเช็ค" links (one `Card` block each) | Verified via direct diff (see below) — genuinely minimal, additive; one pre-existing sentence was edited only to remove the now-redundant mention of inspection from a "coming in a later phase" placeholder note, which is a correct, intentional edit, not scope creep. |
| `frontend/src/index.css` | +`.checklist-item-card*`/`.result-button*` rules | Additive on top of frozen `Card`/`FormField`/`.sticky-actions`/`--tap-target` primitives; no existing rule's value was changed. |

**No defect found** in this section beyond the Section C/I/M findings
already noted.

---

## L. Data Integrity / ID Strategy

| Identifier | Scheme | Stable? | Row-number-based? |
|---|---|---|---|
| `checklist_id` | `CHK-NNNN` (seed-fixed) | YES | NO |
| `revision_id` | `REV-NNNN` (seed-fixed) | YES | NO |
| `checklist_item_id` | `{prefix}-NNNN` (seed-fixed) | YES | NO |
| `inspection_id` | `INS-NNNN`, in-process sequence in `MockRepository` | YES within a process; not yet a cross-storage opaque strategy | NO |
| `inspection_result_id` | `RES-NNNN`, same pattern | YES | NO |
| `finding_id` | `FND-NNNN`, same pattern | YES | NO |
| `attachment_id` | `ATT-NNNN`, same pattern | YES | NO |

None of these IDs are derived from a Google Sheets row position — the
declared Sheets schemas (`schemas.py`) map by header name only, matching
Phase 1/2's precedent.

**A01 cross-check:** `OPEN_DECISIONS_REGISTER_EN.txt` A01 (transaction ID
generation) is `TBD-BLOCKING`, explicitly naming `inspection_id`,
`attachment_id`, etc. as domains needing one consistent
backend-generated-opaque-string strategy. Phase 3 continues the exact
same **isolated, mock-only, simple sequential-counter convenience**
pattern Phase 2 already established for `VehicleStatusHistoryEntry.history_id`
(`STH-NNNN`) — Phase 2's own verification flagged that this ad hoc scheme
should not be silently treated as A01's final answer. Phase 3 does not
make this worse or harder to reverse: the ID *format* (`PREFIX-NNNN`) is
already the shape the register's own "Direction" line recommends
("backend-generated opaque string IDs"), and swapping the *generation
mechanism* (in-memory counter → UUID or DB sequence) later requires no
caller-visible change, since callers only ever treat these as opaque
strings. **This is an isolated, reversible continuation of an
already-disclosed pattern, not a new unapproved freeze of A01.**

**Frontend does not generate authoritative IDs** — confirmed:
`InspectionFormPage`/`ChecklistItemCard` never construct an ID; all IDs
used by the frontend originate from a repository response.

---

## M. Security / Secrets Review

| Check | Result | Evidence |
|---|---|---|
| No committed `.env` | CONFIRMED CLEAN | No new env-shaped file added by this commit |
| No credential JSON | CONFIRMED CLEAN | None added |
| No API key/token/password/private key | CONFIRMED CLEAN | None found in any new file |
| Unsafe path handling on file upload | CONFIRMED SAFE | `LocalFileStorageProvider._resolve` re-resolves every `storage_ref` against the configured root and rejects anything that escapes it; `storage_ref` itself is always `uuid4().hex + suffix` generated server-side — the client-supplied `filename` is used only to extract a suffix via `Path(filename).suffix`, never as a path component, so a filename like `../../etc/passwd` cannot cause traversal |
| Filename trust issues | LOW RISK | Same as above — filename is stored as metadata only (`Attachment.filename`) and never used to construct a filesystem path |
| Attachment metadata validation | GAP FOUND | See finding below |
| Content-type handling | GAP FOUND | See finding below |
| Development auth not represented as production auth | UNCHANGED, STILL CORRECT | `DEV_AUTH_MODE` guard from Phase 1 (`main.py`) is untouched; inspection routes use the same `get_current_context` dependency as every other route, no new auth bypass introduced |

**Finding (moderate, non-blocking for this dev-mode phase):**
`InspectionService.upload_attachment` (`inspection_service.py:77-99`)
accepts any `content_type` and any file size from the client, rejecting
only a fully empty body. `download_attachment`
(`inspections.py:167-173`) then echoes that same client-supplied
`content_type` back verbatim as the `media_type` of the HTTP response,
with no `Content-Disposition` header and no `X-Content-Type-Options:
nosniff`. Since `DEV_AUTH_MODE` currently grants every request a fixed
`ADMIN` context with no further authorization check (a pre-existing,
disclosed Phase 1/2 limitation, not introduced here), any user who can
reach the API today could upload a file with `content_type: text/html`
and arbitrary content, then have a browser render it inline if navigated
to `/api/v1/attachments/{id}/file` directly — a stored-content /
MIME-confusion risk. This is exactly the scenario
`OPEN_DECISIONS_REGISTER_EN.txt` **M07 (File Upload Limits / MIME /
Malware Scanning, TBD-BLOCKING before production file upload)** describes,
and Phase 3 is the **first** phase to ship a real upload endpoint —
`docs/phase-results/web-phase-01-verification.md` explicitly flagged this
exact moment ("track as a pre-condition for whichever phase adds the
first upload endpoint... do not let it silently inherit 'no limits' as a
permanent decision"). Phase 3's own Known Limitations section (Section 12
of the result report) does not mention this at all.

**Severity assessment:** bounded today because (a) this remains a local
development/mock environment with no production auth of any kind yet
(the same standing risk Phase 1/2 already disclosed for every write
endpoint), and (b) the frontend only ever renders these URLs inside
`<img>` tags, never navigates to them directly. It does **not** block
Phase 3 approval by itself, but it should be explicitly disclosed (which
this report now does) and addressed — at minimum an image-MIME allowlist
and a size cap, per M07 — before any real-user or production exposure,
consistent with M07's own stated trigger ("before production file
upload").

---

## N. Mobile / Responsive Review

All claims below were independently re-verified by re-running the full
Playwright suite in this session (Section O), not taken from the report.

| Viewport | Result |
|---|---|
| Smartphone portrait (375×667) | 15/15 tests passed (5 shell/vehicle-equipment groups + inspection.spec.ts) |
| Smartphone landscape (568×320) | 15/15 passed |
| Tablet portrait (768×1024) | 15/15 passed |
| Tablet landscape (1024×768) | 15/15 passed |
| Desktop (1280×800) | 15/15 passed |

Specific checks, verified by reading the actual assertions in
`frontend/e2e/inspection.spec.ts` and `ChecklistItemCard.tsx`/`index.css`,
not just their existence:
- No unintended horizontal scrolling after checklist load/submit — asserted per-test.
- PASS/FAIL/N/A buttons meet the 44px touch-target minimum — asserted via bounding-box measurement.
- Remarks are usable — a plain `<textarea>`, full-width per the frozen `.form-field` pattern.
- Reference image is understandable — rendered with a Thai caption above the result controls; correctly blank for all seed items (no fabricated image), so nothing misleading is shown.
- Evidence/photo control is mobile-friendly — `capture="environment"` opens the camera directly on a phone; upload/remove state visible inline.
- Sticky submit does not hide content — reuses the frozen `.sticky-actions` pattern already validated in Phase 1.
- Thai text wraps correctly — relies on the unchanged global `overflow-wrap`/`word-break` rules.
- No hover-only required action — all controls are `<button>`/`<input>`/`<textarea>`.
- Confirmation/error messages fit viewport — `form-field__error` role="alert" text, no modal/dialog overflow introduced by this phase.
- Vehicle and Equipment inspection entry points work on small screens — both `VehicleDetailPage`/`EquipmentDetailPage` action links tested by the Playwright suite.

**No defect found.**

---

## O. Automated Verification — Actually Re-Run in This Session

All commands below were executed directly in this session against the
pulled `web/phase-03-inspection` @ `e5f1a5e` checkout. None are copied
from the phase report without re-running.

**Backend — pytest**
```
$ cd backend && source .venv/bin/activate && pip install -e ".[dev]"
$ DATA_REPOSITORY=mock python -m pytest -q
72 passed, 6 warnings in 1.87s
```
(6 warnings are all pre-existing `HTTP_422_UNPROCESSABLE_ENTITY` Starlette
deprecation notices, same category present since Phase 1's `errors.py`;
not a new issue.) **Matches the phase report's claimed 72/72.**

**Frontend — unit/component (Vitest)**
```
$ cd frontend && npx vitest run
Test Files  15 passed (15)
     Tests  29 passed (29)
```
**Matches the phase report's claimed 29/29.**

**Frontend — typecheck**
```
$ npx tsc -b
(exit code 0 — PASSED)
```

**Frontend — lint**
```
$ npx oxlint
6 warnings, 0 errors — all react(set-state-in-effect), same pre-existing
category since Phase 1, now also on the 4 new inspection pages.
```

**Frontend — production build**
```
$ npm run build
dist/index.html                   0.43 kB │ gzip:  0.30 kB
dist/assets/index-*.css           9.46 kB │ gzip:  2.40 kB
dist/assets/index-*.js          299.35 kB │ gzip: 90.67 kB
✓ built in 487ms
```
**Matches the phase report's claimed sizes exactly.**

**E2E — Playwright, all 5 required viewport projects**
```
$ bash scripts/run_e2e_tests.sh
75 passed (47.1s)
```
Ran across `smartphone-portrait`, `smartphone-landscape`,
`tablet-portrait`, `tablet-landscape`, `desktop` (15 tests × 5 projects).
**Matches the phase report's claimed 75/75.**

**Summary**

| Suite | Result |
|---|---|
| Backend pytest | 72/72 passed |
| Frontend Vitest | 29/29 passed (15 files) |
| Frontend typecheck (`tsc -b`) | PASSED |
| Frontend lint (`oxlint`) | PASSED (6 pre-existing-category warnings, 0 errors) |
| Frontend production build | PASSED |
| Playwright e2e (5 viewports) | 75/75 passed |

No test was skipped, disabled, or hidden. No claimed result in the phase
report was found to be false — every number matches an independent
re-run in this session.

---

## P. Manual Acceptance Plan

Run with `./scripts/run_dev.sh` (or `run_backend.sh` + `run_frontend.sh`),
`DATA_REPOSITORY=mock`, at `http://127.0.0.1:5173`.

1. **Vehicle → ตรวจเช็ค**
   - Prerequisite: dev servers running.
   - Action: open `/vehicle/VEH-1046`, tap "ตรวจเช็ค".
   - Expected: navigates to `/vehicle/VEH-1046/inspect`; 5 placeholder items load automatically, titled "รายการตรวจสอบตัวอย่างที่ N", no revision picker anywhere.
   - Failure evidence: screenshot + Network tab for `GET /api/v1/checklists/active?asset_type=VEHICLE`.

2. **Equipment → ตรวจเช็ค**
   - Action: open `/equipment/EQP-0001/inspect` (or via the "ตรวจเช็ค" link on Equipment Detail).
   - Expected: 4 placeholder items load; identical workflow to vehicle.
   - Failure evidence: same as above for `asset_type=EQUIPMENT`.

3. **PASS result**
   - Action: on any item, tap "ผ่าน".
   - Expected: button highlights as selected; no remark/photo fields appear.
   - Failure evidence: screenshot of the selected state.

4. **FAIL result**
   - Action: tap "ไม่ผ่าน" on any item.
   - Expected: a remark textarea and an evidence-photo file input appear immediately in the same card, no navigation.
   - Failure evidence: screenshot before/after tapping.

5. **N/A result**
   - Action: tap "ไม่เกี่ยวข้อง" on any item.
   - Expected: accepted with no remark/photo requirement.
   - Failure evidence: screenshot + the eventual detail page showing "ไม่เกี่ยวข้อง".

6. **Remark entry**
   - Prerequisite: an item marked FAIL.
   - Action: type a remark, then try submitting with the remark left empty.
   - Expected: submission is blocked client-side with "กรุณาระบุหมายเหตุเมื่อผลตรวจไม่ผ่าน"; after entering text, the block clears.
   - Failure evidence: screenshot of the validation message; note whether it also blocks server-side by inspecting the Network tab (should never see a request fire while remark is empty).

7. **Evidence/photo attachment**
   - Prerequisite: an item marked FAIL, ideally the last item of a checklist (seed data marks exactly the last item of each checklist `required_photo_on_fail=True`).
   - Action: attach a photo via the file input (on a phone, confirm the camera opens directly).
   - Expected: an uploading indicator appears, then a thumbnail with a "ลบรูป" button; without a photo, submitting is blocked with "กรุณาแนบรูปถ่ายหลักฐานเมื่อผลตรวจไม่ผ่าน" for that specific item only.
   - Failure evidence: screenshot + `POST /api/v1/attachments` request/response from devtools.

8. **Reference image behavior**
   - Action: inspect any item's card.
   - Expected: no reference image appears for any seed item (none was supplied — this is correct, not a bug); confirm the position above the PASS/FAIL/N/A controls is simply absent rather than showing a broken image or fabricated placeholder image.
   - Failure evidence: screenshot + full page HTML.

9. **Submission**
   - Prerequisite: every item answered, FAIL items satisfying their remark/photo rules.
   - Action: tap "ส่งผลการตรวจ".
   - Expected: navigates to `/inspections/INS-...` showing the full immutable record.
   - Failure evidence: screenshot + the `POST /api/v1/inspections` request/response.

10. **History list**
    - Action: from `/vehicle/VEH-1046`, tap "ประวัติการตรวจเช็ค".
    - Expected: submitted inspections appear newest first with correct pass/fail/na counts and a "ผ่านทุกรายการ"/"ไม่ผ่าน N รายการ" badge.
    - Failure evidence: screenshot + `GET /api/v1/inspections?...` response.

11. **History detail**
    - Action: tap a row in the history list.
    - Expected: opens the exact immutable record, matching what was submitted, including the checklist revision number used at the time.
    - Failure evidence: screenshot + compare against the original submission response.

12. **FAIL finding**
    - Prerequisite: an inspection submitted with at least one FAIL.
    - Action: open its detail page.
    - Expected: an "ข้อบกพร่องที่พบ" section lists the failed item's title; no "create repair order" action exists anywhere on this page.
    - Failure evidence: screenshot; confirm absence of any repair-related control.

13. **Unknown asset 404**
    - Action: open `/inspections/INS-9999` directly.
    - Expected: a controlled Thai "ไม่พบข้อมูลผลการตรวจเช็คนี้" message, not a crash or blank page.
    - Additional check (documents the finding in Section I): open `/vehicle/VEH-9999/inspect` directly. **Current behavior:** the checklist form still renders using "VEH-9999" as the label instead of showing an immediate Thai not-found message; submission is still correctly blocked at the end with a 404. Capture this behavior as evidence for the Section I finding, not as an unexpected crash.
    - Failure evidence: screenshot + full page HTML for both cases.

14. **Old inspection after a newer checklist revision**
    - Prerequisite: developer access to insert a second `ChecklistRevision` directly (no authoring UI exists — this mirrors what the automated test `test_new_checklist_revision_does_not_mutate_a_previously_submitted_inspection` does at the repository level).
    - Action: `curl GET /api/v1/checklists/CHK-0001/revisions/REV-0001` before and after such a change; also re-open a previously submitted inspection's detail page.
    - Expected: both the old revision endpoint and the historical inspection detail page are unchanged.
    - Failure evidence: diff the two `curl` responses.

15. **Smartphone test**
    - Action: repeat items 1–9 on a real phone (or DevTools emulation) in both portrait and landscape.
    - Expected: no horizontal scrolling, PASS/FAIL/N/A easily tappable one-handed, camera opens for evidence photos, "ส่งผลการตรวจ" stays reachable while scrolling.
    - Failure evidence: screenshot in the failing orientation.

16. **Desktop test**
    - Action: repeat items 1–9 at ≥1280px width.
    - Expected: PASS/FAIL/N/A lay out side-by-side; history renders as a real table (not stacked cards).
    - Failure evidence: screenshot + exact window width.

---

## Q. Final Verdict

# PASS WITH KNOWN LIMITATIONS

**Blocking defects:** None. All required Phase 3 scope items are
implemented, all automated tests were independently re-executed in this
session and passed (backend 72/72, frontend unit 29/29, typecheck/build/
lint clean, Playwright 75/75 across all 5 required viewport bands). No
frozen Phase 1/2 contract was changed. D01, D02, D03, and D04 were all
correctly left unresolved, with reversible, disclosed placeholders — this
was independently verified structurally (Section D), not taken on the
report's word.

**Known limitations:**
1. **(Moderate, drives the "WITH KNOWN LIMITATIONS" qualifier)** "FAIL
   requires a non-empty remark" is enforced unconditionally, for every
   checklist item, on both backend (`inspection_service.py:177-184`) and
   frontend (`InspectionFormPage.tsx:143-148`, `ChecklistItemCard.tsx:92`),
   with no per-item source-data toggle (unlike the correctly-configurable
   `required_photo_on_fail`). This rule is not separately named in the
   Phase 3 SCOPE bullet list (only "required-photo-on-fail rules" is), is
   not tied to any `OPEN_DECISIONS_REGISTER_EN.txt` entry, and was not
   flagged for confirmation in the phase report's own "Open Decisions
   Encountered" section. It is a reasonable, narrow data-quality rule
   (not a fabricated technical/safety standard), but per this audit's
   brief it must be surfaced rather than assumed approved. See Section C.
2. No MIME-type allowlist or file-size limit on attachment upload; the
   download endpoint echoes the client-supplied `content_type` back
   verbatim with no `Content-Disposition`/`nosniff` protection. Bounded
   risk today (no production auth exists yet regardless), but this is the
   first phase to ship a real upload endpoint and the Phase 1-disclosed
   pre-condition for that moment (M07) was not carried forward into
   Phase 3's Known Limitations. See Section M.
3. `InspectionFormPage` does not show an immediate 404 for a nonexistent
   vehicle/equipment ID reached by direct URL — the checklist form still
   renders and only fails at submission time (with a correct backend
   404). Data integrity is not at risk. See Section I.
4. All limitations already disclosed in the Phase 3 result report remain
   accurate and are not repeated in full here: placeholder-only checklist
   content (Section G confirms this is clearly disclosed, not a defect),
   no checklist-authoring UI, `GoogleSheetsRepository`'s Phase 3 methods
   are interface/schema-only (cannot be exercised without real
   credentials in this sandbox), no pager UI on inspection history, no
   RBAC beyond `DEV_AUTH_MODE`, and orphaned evidence files are not
   cleaned up when removed from the form before submission.

**Open decisions intentionally deferred (correctly left unresolved):**
D01 (checklist assignment), D02 (scheduling), D03 (critical items), D04
(correction/void/supersede) — see Section B for the individual status of
each. A01 (transaction ID strategy) remains open and Phase 3's ID
generation is an isolated, reversible continuation of Phase 2's existing
mock-only convenience, not a new freeze.

**Unapproved decisions found:** One — the unconditional FAIL-remark rule
described in Known Limitations item 1 / Section C. This is not treated as
severe enough to warrant a plain FAIL verdict (it does not fabricate
technical/safety content, corrupt data, or violate a frozen contract),
but per the audit brief it precludes an unqualified PASS until the user
either explicitly confirms it as the intended permanent rule or asks for
it to be made configurable.

**Frozen Phase 1/2 contracts confirmed intact:** `/api/v1` versioning;
the common error envelope; `Page`/`PageParams` pagination; the
opaque-prefixed stable-ID convention; UTC ISO-8601 timestamps;
`RequestContext`/`DEV_AUTH_MODE`; the `Repository`/`StorageProvider` ABCs
(extended only, per Section K's file-by-file review); `VehicleService`/
`EquipmentService` and the Vehicle/Equipment domain models and routes
(untouched); the permanent QR routes `/vehicle/{vehicle_id}` and
`/equipment/{equipment_id}` (byte-for-byte unchanged); the mobile-first
responsive foundation (`Card`, `ResponsiveTable`, `FormField`,
`.sticky-actions`, `--tap-target`, breakpoints — reused, only additive
CSS classes introduced). All 47 pre-existing backend tests, 18
pre-existing frontend unit tests, and 55 pre-existing Playwright tests
were confirmed still passing as a subset of the current totals.

**D01 status:** Unresolved, correctly so. Placeholder ("one active
checklist family per asset type") is structurally reversible and clearly
disclosed at both the code and user-facing UI level (Section D).

**D02 status:** Unresolved, correctly so. No scheduling/due logic exists;
`frequency` is inert metadata (Section J).

**D03 status:** Unresolved, correctly so. `is_critical` is architected but
never populated with real or invented data (Section B/F/G).

**D04 status:** Unresolved, correctly so. No correction/void/supersede
capability exists at any layer; the create-and-read-only surface is the
strictest possible interpretation of immutability (Section E).

**Phase 4 accidentally implemented:** NO. Confirmed by a repo-wide search
for repair-related code: only forward-looking docstring comments exist
(`asset.py`, `inspection.py`, `inspection_service.py`, `FormField.tsx`),
no Repair domain model, route, service, or UI exists anywhere.

**Next phase readiness:** NOT READY (pending correction) — Phase 4 should
not begin until the unconditional FAIL-remark rule (Known Limitations
item 1) is explicitly confirmed or reworked by the user, since Phase 4
(Repair) is likely to build on top of `InspectionFinding` and inherit any
unresolved assumption about what "required FAIL details" means. The file
upload hardening in item 2 should also be addressed before any real
(non-mock, non-dev-auth) deployment, though it does not block continued
local-development work on Phase 4 specifically.

---

STOP HERE. This is an audit only. Phase 4 was not started. No open
decision (D01–D04 or otherwise) was resolved. No frozen Phase 1/2 contract
was changed. The one finding above (unconditional FAIL-remark rule) is
reported for the user's decision, not silently corrected.
