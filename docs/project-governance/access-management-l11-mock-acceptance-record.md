# Access Management + L11 Mock Implementation Acceptance Record

**Decision: Access Management + L11 Mock Implementation — MOCK ACCEPTED WITH LIMITATIONS**
Decided by: the Owner. Acceptance date: 2026-10-20.

This acceptance applies ONLY to the Mock implementation. It is NOT Production acceptance, NOT
Production readiness, NOT a deployment authorization, and NOT approval to merge into the
integration or main branches.

## 1. Identification
- Project: CRANE FLEET MAINTENANCE / IoT WEB APPLICATION + BACKEND API.
- Workstream: Access Management + R3 Finding Delegation (L11).
- Repository: `sarawutekcrane/crane-maintenance-iot`.
- Branch: `feature/access-management-l11-mock`.
- Accepted R3 Mock baseline (parent): `e53ac0add6ff6a98bd65761fbbe10c765a1766aa`
  (`docs(r3): record Mock acceptance with limitations`).
- Implementation commit (Commit 1): `9f1607c52713b569228e89ed2b82d191426bc686`
  (`feat(access): add Mock access management and L11 Finding delegation`; 44 files: 10 added,
  34 modified).

## 2. Accepted implementation scope

### AM-1 — Backend
- Every ordinary functional permission is granted per employee (`personnel_id`).
- No automatic department baselines, role templates or inherited job-title permissions;
  department and position are selection filters only. A whole-department change is a bulk
  operation over the employees eligible at that moment; later employees inherit nothing.
- Root Maintenance Manager authority comes only from a trusted position appointment bound to the
  holder's verified account; handover by the current holder; technical recovery only while no
  valid holder exists; no self-appointment.
