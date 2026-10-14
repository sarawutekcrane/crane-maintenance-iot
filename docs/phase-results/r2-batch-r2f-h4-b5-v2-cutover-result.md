# R2 Batch R2f-h4 B5 — Technician V2 Navigation Cutover + Legacy Assignment UI Removal — Result

Status: REVISED CANDIDATE (owner-authorized responsive fix, section 10a) / UNCOMMITTED / READY FOR INDEPENDENT
REVIEW. This is not self-certified, and production readiness is not claimed. The previous candidate (patch
`36e96dd6…`, tree `c135e18d…`) is superseded by this revision.

Contract: C1 Amendment A1 (`docs/project-governance/c1-amendment-a1-v2-only.md`) §3 (safe legacy removal, group A),
§24, §25, §26 (O4), §31; the B4 result (`r2-batch-r2f-h4-b4-v2-frontend-result.md`).

Baseline:
- `web/phase7-dashboard-search-reporting` @ `17b318046555be6c1ba8b894a0049c3e4ba72350`
  (tree `4910e63b1f5e30f1cb9af4ae534b62e3072e6675`; B4 integrated);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (unchanged).

Local branch: `review/r2-batch-r2f-h4-b5-v2-cutover` (no remote, no upstream). Nothing is committed or pushed.

Frontend only:
- **zero backend change**; no schema, data, role, capability or setting change;
- no live Google Sheets access;
- the V2 setting is ON only in the dedicated mock test backend process.

## 1. Approach — one canonical route per workflow

The B4 parallel `/v2/...` pages are retired. The existing canonical pages now host the V2 workflow, so every entry
point already in the application keeps working:
- NavBar;
- the Vehicle / Equipment Detail actions;
- the history lists;
- the Finding → Repair link;
- the Repair-Request queue;
- the parts and parts-lifetime pages.

Each page keeps its non-assignment features. Only the legacy assignment pieces are removed or replaced.

| Workflow | Canonical route (unchanged path) | Before B5 | After B5 |
|---|---|---|---|
| Repair creation | `/vehicle/:id/repairs/new`, `/equipment/:id/repairs/new` | legacy create with inline `primary_technician` | V2-gated direct create, no technician field (B4 rules); the Repair-Request report flow unchanged |
| Repair-Request conversion | `/repair-request-queue` | convert always offered | V2-gated (the conversion opens a Repair) |
| PM creation | `/vehicle/:id/pm`, `/equipment/:id/pm` | "เริ่มทำ PM" always offered | V2-gated; the plan status stays readable |
| Repair detail | `/repairs/:id` | free-text "การมอบหมายงาน" (`POST /repairs/{id}/assign`) | `JobAssignmentSection` (V2 panel / LEGACY read-only / INVALID error) + every existing action, evidence, parts, meter and close feature |
| PM detail | `/pm/work-orders/:id` | no team shown | `JobAssignmentSection` + every existing PM feature (scope, results, evidence, defect report, close) |
| My Work | `/my-work` | legacy `/repairs/my-work` + `/pm/work-orders/my-work` | V2 `GET /my-work` (PRIMARY / COLLABORATOR, unresolved states) + the retained "คำขอแจ้งซ่อมของฉัน" (UAT-F2, `/repair-requests/mine`) |
| Waiting assignment | `/waiting-assignment` | legacy `/repairs/waiting-assignment` (Repair only) | U1 Repair and PM queues (A1-§24 routes, per capability) |
| Open-repair report | `/open-repair-queue` | legacy-mirror assignee column | column removed (the report is otherwise unchanged) |

**Retired B4 bookmarks** (`/v2`, `/v2/repairs/:id`, `/v2/pm/work-orders/:id`, `/v2/{vehicle,equipment}/:id/repairs/new`,
`/v2/{vehicle,equipment}/:id/pm`, `/v2/my-work`, `/v2/waiting-assignment`, any other `/v2/*`) redirect with
`replace` to the canonical page, keeping the ids. A redirect is a plain navigation: it never creates or changes
anything (unit and E2E tested: only GET requests).

