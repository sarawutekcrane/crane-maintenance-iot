# R8 PRE-UAT — TEST fixture mapping and local setup (browser UAT)

Owner approval: R8 PRE-UAT Whole-Web Completion Rev 1 (2026-11-18). **Mock / TEST only.** Not PostgreSQL
evidence, not production evidence. Google Sheets stays TEST-only and is **not** used for this UAT; D-9 (writing
the UAT workbook control tabs) is **not authorized** — results go to a separate report file
(`docs/phase-results/r8-preuat-completion-result.md` and the export pack).

## 0. Who can run this (read first)

The commands below start the app on a developer's own machine or inside a Claude Code Web cloud session, where
they are used for **automated** browser evidence (Playwright, screenshots, traces). A cloud session's `127.0.0.1`
is **not** the Owner's computer: it cannot be opened from the Owner's browser, and it must not be exposed (no
tunnel, no public port, no shared dev-auth). The app's development identity comes from request headers, which
only automation or a developer machine can set safely.

**Owner manual browser UAT: ACCESS BLOCKED** until the Owner decides on an access route that has real
authentication, per-user TEST grants, HTTPS, Mock/TEST isolation, disposable data and access control (see the
access decision in the UAT evidence pack). Until then every scenario keeps `PASS_MANUAL = false`; the automated
evidence (screenshots / traces) is what the Owner can review.

## 1. Tracks

| Track | How | Use |
|---|---|---|
| B1 legacy Mock (development roles) | default backend (`DATA_REPOSITORY=mock DEV_AUTH_MODE=true APP_ENV=development`) | regression of the existing development-role UI |
| B2 Access Management Mock | B1 + `ACCESS_MANAGEMENT_MODE=true` | per-employee grants (`/access-management`) |
| **B3 PRE-UAT profile** | B2 + `MOCK_FIXTURE_PROFILE=uat_r8` + `PM_MASTER_TEST_PROFILE=true` | master records, Store workflow, TEST classification, parts (PG-5 P-A), PM Master TEST, whole-web walk |
| Google Sheets UAT copy | **OFF** | never set `REGISTRY_DATA_CONTEXT=REAL`; Sheets-only problems are simulated, not fixed |

The profile is refused unless `DATA_REPOSITORY=mock` and a recognized non-production `APP_ENV`. Without the
flag the default Mock seed is unchanged. `PM_MASTER_TEST_PROFILE=true` (Owner gate 2026-11-18, SG-PM) is accepted
only with Mock + Access Management + a non-production `APP_ENV`; only then does the backend register the
`/api/v1/pm-master-test/*` routes and the menu item "แผน PM หลัก (ทดสอบ)" appear for grant holders.

## 2. Start B3 locally

```bash
cd backend && source .venv/bin/activate
DATA_REPOSITORY=mock DEV_AUTH_MODE=true APP_ENV=development ACCESS_MANAGEMENT_MODE=true MOCK_FIXTURE_PROFILE=uat_r8 PM_MASTER_TEST_PROFILE=true uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend && npm run dev -- --host 127.0.0.1
```

Bind to localhost only. `GOOGLE_SHEET_ID` and credentials must not be set. Mock state is in memory: a
restart resets everything.

Identity in development: the app has no user picker. Automation sets the `X-Dev-User-Id` request header (and
`X-Dev-Role: TECHNICIAN`), as the E2E specs do; a developer may do the same on their own machine only. Without it the default
`dev-user` has no employee link and every Access Management write is refused (`ACCESS_ACTOR_NOT_VERIFIED`). Access Management seed users: `USR-TEST-AM-MGR` (root position holder), `USR-TEST-AM-CLERK`,
`USR-TEST-AM-OPM`, `USR-TEST-AM-DRV1/2`, technicians `USR-TEST-911/912` (`TEC-TEST-911/912`).

## 3. Grants (zero default holders; root is not automatic)

As `USR-TEST-AM-MGR`, open `/access-management` and grant per employee, with a reason:

