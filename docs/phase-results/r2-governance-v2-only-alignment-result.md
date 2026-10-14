# R2 Post-B6 Governance Alignment — Technician V2-Only Final Policy — Result

Status: DOCUMENTATION CANDIDATE / UNCOMMITTED / READY FOR INDEPENDENT REVIEW. Documentation only; no runtime
behaviour changes.

Baseline:
- Integration `web/phase7-dashboard-search-reporting` @ `f14e01c037f7494afb821b1969dd4ebaaccfc378`
  (tree `651dc1ca8ba6a0afd934a48bccdad6a54cc57471`; B6 Rev2 integrated);
- `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae` (unchanged).

Local branch: `review/r2-governance-v2-only-alignment`.

## 1. Documents changed

| Path | Change |
| --- | --- |
| `docs/project-governance/c1-amendment-a1-v2-only.md` | New dated, owner-authorized section **A1-R1** (superseding policy). Inline SUPERSEDED / DECIDED markers on every obsolete statement. All original wording is kept: the only edit to existing text is a full stop added before the appended marker in four table cells. |
| `docs/phase-results/r2-governance-v2-only-alignment-result.md` | This report (new). |

Not changed:
- the frozen Corrected C1 record (not a repository file);
- every earlier phase-result document;
- all source, test, fixture, CI, configuration, API, schema and permission files.

## 2. Superseded-policy mapping (before → after)

| Before (A1, B0) | After (A1-R1) | Authority / evidence |
| --- | --- | --- |
| O4: `TECHNICIAN_ASSIGNMENT_V2_ENABLED=true` only in a dedicated mock test process | Setting removed; there is no ON/OFF (R1-3) | B6 Rev2 decision; `f14e01c0` |
| Additional Owner Decision: cutover OFF blocks creation; backend compatibility unchanged | Every new job is `TECHNICIAN_V2` unconditionally, with no legacy fallback (R1-2, R1-3); legacy writes retired (R1-10) | B6 Rev2; D3 |
| A1-§13: legacy backend compatibility retained (routes, readers, rows, tests) | Routes and write paths retired; readers, rows, display and the C1 §13 [APPROVED] storage rules retained | D3; `f14e01c0` |
| A1-§24: `/me` `technician_assignment_v2_enabled` | Removed; `data_context` remains | B6 Rev2 |
| A1-§24 / C1 §24 Q4: legacy `/assign` and legacy queues stay in the backend | Retired, 410 `LEGACY_ASSIGNMENT_RETIRED`; inline assignee refused with 422 | D3 |
| A1-§25: UI rows keyed on the flag (true / false) | Creation offered by capability alone; no V2-OFF state; no ON/OFF or TEST/REAL selector (R1-13) | B6 Rev2 |
| A1-§26: enabling the flag live as a Go-live approval item; the test-only setting | No setting exists. Go-live and the other approvals remain separate. Deployment prerequisites are recorded separately (R4) and are not feature flags. | B6 Rev2 result §10 |
| A1-§31: Playwright with the flag ON; the dedicated cutover-OFF mode | V2-only suite with no OFF projects; C1 §31 suites, baselines and fixtures unchanged | B6 Rev2 |
| A1-§23 item 2: `cut_02` exact key set with `LEGACY` | The deliberate, marked test migration proves a new job is `TECHNICIAN_V2` | B6 Rev2 |
| §3 group B: DEFER, not authorized | Authorized by D3 and implemented | D3; B6 / B6 Rev2 |
| §5 PENDING: V2 assignment on CLOSED jobs | DECIDED: rejected, 409 `TECHNICIAN_ASSIGNMENT_JOB_CLOSED`; safe replay retained (R1-9) | D1 |
| §5 PENDING: V2 empty-set unassignment | DECIDED: whole-assignment withdrawal; job back in U1 as `NONE`, out of My Work; history preserved; reason optional (R1-5 to R1-8) | D2 |
| O3: remove legacy backend only after a dependency review and owner authorization | Still valid; met for the B6 scope by D3 | D3 |

The active requirements are A1-R1 R1-1 to R1-13. They are the owner's 13 listed requirements, verbatim in substance.

## 3. Occurrence audit

Every occurrence of the following terms was checked:
- `TECHNICIAN_ASSIGNMENT_V2_ENABLED` / `technician_assignment_v2_enabled`;
- cutover / OFF;
- legacy backend availability;
- pending CLOSED-job and empty-set decisions;
- dedicated OFF-mode testing;
- Go-live flag activation.

Each occurrence is either inside A1-R1, or carries a SUPERSEDED / DECIDED / "met" marker within the same statement.

One heading is unmarked by design: "A1-§26 — Go-live / cutover". Go-live and the remaining approvals stay active.

No obsolete instruction is presented as an active requirement.

Permanent requirements preserved unchanged:
- TEST/REAL isolation;
- authentication, authorization, idempotency and audit;
- model separation;
- no data migration and no DELETE;
- the C1 §31 suites;
- the C1 §15 fail-closed rules;
- D5 PENDING;
- H3-01 fail-closed.

## 4. No new business decision

A1-R1 records only these:
- the decisions in the owner authorizations for B6 (D1, D2, D3) and for B6 Rev2 (V2 only);
- behaviour verified in the integrated code at `f14e01c0`.

The deployment prerequisites (R4) are existing fail-closed behaviour and existing separate approvals, stated as
facts. No decision is taken on them.

The C1 clause amendments listed in R3 (C1 §12, §13 lock and §24 Q4) follow directly from those decisions. A1's
existing mechanism amends named C1 clauses, so no higher-authority contract had to change.