**Legacy bookmarks:** the canonical paths are the old paths, so an old bookmark lands on the cut-over page. The page
offers no legacy assignment edit and no legacy create.

## 2. Removed or blocked legacy assignment entry points

| Entry point | Treatment |
|---|---|
| Repair detail free-text assignment (`POST /repairs/{id}/assign`, `ช่างผู้รับผิดชอบหลัก` / `ผู้ร่วมงาน (คั่นด้วยจุลภาค)` / "บันทึกการมอบหมาย") | removed |
| Repair creation inline `primary_technician` field (and the body key) | removed |
| Repair / PM / Repair-Request-conversion creation with the cutover OFF, the flag missing / invalid, or `/me` failed | blocked: "การมอบหมายช่างยังไม่เปิดใช้งาน", no form or control, no create request, no legacy fallback |
| Legacy My Work reads (`/repairs/my-work`, `/pm/work-orders/my-work`) | no longer called |
| Legacy waiting queue (`/repairs/waiting-assignment`) | no longer called |
| Open-repair legacy-mirror assignee column | removed |
| B4 parallel pages (`pages/v2/*`) | removed; bookmarks redirect |
| NavBar "รอมอบหมายช่าง" | now opens the U1 view; shown for `can_manage_repair` OR `can_manage_pm` (the PM queue needs `can_manage_pm`); the backend re-checks each queue |

No frontend code calls `/assign` or `/assignment-history` any more. The backend routes stay unchanged (B6 /
separate authorization).

## 3. Retained functionality (non-assignment)

- **Repair detail:** summary, meter snapshots, action history plus new actions with photo evidence, actual parts
  (Part Master / Part Instance), close with note.
- **PM detail:** task revision, scope add / approve, results, evidence, PM-defect Repair Request, close.
- **Problem reporting:** the Repair-Request flow for non-Maintenance actors, including Finding / PM-defect
  provenance and the "already reported" state (UAT-F1 / F3).
- **My Work:** the caller's own Repair Requests (UAT-F2).
- **Pages unchanged in behaviour:** the PM plan status, the open-repair report, the histories, parts / lifetime,
  personnel and registry pages.
- **Unchanged:** all backend endpoints, storage, histories, identities, audit, capabilities and authorization.

**LEGACY jobs:** a read-only `LEGACY_USER_ID` display (raw, never converted, never editable). **INVALID / unknown
markers:** an explicit error (`ASSIGNMENT_MODEL_INVALID`) in the assignment area only; the rest of the job stays
usable (E2E).

## 4. Creation and the cutover signal

- The signals are parsed as in B4 (fail closed).
- Every creation page shows a loading state, not a form, until `GET /me` resolves (unit tested).
- **Direct Repair create:** blocked unless the flag is exactly ON. When ON, the body is exactly `asset_type`,
  `asset_id`, `source_type`, `source_id`, `category` and `symptom`, with no technician field. A double click sends one
  request.
- **PM start:** blocked unless the flag is ON, with one start in flight.
- **Repair-Request convert:** blocked unless the flag is ON, with body `{}`. The backend persisting
  `TECHNICIAN_V2` on conversion was verified on the mock.
- **Verification:** E2E reads back `assignment_model = TECHNICIAN_V2` for Repair and PM jobs created through normal
  navigation.
- **Unchanged rules:** the frontend never sets the flag; the backend default is unchanged.

## 5. Assignment, My Work and U1

These are unchanged from B4 and are now reached from the canonical pages:
- the stable-ID picker;
- exactly one PRIMARY plus optional COLLABORATORs;
- `expected_current`;
- the pending intent with a same-id resend;
- stale reload and reconfirm;
- no empty-set unassignment;
- no control on CLOSED or AMBIGUOUS jobs;
- `ErrorState` with code and request id.

My Work and U1 behave exactly as in B4, except that their links go to the canonical detail pages. Backend CLOSED-job
behaviour is unchanged and still PENDING (the UI offers no control).

## 6. TEST / REAL simplicity