| Capability (TEST) | Needed for |
|---|---|
| `can_test_manage_master_records` | create / edit TEST master records (vehicles, models, equipment, branches, departments, personnel, technicians) |
| `can_test_store_approve` / `can_test_store_issue` / `can_test_store_receive_return` | Store approval / issue / return acceptance |
| `can_test_classify_repair` | TEST repair classification |
| `can_test_pm_master_publish` | PM Master TEST: register the synthetic source, decide REVIEW entries, publish, approve model variants |
| `can_test_pm_master_assign` | PM Master TEST: assign a vehicle to the TEST plan (separate from publish) |
| `can_test_manage_parts` (PG-5 P-A) | part sets (create / revision / applicability) and part maintenance events in AM mode |
| existing `can_view`, `can_manage_repair`, `can_close_repair`, `can_manage_pm` | reading; repairs; the maintenance-event handler's own operational check; opening a Master-sourced PM Work Order |

## 4. Profile contents (`UAT8-` prefix; all invented; TEST scope, batch `MOCK-7O2B-SYNTHETIC`)

| Profile records | Purpose (semantic mirror of the UAT workbook — no workbook IDs are copied) |
|---|---|
| `UAT8-MDL-A` (carrier + crane engine + PTO), `UAT8-MDL-B` (carrier + PTO) | model + component roles |
| `UAT8-VEH-01…07`: READY, WORKING, MAINTENANCE, OUT_OF_SERVICE, LONG_TERM_PARKING, READY, WORKING across BR-BANGNA-KM6 / BR-LAEM-CHABANG / BR-RAYONG; VEH-07 has machine no. `UAT8/007` (different format) | dashboard KPIs, filters, drill-down, search |
| current counters; **VEH-03 without meters** (UNKNOWN) | meter display, UNKNOWN never 0 |
| latest location: VEH-01 recent, VEH-02 stale, others none | "not live" location and its age |
| `UAT8-CERT-01` valid, `-02` near expiry, `-03` past-dated but ACTIVE | expiry report, alerts, R7 A-5 observation |
| `UAT8-PER-01…10` (drivers, rigger, signalman, helper, technicians, supervisor, safety, one INACTIVE) | crew / calendar / identity cases |
| `UAT8-TEC-01…03` | technician lists |
| `UAT8-PINST-01` (PART-0005) + `UAT8-LTR-INSPECT` / `UAT8-LTR-REPAIR` (synthetic, model UAT8-MDL-A, not real thresholds) | part maintenance events in AM mode |
| built-in synthetic PM source (`UAT8 PM Plan`: variant A = CARRIER 600 h, CRANE 600 h, ODOMETER 10,000 km; variant B = one 250 h Set needing a meter decision) | PM Master TEST flow |
| `frontend/e2e/fixtures/test-certificate-valid.pdf`, `test-document-valid.pdf` (labelled TEST ONLY), `test-invalid-signature.pdf` (not a PDF) | R7 document upload, positive / negative |

## 5. Suggested browser walk

1. Dashboard → status card → filtered list → `UAT8-VEH-0x` → vehicle hub (location age, meters, certificates link).
2. `/master-data` and the vehicle / equipment / personnel / department lists: create a TEST record, edit it,
   check history; a REAL record offers no edit; a duplicate is refused.
3. Repair (open a MANUAL repair, assign the V2 team): Store panel request → approve → issue → close repair →
   use / declare return → accept return → "สถานะกระทบยอด: ครบแล้ว".
4. Classification panel (closed + reconciled repair): SYSTEM → ASSEMBLY → POINT from the TEST-CANDIDATE-R1
   subset (24 relationships), symptoms allowed for that point, actions A01–A15, optional position; stage the
   draft, then finalize. Badge: "TEST candidate — ไม่อนุมัติสำหรับ REAL".
5. Rejections to try: classify before reconciliation; a conflicting code (e.g. `ACM-AC-P135`); a symptom not
   allowed for the point; re-submit the same request (replayed, nothing duplicated); a user without the grant;
   a return that does not name the issued part (refused, nothing guessed).
6. Parts (AM, `can_test_manage_parts`): part page → part set (REQUIRED / ALTERNATIVE items, applicability);
   `/part-instances/UAT8-PINST-01` → in-place repair against `UAT8-LTR-REPAIR` (no new-cycle control: R6 A-2(ii)).
   Without the grant the controls are hidden and the API answers 403.
7. PM Master TEST (`/pm-master-test`): as the publish-grant holder register the synthetic source → decide the
   meter REVIEW → publish → approve `UAT8-V-A`; as a different employee with the assign grant assign
   `UAT8-VEH-01`; then `/vehicle/UAT8-VEH-01/pm/due` → select Sets → "เปิดใบงาน PM จากแผนหลัก" (needs
   `can_manage_pm`). Due stays UNKNOWN until a verified completion meter exists (no IoT source in the app — R9).

