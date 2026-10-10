# R2 Batch R2f-c — Personnel ↔ User Account Link Writes — Result

Authority: R2f Final Contract Consolidation — Corrected C1 (§6, §15, §16, §17, §19) and the R2f-c implementation
authorization. Baseline: `web/phase7-dashboard-search-reporting` @ `7d5797c6e4642cc2da728e811e50697ecec795d0`
(tree `005adef5d1636dc4be47a41058e118b1b854c687`); `main` @ `af75b548b7f99e3b2da90654a27bfdb4a2e590ae`.

Fake / mock only: no live Google Sheet was read or written, and `personnel_account_link_history` was not created.

## 1. Scope

Added: LINK / UNLINK / RELINK of the Personnel ↔ User Account relationship, explicit RECONCILIATION, the
account-link history read, uniqueness, stale protection, request replay, mismatch handling, the dedicated
`can_link_personnel_account` capability, and capability-gated visibility of the raw linked `user_id`. Not added:
account provisioning, deletion, passwords, MFA, roles, email / phone / status changes or the auth cutover (R11);
any user_account write; any driver link; lifecycle gates; cascades; relationship-edit UI; live schema changes.

## 2. Reuse of the R2f-b engine

The integrated `PersonnelLinkService` / `LinkSpec` is reused unchanged in behaviour; R2f-c adds only
`PERSONNEL_ACCOUNT_SPEC` (`app/domain/personnel_account_link.py`). The one engine change is two explicit spec fields
(`target_tab`, `target_read_prefix`) replacing a name derived from the label, so the account target reports
`user_account` / `USER_ACCOUNT_*` like the R2f-a reader; the technician spec sets them to its previous values
(`technician_master`, `TECHNICIAN_MASTER`), so R2f-b behaviour is byte-identical.

## 3. Authority and history

- Current link: `personnel_master.user_id` (0..1 ↔ 0..1, exact id only). The linked `user_id` is the SUBJECT; the
  history's `recorded_by` is always the authenticated actor.
- Audit: `personnel_account_link_history`, append-only, frozen header `link_event_id, personnel_id, event_kind,
  previous_user_id, new_user_id, recorded_at, recorded_by, request_id, request_fingerprint, reason_th,
  is_test_data, test_batch_id, related_request_id`. Not live, never auto-created, fails closed when missing, not in
  `_CORE_SCHEMAS`. Existing user_id values with no history are valid (`NO_HISTORY`); no migration.

## 4. Rules (as R2f-b)

Order: capability → X-Request-Id → body → reason / operation shape → data context → exact personnel locate in scope →
history validation → replay → consistency → target validation (`USER_ACCOUNT_NOT_FOUND` 422,
`USER_ACCOUNT_ID_AMBIGUOUS` 409, `USER_ACCOUNT_SCOPE_UNPROVEN` 422) → uniqueness (`USER_ACCOUNT_ALREADY_LINKED` 409,
details: the user id only) → stale (`PERSONNEL_ACCOUNT_LINK_STALE`, before no-op) → operation rule
(`_RELINK_REQUIRED` / `_LINK_REQUIRED`) → no-op → W1 history → W2 the one `user_id` cell. W1 rejected / unknown → no
W2; W2 failed → event kept, MISMATCH, explicit reconciliation (target = latest history target; `related_request_id`
must name a prior in-scope event of the same personnel with that target). No retry, no compensation. A live TEST
link fails closed whatever the id text looks like (e.g. `TEST-USER-1`).

## 5. Raw user_id visibility (C1 §16)

- `GET /personnel/{id}/relationships`: `account` is `{resolution}` for a `can_view` caller; a holder of
  `can_link_personnel_account` also gets `user_id` (the exact personnel cell; null = UNSET).
- `GET /personnel/{id}/account-links/history` (`can_view`): `user_ids_visible` is true only for a holder; otherwise
  every user id field is null because it is redacted (not unset).
- No other account field (name, email, phone, role, MFA, status) is ever returned or read.

## 6. Google Sheets

Locate read: the R2f-a truly bounded column read of personnel_id, first_name, last_name, active_status, user_id,
is_test_data, test_batch_id (no technician_id / department / position / branch / note). Target read: user_account
`user_id` only. W2: ONE cell — `user_id` at the located row, column by header name — as forced exact text, or `""`
for UNLINK. user_account is never written.

## 7. API

- `POST /api/v1/personnel/{personnel_id}/account-links` — `{operation, expected_user_id, new_user_id?, reason_th}`
- `POST /api/v1/personnel/{personnel_id}/account-links/reconcile` — `{expected_user_id, related_request_id, reason_th}`
- `GET /api/v1/personnel/{personnel_id}/account-links/history` (`can_view`)

Writes need `can_link_personnel_account` (ADMIN via ALL_CAPABILITIES, MAINTENANCE_MANAGER explicitly); 403 has zero
repository calls. No DELETE route; no account administration route.

## 8. Deliberate test amendments

The shared R2f-a guard now expects `PERSONNEL_LINKS == (TECHNICIAN, ACCOUNT)` and still proves technician_master /
user_account are read only and no driver link exists (also used by the three legacy technician guards).
`test_r2fa_08` expects both link capabilities and no driver capability; `test_r2fa_08_api_redacts_the_raw_user_id`
proves the redaction for a can_view-only caller and visibility for a holder; four R2f-a Sheets assertions compare
the account resolution (their ADMIN caller now also sees user_id). Two R2f-b assertions that forbade account-link
routes now forbid driver-link routes only. The 7O2b / 7O2c exact MAINTENANCE_MANAGER sets gain
`can_link_personnel_account`.

## 9. Known prototype limitation (unchanged)

Google Sheets has no cross-row compare-and-set or unique constraint; uniqueness and stale checks run before W1/W2,
so truly concurrent writers could race. Accepted for the prototype; to be revisited with PostgreSQL.