- Scoped, non-transitive delegation (exact department and capability list; no onward delegation;
  a delegate never edits their own permissions or the root holder's); immediate revocation that
  keeps legitimate grants to third parties.
- Append-only, revision-checked access-event log with an audit view of grants, revocations, bulk
  changes, delegations, root appointments and permission resets.
- Server-side enforcement on every request, without re-login.
- Mock atomicity (single append per change), stale-revision refusal, and actor-scoped request
  replay (idempotent same-actor repeats; another actor's reuse refused).
- Permission reset boundaries: every department-history record and every effective
  employee–account or employee–technician link change.
- Fail-closed behaviour for invalid, ambiguous, unlinked or inactive identities and invalid
  department timelines.

### AM-2 — Frontend
- One responsive Access Management screen (`/access-management`).
- Department, position filter, individual employee and "all employees in department" selection.
- ON/OFF capability switches (no third state) with mixed counts ("x จาก n").
- Changed-only bulk semantics: untouched switches change nothing; exclusions are listed with
  reasons before confirmation.
- Preview, mandatory reason and confirmation before any save.
- Delegation, root position and audit sections.
- Thai permission labels and descriptions, sensitive-capability notices and Thai error states.

### AM-3 — R3 Finding L11
- Source-scoped `can_manage_finding_repair`: opening, converting, team assignment, cancellation,
  closure after completion and termination of R3 Finding rounds.
- No automatic authority over MANUAL repairs, PM work or non-R3 Technician V2 work.
- Technician completion only by the current, eligible PRIMARY.
- Technician Assignment V2-only and the accepted R3 Finding lifecycle are preserved. On R3 rounds
  L11 supersedes the earlier L8 "both capabilities" rule.

## 3. Accepted security corrections
| Item | Correction | Verified by (Mock tests) |
|---|---|---|
| B1 | Root takeover and lockout: the holder's account link, lifecycle and department are protected; the appointment is bound to the holder's account. | `backend/tests/test_access_management_security.py` (B1 tests) |
| B2 | An inactive or unverified PRIMARY is denied work recording and completion. | `test_access_management_security.py` (B2 tests) |
| D1–D8 | Owner-approved decisions: explicit bulk exclusions; audited root self-grant; scoped delegation with root protection; no permission resurrection after transfer cancellation or correction; transferred PRIMARY requires team reconfirmation; central write policy; sensitive capabilities root-only and not delegable; Finding-only L11. | `test_access_management.py`, `test_access_management_security.py` |
| Replay | Authority checked before any replay is disclosed; replay scoped to the verified actor. | `test_access_management_security.py` (replay test) |
| A1 | An account relink resets the employee's effective ordinary permissions; explicit re-grant required. | `backend/tests/test_access_management_identity.py` (A1 tests) |
| A2 | Account or technician identity changes invalidate earlier assignment authority until a manager reconfirms or replaces the team. | `test_access_management_identity.py` (A2 tests) |
| B (legacy) | A historical legacy assignment cannot authorize work after a relevant reset boundary; a missing or unusable timestamp fails closed. | `test_access_management_identity.py` (B tests) |

These are behaviours demonstrated by Mock tests and by attack reproductions run against the Mock.
They do not establish security guarantees for production authentication, real identity data, or
multi-process concurrency.

## 4. Verification evidence (final reported results, Mock only)
| Verification | Final reported result |
|---|---|
| Full backend pytest | 5,039 passed, 0 failed, 0 skipped, 941 warnings |
| Frontend Vitest | 1,015 passed, 0 failed |
| TypeScript typecheck | Passed |
| Frontend build | Passed |
| Lint | 0 errors, 30 warnings |
| Full Playwright | 697 passed, 0 failed, 112 skipped |
| Dedicated AM E2E (`ACCESS_MANAGEMENT_E2E=1`) | 10 passed, 20 expected skips |
| R3 mutation E2E | 4 passed |
| Focused Access Management security tests | 45 passed |
| Focused A1/A2/B identity and legacy tests | 15 passed |

- The focused backend counts are subsets of the full backend pytest total, not additional
  independent totals.
- The 112 Playwright skips are 82 pre-existing conditional skips and 30 from the Access
  Management spec, which runs only in its dedicated mode.
- Two earlier intermittent failures remain **UNVERIFIED** (not fixed; they did not recur in the
  final runs): `frontend/src/pages/VehicleDetailPage.branchWrite.test.tsx` and
  `frontend/e2e/inspection.spec.ts:107`.
- Legacy-job verification used controlled in-memory Mock historical fixtures; the Mock seed holds
  no legacy jobs.

## 5. Accepted limitations and deferred items
1. 22 mutating routes without an approved capability mapping remain fail-closed in Access
   Management mode (`ACCESS_CAPABILITY_MAPPING_UNRESOLVED`; listed in
   `backend/app/dependencies.py`, `AM_UNRESOLVED_WRITE_ROUTES`). Their mappings are deferred for
   Owner decisions.
2. Checklist reference-image uploads remain closed in Access Management mode pending an approved
   mapping.
3. The A2 team-reconfirmation UI shows the Technician record but not the employee currently linked
   to it. This must be improved before operational rollout.
4. The Access Management navigation link is visible to every user; the backend and the page's
   access checks remain the security boundary.
5. Development login and technical recovery use Mock-only header-based identity; this is not
   production authentication.
6. The access-event append and atomicity guard is single-process only.
7. Google Sheets mode does not implement Access Management persistence; the new storage
   operations answer HTTP 501.
8. TEST/REAL isolation, real employee–account identity mappings, production authorization,
   migration and onboarding remain unverified.
9. Production dependencies M01, M02 and R11 remain open.
10. Legacy-job coverage was demonstrated with in-memory Mock historical jobs; actual production
    legacy data has not been verified.
11. Effects of Personnel–Driver linking on the existing Vehicle–Driver functionality were not
    evaluated in this workstream. The existing Vehicle–Driver functionality must be preserved.
12. The earlier intermittent test failures listed in section 4 remain UNVERIFIED.
13. Commit 1 carries a signature header, but independent signature verification is UNVERIFIED in
    the local environment because the SSH allowed-signers file is not configured.

## 6. Compatibility and non-regression boundaries
- The R3 Mock acceptance (`docs/project-governance/r3-mock-acceptance-record.md`) remains in
  force with its limitations.
- Technician Assignment V2-only is preserved: no V2 ON/OFF setting, no retired assignment
  fallback and no automatic reassignment. An identical team is re-recorded only when a manager
  explicitly reconfirms it after a reset boundary.
- L8 (superseded on R3 rounds by L11), L9, L10 and the Finding lifecycle protections are
  preserved and covered by the regression suites.
- Legacy Repair and PM history is retained; no history is rewritten or deleted.
- The existing Vehicle–Driver functionality was not deliberately modified; its write routes are
  closed only in Access Management mode.
- No Google Sheets TEST/REAL access or production modification was performed or authorized.
- No merge or deployment is authorized.

## 7. Production readiness
**PRODUCTION READINESS: NO-GO**

This Mock acceptance record does not authorize production activation, Google Sheets access,
real-user permission grants, deployment, or a merge into the integration or main branches.

Unresolved production dependencies (none is claimed complete):
- M01 production authentication, and a production recovery process.
- M02 exact permission matrix, including the 22 unresolved write-route mappings.
- R11 production atomicity and concurrency for the permission log.
- Google Sheets persistence for Access Management.
- TEST/REAL isolation proof.
- Verification of real personnel, department, account and technician identities.
- Controlled migration and rollout, and real-user onboarding.

## 8. Future work and decision boundaries
Each of the following requires separate review and Owner approval:
- Capability mappings for the 22 unresolved write routes and for checklist reference images.
- Technician-to-employee identity display and verification during team reconfirmation (A2).
- Production identity, authentication and recovery.
- Production permission persistence and safe concurrency.
- Live personnel, department and identity verification.
- Controlled TEST/REAL migration and rollout.
- The remaining R2 Personnel/Responsibility UI scope and B7 readiness.
- Later roadmap work, including R4, only when separately authorized.

Not every deferred production item must be completed before the next independently authorized
Mock development phase.

## 9. Evidence and audit trail
Repository artifacts:
- Implementation commit `9f1607c52713b569228e89ed2b82d191426bc686` on
  `feature/access-management-l11-mock` (parent `e53ac0add6ff6a98bd65761fbbe10c765a1766aa`).
- Tests: `backend/tests/test_access_management.py`,
  `backend/tests/test_access_management_security.py`,
  `backend/tests/test_access_management_identity.py`,
  `frontend/src/lib/accessManagement.test.ts`,
  `frontend/src/pages/AccessManagementPage.test.tsx`,
  `frontend/e2e/access-management.spec.ts`.
- `docs/project-governance/r3-mock-acceptance-record.md` (accepted R3 baseline).
- `docs/project-governance/r3-implementation-contract.md` (B0; the L8 rule superseded on R3
  rounds by L11).

Conversation evidence (Claude Code session reports; not repository artifacts):
- The Owner-approved Access Management + L11 Mock implementation contract.
- The read-only security and contract verification.
- The final security correction report (B1/B2, D1–D8, replay privacy).
- The final read-only security closure (A1, A2, legacy findings).
- The identity and legacy security correction report (A1/A2/B).
- The Git finalization preflight, the Step 1 staging verification and the Step 2 Commit 1
  verification.