- No TEST/REAL selector and no client-controlled scope.
- No migration or cleanup feature, and no TEST-management workflow.
- The data-context banner stays informational. It appears on the creation and assignment surfaces, labels TEST
  visibly, and never shows a non-REAL context as REAL.
- Backend isolation is unchanged.
- The V2 setting is ON only in the mock E2E backend (`playwright.config.ts`); there are no staging or production
  settings in this repository diff.

## 7. Test workflow integration

- The dedicated V2 suite is folded into the normal suite (`npx playwright test` / `npm run test:e2e`).
  `playwright.v2.config.ts` and `e2e-v2/` are removed. Their specs become `e2e/technician-v2.spec.ts`,
  `e2e/technician-v2-off.spec.ts` and `e2e/technician-v2-helpers.ts`.
- **Main pair:** backend 4311 (mock, DEV auth, development env, `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true`) plus
  frontend 4310. All five viewport projects run against it.
- **OFF pair:** backend 4331 (the setting explicitly unset → default OFF) plus frontend 4330. Projects
  `cutover-off-desktop` and `cutover-off-smartphone` run only `technician-v2-off.spec.ts`; the viewport projects
  ignore it.
- **Isolation:** all four servers use `reuseExistingServer: false` and `--strictPort`, so a stray server with another
  setting is never reused. Playwright stops them at the end.
- **Route stubs:** used only for error injection, as in B4. The one exception is the photo matrix, which holds a real
  upload open (then lets it through unchanged) to measure the "uploading" state.
- **`responsive-photo` project (responsive fix):** runs `e2e/photo-attachment-responsive.spec.ts` once. Each test opens
  its own context per required viewport (1280×800, 768×1024, 1024×768, 375×667, 667×375; mobile emulation below
  desktop). The viewport projects ignore this spec.

## 8. Regression test migration matrix

| Test | Original invariant | Why the legacy procedure is no longer valid | New procedure | Evidence the invariant is still tested |
|---|---|---|---|---|
| `e2e/pm-repair.spec.ts` (7 creating tests) | PM start → work order → results / parts / close; manual Repair → actions / parts / close; Finding → Repair link; equipment PM / Repair; evidence after reload | creation is now V2-gated (it would be blocked on an OFF backend) | unchanged steps against the V2-ON mock; each creation additionally asserts the V2 team area (never the legacy assignment) | all original assertions kept; 7 added V2 assertions; passing on 5 viewports |
| `e2e/web-uat-defect-fix.spec.ts` F2 | a DRIVER finds their submitted Repair Request from My Work | My Work no longer reads the legacy lists | unchanged: the requests section is retained on the V2 My Work | unchanged assertions pass |
| `e2e/web-uat-defect-fix.spec.ts` F3 | PM-defect "already reported" survives reload | PM start is V2-gated | unchanged steps; the PM job asserts the V2 area | unchanged plus 1 added assertion |
| `e2e/parts-lifetime.spec.ts` (PM actual part → Part Instance) | a PM actual part links to a Part Instance | PM start is V2-gated | unchanged steps; the PM job asserts the V2 area | unchanged plus 1 added assertion |
| `e2e-v2/*` (B4) | V2 create / picker / assign / U1 / My Work / stale / unknown / denied / corrupted / CLOSED / OFF / LEGACY | the `/v2` pages are retired | the same tests on the canonical pages, reached by normal navigation (Vehicle Detail → "แจ้งซ่อม" / "PM"; NavBar → "รอมอบหมายช่าง" / "งานของฉัน"); added: `/v2` bookmark redirects, OFF Repair-Request conversion, OFF equipment create | 9 ON tests × 5 viewports + 4 OFF tests × 2 |
| `MyWorkPage.test.tsx` | open repairs AND open PM work orders both appear, plus the caller's requests | legacy endpoints | the same invariant via `GET /my-work`; no legacy request | migrated (marked in the source) |
| `RepairDetailPage.test.tsx` "Assign/Close controls" | Maintenance sees the job controls | the free-text Assign is retired | the Close control plus a read-only LEGACY assignment; no Assign control and no `/assign` request | migrated (retires the obsolete Assign assertion; marked) |
| `RepairCreatePage.test.tsx`, `PmStatusPage.test.tsx` | Maintenance creates a Repair / starts a PM | creation is V2-gated | the Maintenance fixture reports the server cutover ON; OFF / missing-flag blocking is covered in `TechnicianV2Cutover.test.tsx` | every original assertion kept (marked) |
| `OpenRepairQueuePage.test.tsx` (2 tests) | columns; `opened_at` formatting | the legacy-mirror column is removed | the header list drops the column; the formatting assertions are kept; the legacy mirror is asserted absent | migrated (retires the column assertion; marked) |
| `pages/v2/V2Pages.test.tsx` (B4) | the B4 page rules | the `/v2` pages are retired | `pages/TechnicianV2Cutover.test.tsx` on the canonical pages, plus the convert gate, the pre-`/me` loading gate, retained-feature, LEGACY and link tests | 47 tests (B4: 39) |

