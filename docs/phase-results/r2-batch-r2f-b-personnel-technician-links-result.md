# R2 Batch R2f-b — Personnel ↔ Technician Link Writes — Result

Authority: R2f Final Contract Consolidation — Corrected C1 (§5, §15, §16, §17, §19) and the R2f-b implementation
authorization. Baseline: `web/phase7-dashboard-search-reporting` @ `1cce86be97aec41f0b32fbedce27de0c4827a2e8`
(tree `4ebe94c3359c5ba3dac34abc9e5561bd09d674cc`); `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Fake / mock only: no live Google Sheet was read or written, and `personnel_technician_link_history` was not created.

## 1. Scope

Added: LINK / UNLINK / RELINK of the Personnel ↔ Technician relationship, an explicit RECONCILIATION recovery, the
link-history read, uniqueness, stale protection, request replay, mismatch detection, the dedicated capability and
the audit trail. Not added: any account or driver link (no route, repository key or spec), lifecycle gates,
cascades, Repair / PM V2, relationship-edit UI, live schema changes.

## 2. Authority and history

- Current link: `personnel_master.technician_id` (0..1 ↔ 0..1, exact id only). The R2f-a relationship GET keeps
  reading it; there is no second current authority.
- Durable audit: `personnel_technician_link_history`, append-only, frozen header:
  `link_event_id, personnel_id, event_kind, previous_technician_id, new_technician_id, recorded_at, recorded_by,
  request_id, request_fingerprint, reason_th, is_test_data, test_batch_id, related_request_id`.
  Recorded time only (no effective-date backdating). Event kinds LINK, UNLINK, RELINK, RECONCILIATION.
- The tab does not exist live: never auto-created, a missing tab fails closed
  (`PERSONNEL_TECHNICIAN_LINK_HISTORY_SCHEMA_INVALID`), not part of `_CORE_SCHEMAS`.
- Existing links without history are valid baseline state: consistency `NO_HISTORY`; then `CONSISTENT` /
  `MISMATCH` (latest history target vs current cell). No migration.

## 3. Engine

One spec-driven engine (`app/domain/personnel_link.py`, `LinkSpec` / `PersonnelLinkService`); R2f-b registers only
`PERSONNEL_TECHNICIAN_SPEC` (`app/domain/personnel_technician_link.py`). Mutation order: capability → X-Request-Id →
body → reason + operation shape → data context → exact personnel locate in scope → history read + validation →
replay → consistency gate → target validation → stale → operation rule → no-op → W1 history → W2 the one cell.

- LINK: blank → target; same target → no-op; another current target → `..._RELINK_REQUIRED`.
- RELINK: nonblank → different target; same → no-op; blank current → `..._LINK_REQUIRED`.
- UNLINK: nonblank → blank (a truly empty cell); blank → no-op; a target in the body → `..._TARGET_NOT_ALLOWED`.
- Target (LINK / RELINK / reconciliation to a nonblank id): exactly one same-scope technician
  (`TECHNICIAN_NOT_FOUND` 422, `TECHNICIAN_ID_AMBIGUOUS` 409, `TECHNICIAN_SCOPE_UNPROVEN` 422) and not held by
  another in-scope personnel (`TECHNICIAN_ALREADY_LINKED` 409, details: the technician id only).
- Stale (`expected_technician_id`, blank = expects no link) precedes no-op; a broken target is never hidden by a
  no-op.
- Reconciliation: only from MISMATCH (`..._RECONCILIATION_NOT_REQUIRED` otherwise); `related_request_id` must name a
  prior in-scope event of the same personnel whose target is the latest history target
  (`..._RELATED_REQUEST_INVALID`); the target is always the latest history target, never client-chosen.
- No lifecycle gate (OD-5 governs work assignments, not identity links) and no cascade.

## 4. Failure behaviour

W1 rejected → nothing written; W1 unknown → no W2, `{history_write_outcome, request_id}`; W2 failed → the event
stays, MISMATCH, `..._PROJECTION_WRITE_FAILED {event_recorded: true, record_id, request_id}`. No retry, no
compensation. Exact replay succeeds only when not in MISMATCH (otherwise `..._MISMATCH`); a reused id with another
fingerprint is `REQUEST_ID_REUSED`; an unknown-not-applied W1 resend proceeds normally.

## 5. Google Sheets

The personnel locate read is the R2f-a truly bounded column read (header row as metadata + personnel_id,
first_name, last_name, active_status, technician_id, is_test_data, test_batch_id). W2 is ONE `values:batchUpdate`
cell — `technician_id` at the located row, column resolved by header name — as forced exact text, or `""` for
UNLINK. W1 is one append to the history tab.

## 6. API

- `POST /api/v1/personnel/{personnel_id}/technician-links` — `{operation, expected_technician_id,
  new_technician_id?, reason_th}`
- `POST /api/v1/personnel/{personnel_id}/technician-links/reconcile` — `{expected_technician_id,
  related_request_id, reason_th}`
- `GET /api/v1/personnel/{personnel_id}/technician-links/history` (`can_view`)

Writes need `can_link_personnel_technician` (ADMIN via ALL_CAPABILITIES, MAINTENANCE_MANAGER explicitly); 403 has
zero repository calls. No DELETE route.

## 7. Deliberate test amendments

The R2f-a guard `assert_reference_surface_is_read_only` (also used by the three legacy technician guards),
`test_r2fa_08` and `test_r2fa_09` now allow exactly the approved R2f-b surface (four link repository methods with
TECHNICIAN the only key, the link-history tab, the one capability, the three routes) while still proving
technician_master / user_account are read only and no account / driver link exists. The 7O2b / 7O2c exact
MAINTENANCE_MANAGER sets gain `can_link_personnel_technician` (`# R2f-b`).