## 5a. Role-by-role browser setup (header `X-Dev-User-Id`)

| Role in the walk | User | Grants to give (via `/access-management`, as `USR-TEST-AM-MGR`) |
|---|---|---|
| Manager / PM publisher / Store / classifier | `USR-TEST-AM-MGR` | `can_view`, `can_manage_repair`, `can_close_repair`, `can_manage_pm`, `can_test_pm_master_publish`, `can_test_store_approve`, `can_test_store_issue`, `can_test_store_receive_return`, `can_test_classify_repair`, `can_test_manage_master_records`, `can_test_manage_parts` |
| PM assigner (separate person) | `USR-TEST-AM-OPM` | `can_view`, `can_test_pm_master_assign` |
| Technicians (V2 team) | `USR-TEST-911`, `USR-TEST-912` | `can_view` |
| Plain reader (negative checks) | `USR-TEST-AM-CLERK` | `can_view` only |

## 6. Cleanup and R11 exclusion

- `UAT8-` IDs exist only in Mock memory; a restart removes them and everything created during the walk.
- The UAT workbook stays excluded at R11/R12 (UAT migration exclusions).
- Updating the workbook control tabs needs a separate write authorization (D-9 not approved).

## 7. Hosted TEST UAT through Cloud Run Direct IAP (H1-DIRECT) — NOT YET DEPLOYED

Owner source approval Gate A (2026-11-19) covers the source only. **Gate B (Git) and Gate C (cloud
deployment / IAM / billing) are not approved.** Nothing has been deployed; no manual UAT has run (PASS_MANUAL
is false for all 67 scenarios).

**What it is.** One short-lived Cloud Run service with Direct IAP (`--iap`) on its own `run.app` HTTPS URL.
The image (`deploy/uat-r8/Dockerfile`) serves the built frontend and the API on the same origin, with one
uvicorn worker and Cloud Run `max-instances=1`.

**Identity.**
- `TEST_IDENTITY_PROXY=google_iap` takes every request's identity ONLY from the signed
  `x-goog-iap-jwt-assertion`. The app verifies:
  - the ES256 signature against Google's IAP public keys (cached; fail closed);
  - issuer `https://cloud.google.com/iap`;
  - audience `/projects/PROJECT_NUMBER/locations/REGION/services/SERVICE_NAME`;
  - expiry.
- The verified email is hashed (`sha256("r8-uat-iap:" + lower(trim(email)))`) and looked up in
  `TEST_IDENTITY_MAP`, which maps hash → synthetic `USR-TEST-…` account.
- `X-Dev-*` and `x-goog-authenticated-user-*` are ignored, and no role is ever granted.
- Any `/api` request without a verified, mapped identity gets `401 IAP_IDENTITY_REQUIRED`. Only
  `GET /api/v1/health` is open, and it carries no data. The API docs are not served in this mode.

**Required settings.** The app refuses to start otherwise:
- `APP_ENV=test`, `DATA_REPOSITORY=mock`, `DEV_AUTH_MODE=false`, `ACCESS_MANAGEMENT_MODE=true`,
  `MOCK_FIXTURE_PROFILE=uat_r8`, `PM_MASTER_TEST_PROFILE=true`;
- no `GOOGLE_SHEET_ID`, credentials or `REGISTRY_DATA_CONTEXT`;
- every mapped id must be an active synthetic account.

**Each human uses their own Google account.** Each one is granted `roles/iap.httpsResourceAccessor` on this
service only and mapped to one synthetic employee; rights come only from the §3 Access Management grants.
There is no identity switcher. Tester emails never appear in the repository, the image, the service
configuration (hashes only) or the logs.

**State.**
- The data lives in memory. A redeploy, restart, crash or platform replacement resets it to the `uat_r8`
  fixture, and grants must be given again.
- Record each scenario's evidence (screenshot plus a matrix row) outside the app right away.

**Operator steps** (preflight, OAuth client for projects without an organization, build from a verified
export, deploy with `--env-vars-file`, read-back, per-tester grants, checks N1′–N9, revocation, reset,
teardown) are in the Gate C runbook draft. Each step needs the separate Gate C approval.