**Added:**
- `JobAssignmentSection.test.tsx` (8 tests);
- the PM detail assignment-area tests (3);
- the NavBar waiting-item tests (4);
- the `/v2` redirect tests (10).

**Not used anywhere:** unconditional skips, removed tests to conceal a failure, or smoke-test replacements.

## 9. Gates

The precise counts and exit codes are in the candidate report.
- Commands: `npx tsc -b --noEmit`; `npx vitest run`; `npx oxlint`; `npm run build`; `npx playwright test`; backend
  `python -m pytest -q`; the named R2f suites; the mutation runner.
- **Frontend fix-removal mutations:** 16 of 16 caught.
  - G01–G05: creation gates and the legacy field;
  - G06 / G07: LEGACY or INVALID shown as V2;
  - G08 / G09: My Work legacy fallback or dropped requests;
  - G10: the NavBar PM-only gap;
  - G11 / G12: redirect or link regressions;
  - G13: the legacy column back;
  - G14: the CLOSED status not passed to the panel;
  - G15: the PM detail area removed;
  - G16: the U1 per-capability gate removed.

  G14 was first written as a no-op mutant (a duplicate JSX prop) and was replaced. G15 survived the first run and
  was fixed by adding the PM detail unit tests. Both are reported.

## 10. Known limitations and observations

- **Layout defect in `PhotoAttachmentField`:** pre-existing, and corrected in this revision (section 10a, owner
  authorization "B5 RESPONSIVE FIX ONLY").
- **Backend:** V2 assignment on CLOSED jobs is accepted (owner decision PENDING). The UI offers no control, and the
  backend is unchanged.
- **Index:** during development a `git mv` briefly staged one rename; it was unstaged immediately (`git reset`), and
  the index is clean.

## 10a. Responsive fix — PhotoAttachmentField horizontal overflow

**Root cause** (from the CSS cascade, confirmed in the browser with the computed style of `#action-photo` at
1280×800):

| Property | Computed value | Source |
|---|---|---|
| `position` | `absolute` | `.photo-attachment-field__input` |
| `width` | `1280px` | `.form-field input` |
| `height` / `min-height` | `44px` | `.form-field input` |
| `padding` | `8px 12px` | `.form-field input` |
| `border` | `1px` | `.form-field input` |
| `clip` | `rect(0, 0, 0, 0)` | `.photo-attachment-field__input` |
| `left` | `212px` | — |
| positioned ancestor | none | — |

- The input carries both the field's own visually-hidden rule `.photo-attachment-field__input` (specificity 0,1,0)
  and the generic `.form-field input` rule (0,1,1), which wins on `width: 100%`, `min-height`, `padding` and
  `border`.
- With no positioned ancestor, the absolutely positioned input's `width: 100%` resolves against the initial
  containing block (the viewport), starting at its in-card x offset.
- `clip` hides it visually but not from layout, so the page scroll width = offset + viewport width.

**Fix (component-scoped, CSS only, `frontend/src/index.css`):**
- the visually-hidden rule's selector becomes `.photo-attachment-field .photo-attachment-field__input`
  (0,2,0), which outranks `.form-field input`;
- `min-height: 0` is added.

