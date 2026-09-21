"""AlertSetting (Web/API Phase 6 Batch 5C — Alert Setting Read
Foundation; baseline section 23 "ALERTS", and the still-unresolved parts
of A05/A06/A07/A09/M02 in
`docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`).

LIVE GOOGLE SHEETS SCHEMA — VERIFIED (not guessed): the live "MAINTENANCE"
spreadsheet's `alert_setting` tab already exists with exactly these 13
headers, and already carries live rows (ASET-0001..ASET-0014 at the time
of writing):

    alert_setting_id, scope_type, scope_id, alert_type, enabled,
    threshold_value, threshold_unit, lead_value, lead_unit, muted_until,
    auto_reenable_on_online, setting_status, note_th

`AlertSetting` below carries exactly those fields, one per verified
header, and no other.

BATCH 5C IS READ-ONLY: this module and its service/repository
counterparts only ever READ `alert_setting` — no create/update/delete,
no mute/enable/disable mutation, no precedence resolution, no
"effective setting" computation, no alert generation, and no
DEVICE_OFFLINE/suppression/notification logic. Those all require several
still-unresolved decisions this batch does NOT make (see below) and are
left for a later alert-policy/generation batch.

NO-GUESSING RULE — every one of the following stays a plain opaque
string/passthrough value, exactly like the identical precedent already
established for `Alert.alert_type`/`Alert.source_type` in
`app.domain.alert`:

- `scope_type`: baseline/live data currently only shows `GLOBAL`, but no
  `ScopeType` enum is introduced, and NO precedence between scopes
  (e.g. "GLOBAL < MODEL < VEHICLE") is defined or implied anywhere in
  this module. Alert-setting precedence is explicitly still
  UNRESOLVED — see A07's "does NOT define" list.
- `scope_id`: nullable opaque text reference (blank cell -> `None`).
  Never wildcard semantics in this batch — an absent `scope_id` is not
  interpreted as "applies to every scope"; that interpretation belongs
  to whichever future batch defines precedence/effective-setting
  resolution. May legitimately contain leading zeros; never numerically
  coerced, never used for ordering/uniqueness.
- `alert_type`: same opaque-string treatment as `Alert.alert_type` — no
  `AlertType` enum, no alert_type -> severity mapping (A06 remains
  frozen on vocabulary only).
- `threshold_unit` / `lead_unit`: opaque strings (e.g. `"h"`, `"km"`,
  `"month"`, `"day"` in current live data). No unit system, no unit
  conversion, no cross-unit comparison is implemented here.
- `setting_status`: opaque string (e.g. `"ACTIVE"` in current live
  data). Not the same vocabulary as `AlertStatus`
  (ACTIVE/ACKNOWLEDGED/MUTED/RESOLVED) — no relationship between the two
  is defined or implied.

CONSERVATIVE NULLABILITY: only `alert_setting_id` is required. Every
other field stays honestly `None`/absent when the underlying cell is
blank — nothing here fabricates a default merely because a cell may be
blank, matching the same conservative pattern `app.domain.alert` and
every earlier Phase 6 domain model already established.

`enabled` / `auto_reenable_on_online` are read as a nullable tri-state
bool (`TRUE`/`FALSE`/blank -> `True`/`False`/`None`), never coerced to a
default `False` for a blank cell.

`auto_reenable_on_online` IS READ VERBATIM AND NOT INTERPRETED. In
particular this module does NOT equate it with "auto-reenable on
activity" — the two are explicitly different concepts (see A07's own
"does NOT define" list) — and no behavior is attached to this column
anywhere in this batch; it is stored and returned exactly as the sheet
holds it, nothing more.

`threshold_value` / `lead_value` are nullable numeric values (not
required to be integers) with NO unit conversion, NO cross-field
comparison, and NO use of `A05`'s live `DEVICE_OFFLINE` row
(`threshold_value=24`, `threshold_unit=h`) as anything beyond a value
this batch can read back unchanged. A05 (Device Online/Offline
Threshold — heartbeat interval, grace period, recovery rule) remains
TBD-BLOCKING; this batch does not declare 24 hours a frozen system-wide
policy and implements no heartbeat/grace/recovery behavior.

`muted_until` is a nullable, timezone-aware datetime when present. This
batch does not interpret it (no mute-expiry reconciliation, no
suppression) — see `app.domain.alert_service` for the unrelated
`Alert.muted_until` lifecycle field this is not connected to.

UPDATE (Web/API Phase 6 Batch 5D): D26 (A11, APPROVED/FROZEN — see
`docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt`) has since
frozen GLOBAL-only effective-setting eligibility/scope-matching/conflict
behavior and DEVICE_OFFLINE operational-status suppression, implemented
in `app.domain.alert_setting_service.AlertSettingService.
get_effective_global_setting`/`should_suppress_device_offline`. This
module (`AlertSetting` itself, and the repository/read layer) is
UNCHANGED by D26 — still read-only, still the identical verified
13-column schema, still every field an opaque passthrough with no
enum/precedence attached at the model layer. The paragraph below is kept
for historical accuracy about Batch 5C's own (still-correct, narrower)
scope; see `alert_setting_service.py`'s own module docstring for exactly
what D26 does and does not resolve.

STILL PENDING for a later alert-policy/generation batch (never silently
decided by Batch 5C, and NOT resolved by D26 either):

- MODEL/VEHICLE alert-setting scope precedence (D26 only defines
  GLOBAL-only matching; a MODEL/VEHICLE row is never usable and no
  hierarchy/fallback is invented),
- the DEVICE_OFFLINE heartbeat/grace/recovery rule and online/offline
  detection itself (A05 — D26's suppression table only answers a
  suppression-policy question given an already-known vehicle status),
- the behavioral meaning of `auto_reenable_on_online` (D26 explicitly
  assigns it none — still read-only metadata),
- alert_type -> severity mapping (A06),
- public alert-setting mutation RBAC (M02 — no write permission exists
  yet, and none is added here)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AlertSetting(BaseModel):
    """One row of `alert_setting` — mirrors the verified live tab 1:1.
    Read-only in Batch 5C: nothing in this repository/service layer ever
    creates, updates, or deletes an `AlertSetting`."""

    alert_setting_id: str
    scope_type: str | None = None
    scope_id: str | None = None
    """Opaque passthrough string — may legitimately contain leading
    zeros; never numerically coerced, never used for ordering/uniqueness,
    never treated as a wildcard when blank (Alert `source_id` /
    `Alert.source_type` precedent in `app.domain.alert`)."""
    alert_type: str | None = None
    enabled: bool | None = None
    threshold_value: float | None = None
    threshold_unit: str | None = None
    lead_value: float | None = None
    lead_unit: str | None = None
    muted_until: datetime | None = None
    auto_reenable_on_online: bool | None = None
    """Read and stored verbatim — NOT interpreted as "auto-reenable on
    activity" or any other behavior by this batch. See module docstring."""
    setting_status: str | None = None
    note_th: str | None = None


__all__ = ["AlertSetting"]