No global rule, no `overflow-x: hidden`, no clipping of the page and no component markup change. `position: relative`
on the field was deliberately not added: it would mask the root cause and make the fix-removal check meaningless.

**Before / after** (`document.documentElement.scrollWidth` / `clientWidth`, photo input width).

The values are identical across every measured page and state:
- Repair detail: no photo, uploading, photo attached, evidence recorded;
- PM work-order detail: no photo, photo attached;
- Inspection form (failed item): no photo, photo attached.

That is 8 states × 5 viewports = 40 measurements, each way.

| Viewport | Before | After |
|---|---|---|
| desktop 1280×800 | 1492 / 1280, input 1280 px | 1280 / 1280, input 1 px |
| tablet portrait 768×1024 | 812 / 768, input 768 px | 768 / 768, input 1 px |
| tablet landscape 1024×768 | 1108 / 1024, input 1024 px | 1024 / 1024, input 1 px |
| smartphone portrait 375×667 | 407 / 375, input 375 px | 375 / 375, input 1 px |
| smartphone landscape 667×375 | 711 / 667, input 667 px | 667 / 667, input 1 px |

**Tests:**
- **`e2e/photo-attachment-responsive.spec.ts` (new, `responsive-photo` project):**
  - asserts exactly `scrollWidth <= clientWidth`, with no element excluded and no tolerance, at all five viewports in
    every state above (with real uploads through the mock backend);
  - checks that the input keeps `accept="image/*"` and `capture="environment"`, and that the action records its
    evidence photo;
  - checks that the input stays enabled and keyboard-focusable (not `display: none`, `visibility: visible`) behind
    its labelled trigger.
- **`e2e/technician-v2-helpers.ts`:** `expectResponsive` now uses the same exact page-level assertion. The former
  `.photo-attachment-field__input` exclusion is removed.
- **`src/components/PhotoAttachmentField.test.tsx` (new, 5 tests):**
  - the label → input link, and unchanged `accept` / `capture`;
  - one `onAddFile` call per selection, with the input reset;
  - an empty selection is ignored;
  - the uploading state disables the input;
  - the attached count, thumbnail, and remove by id.
- **Fix removal:** with the original rule restored (hash-checked restore), 5 tests fail: the 3 matrix tests plus the
  V2 Repair flow on desktop and smartphone (the strict `expectResponsive`). With the fix, all pass.

**Corrections and flakes during this fix (reported, not concealed):**
1. **Test-side race in the new matrix (fixed).** In the first two full runs, the Repair "evidence-recorded"
   measurement ran during the page's reload after saving the action. It waited only for an image whose alt text the
   pre-submit thumbnail also carries, and while the page reloads it is briefly in its loading state with no photo
   field. Result: "the photo field must be rendered" (input not found), never an overflow. The test now waits for the
   saved action's text and the cleared field. It then passed 20 / 20 under `--repeat-each=5` and in both final full
   runs.
2. **Unrelated one-off flake.** `vehicle-registration-write.spec.ts` I-OC-01 (desktop) timed out on a click once, in
   the first full run only. It is untouched by B5 and this fix. It passed 70 / 70 in isolation (`--repeat-each=10`)
   and in the later three full runs, and is reported as an existing timing flake.

**Unchanged:**
- the component markup and behaviour;
- the upload request and payload (`POST /attachments`, the same `FormData`);
- accepted types, validation and status texts;
- every other selector.

**Observation (not changed):** the visible trigger is a `<label>`. Keyboard focus lands on the visually hidden input,
which has no visible focus ring of its own. This is the existing design, and a later accessibility refinement could
style the trigger on input focus.

## 11. Remaining dependencies

- **B6:** legacy backend cleanup (`/assign`, inline assignee on create / convert, legacy My Work / waiting reads),
  after a separate dependency review and owner authorization.
- **Owner decisions:** CLOSED-job assignment; empty-set unassignment.
- **Live:** the V2 setting in live, the live schema, link population, R11 and Go-live each need their own approval.
- **Unchanged:** D5 PENDING; H3-01 fail-closed.
