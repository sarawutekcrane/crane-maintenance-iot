"""Alert service (Web/API Phase 6 Batch 5A — Alert Read Foundation; Batch
5B — Alert Lifecycle Core). See `app.domain.alert` for the
`Alert`/`AlertSeverity`/`AlertStatus` models.

Batch 5A responsibilities: validate a requested vehicle exists before
listing its alerts, fetch one alert by id (404-style `ApiError` when
missing, matching every other Phase 6 domain's not-found pattern), and
provide a DETERMINISTIC display ordering for a vehicle's alert list.

That ordering (`created_at` descending, `alert_id` ascending as the final
tie-break) is technical/display determinism only — it is not a ranking
by severity or an importance judgment.

Batch 5B responsibilities (D25, APPROVED/FROZEN — see
`docs/project-governance/OPEN_DECISIONS_REGISTER_EN.txt` A07): the
open-alert identity/dedup, acknowledge, mute, mute-expiry, and
source-driven-resolve lifecycle, as INTERNAL methods only —
`ensure_condition_alert`/`acknowledge_alert`/`mute_alert`/
`reconcile_mute_expiry`/`resolve_condition_alert`. None of these is
reachable from any HTTP route in this batch (see `app.api.v1.alerts`,
unchanged): the live `role_permission` schema still has no dedicated
alert-write permission, so no mutation endpoint is added here. Callers
of these methods are internal (future generation/reconciliation jobs),
never a route handler, in this batch.

D25 explicitly repeats the same non-transactional-writes caveat every
earlier Phase 6 write path already accepts (A09, still unresolved):
Google Sheets offers no real transaction, so two racing
`ensure_condition_alert` calls for the same identity can each observe
"no open alert yet" before either write lands, leaving two open rows
for one identity. This service never guesses which of those rows is
canonical — see `ensure_condition_alert`'s `ALERT_OPEN_IDENTITY_CONFLICT`
below."""
from __future__ import annotations

from datetime import datetime

from fastapi import status

from app.domain.alert import Alert, AlertSeverity, AlertStatus
from app.domain.common import utc_now
from app.errors import ApiError
from app.repositories.base import Repository, RepositoryError

_OPEN_ALERT_STATUSES = frozenset(
    {AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED, AlertStatus.MUTED}
)


def _canonical_source_value(value: str | None) -> str | None:
    """B5B-02 review fix. `source_type`/`source_id` are part of D25's
    open-identity tuple, where A07 already states a missing value is
    "missing identity", never a wildcard. `None` and an empty/whitespace-
    only string are both "missing" and must canonicalize to the SAME
    `None` here, at the one boundary every `ensure_condition_alert` call
    passes through — otherwise `""` vs. `None` can silently diverge:
    `MockRepository` would retain a literal `""`, while
    `GoogleSheetsRepository` persists a blank cell that reads back as
    `None` (the accepted Batch 5A parser, `row.get(...) or None`), so the
    same logical identity could dedupe differently depending on which
    repository is behind it or whether a row was just read back after a
    restart. A non-blank value is returned EXACTLY as given — never
    trimmed — so an opaque value like `"000009"` is unaffected."""
    if value is None:
        return None
    return value if value.strip() else None


class AlertService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def _require_vehicle_exists(self, vehicle_id: str) -> None:
        vehicle = await self._repository.get_vehicle(vehicle_id)
        if vehicle is None:
            raise ApiError(
                code="VEHICLE_NOT_FOUND",
                message=f"Vehicle '{vehicle_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    async def get_alert(self, alert_id: str) -> Alert:
        alert = await self._repository.get_alert(alert_id)
        if alert is None:
            raise ApiError(
                code="ALERT_NOT_FOUND",
                message=f"Alert '{alert_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return alert

    async def list_for_vehicle(self, vehicle_id: str) -> list[Alert]:
        await self._require_vehicle_exists(vehicle_id)
        alerts = await self._repository.list_alerts_for_vehicle(vehicle_id)
        return sorted(
            alerts,
            key=lambda a: (-a.created_at.timestamp(), a.alert_id),
        )

    # ---- Lifecycle (Web/API Phase 6 Batch 5B — D25, internal only) ----

    async def ensure_condition_alert(
        self,
        *,
        alert_id: str,
        vehicle_id: str,
        alert_type: str,
        source_type: str | None,
        source_id: str | None,
        severity: AlertSeverity | None,
        created_at: datetime,
        message_th: str | None,
    ) -> Alert:
        """D25 open-identity dedup. Looks up existing rows (any status)
        by `(vehicle_id, alert_type, source_type, source_id)`:

        - exactly one OPEN (ACTIVE/ACKNOWLEDGED/MUTED) row already
          matches -> that unchanged row is returned as-is (idempotent
          reuse; this call's `severity`/`created_at`/`message_th`/
          `alert_id` are never applied to it)
        - more than one OPEN row matches -> `ALERT_OPEN_IDENTITY_CONFLICT`
          (only reachable via the non-transactional-write race described
          in this module's docstring; never silently resolved by
          guessing which row is canonical)
        - zero OPEN rows match -> a brand-new ACTIVE row is created using
          the caller-supplied `alert_id` (never generated here — see A01)
        """
        await self._require_vehicle_exists(vehicle_id)
        if not alert_id or not alert_id.strip():
            raise ApiError(
                code="ALERT_ID_REQUIRED",
                message="alert_id is required",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if not alert_type or not alert_type.strip():
            raise ApiError(
                code="ALERT_TYPE_REQUIRED",
                message="alert_type is required",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if created_at.tzinfo is None:
            raise ApiError(
                code="ALERT_CREATED_AT_NOT_TZ_AWARE",
                message="created_at must be timezone-aware",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        # B5B-02: canonicalize before either use below (the identity
        # lookup AND the newly-created Alert's own fields), so both
        # repositories are always given the same missing-value
        # representation regardless of whether the caller passed `None`
        # or `""`.
        source_type = _canonical_source_value(source_type)
        source_id = _canonical_source_value(source_id)

        identity_rows = await self._repository.list_alerts_by_identity(
            vehicle_id, alert_type, source_type, source_id
        )
        open_rows = [a for a in identity_rows if a.alert_status in _OPEN_ALERT_STATUSES]
        if len(open_rows) > 1:
            raise ApiError(
                code="ALERT_OPEN_IDENTITY_CONFLICT",
                message=(
                    f"{len(open_rows)} open alerts already exist for identity "
                    f"(vehicle_id={vehicle_id!r}, alert_type={alert_type!r}, "
                    f"source_type={source_type!r}, source_id={source_id!r}) — "
                    "refusing to guess which row is canonical"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"open_alert_ids": [a.alert_id for a in open_rows]},
            )
        if len(open_rows) == 1:
            return open_rows[0]

        existing_by_id = await self._repository.get_alert(alert_id)
        if existing_by_id is not None:
            raise ApiError(
                code="ALERT_ID_ALREADY_EXISTS",
                message=f"Alert '{alert_id}' already exists",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        new_alert = Alert(
            alert_id=alert_id,
            vehicle_id=vehicle_id,
            alert_type=alert_type,
            source_type=source_type,
            source_id=source_id,
            severity=severity,
            created_at=created_at,
            alert_status=AlertStatus.ACTIVE,
            message_th=message_th,
        )
        return await self._repository.create_alert(new_alert)

    async def acknowledge_alert(self, alert_id: str, acknowledged_by_user_id: str) -> Alert:
        """D25: ACTIVE -> ACKNOWLEDGED only. Idempotent on an already-
        ACKNOWLEDGED alert — the original `acknowledged_by_user_id`/
        `acknowledged_at` provenance is preserved, never overwritten by
        a later caller. MUTED/RESOLVED -> ACKNOWLEDGED are rejected."""
        if not acknowledged_by_user_id or not acknowledged_by_user_id.strip():
            raise ApiError(
                code="ALERT_ACKNOWLEDGED_BY_USER_ID_REQUIRED",
                message="acknowledged_by_user_id is required",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        alert = await self.get_alert(alert_id)
        if alert.alert_status == AlertStatus.ACKNOWLEDGED:
            return alert
        if alert.alert_status != AlertStatus.ACTIVE:
            raise ApiError(
                code="ALERT_ACKNOWLEDGE_INVALID_TRANSITION",
                message=(
                    f"Alert '{alert_id}' cannot be acknowledged from status "
                    f"{alert.alert_status}"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return await self._repository.update_alert_lifecycle(
            alert_id,
            alert_status=AlertStatus.ACKNOWLEDGED,
            muted_until=alert.muted_until,
            acknowledged_by_user_id=acknowledged_by_user_id,
            acknowledged_at=utc_now(),
            resolved_at=alert.resolved_at,
        )

    async def mute_alert(self, alert_id: str, muted_until: datetime) -> Alert:
        """D25: ACTIVE/ACKNOWLEDGED -> MUTED, with a caller-supplied,
        timezone-aware, strictly-future `muted_until` — there is no
        default/implied mute duration. Idempotent only if `muted_until`
        exactly matches the already-stored value on an already-MUTED
        alert; a different `muted_until` on a MUTED alert is rejected
        rather than silently overwritten. RESOLVED -> MUTED is
        rejected."""
        if muted_until.tzinfo is None:
            raise ApiError(
                code="ALERT_MUTED_UNTIL_NOT_TZ_AWARE",
                message="muted_until must be timezone-aware",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if muted_until <= utc_now():
            raise ApiError(
                code="ALERT_MUTED_UNTIL_NOT_FUTURE",
                message="muted_until must be strictly in the future",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        alert = await self.get_alert(alert_id)
        if alert.alert_status == AlertStatus.MUTED:
            if alert.muted_until == muted_until:
                return alert
            raise ApiError(
                code="ALERT_MUTE_CONFLICTING_MUTED_UNTIL",
                message=(
                    f"Alert '{alert_id}' is already MUTED until "
                    f"{alert.muted_until} — refusing to silently overwrite "
                    f"it with a different muted_until"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if alert.alert_status not in (AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED):
            raise ApiError(
                code="ALERT_MUTE_INVALID_TRANSITION",
                message=f"Alert '{alert_id}' cannot be muted from status {alert.alert_status}",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return await self._repository.update_alert_lifecycle(
            alert_id,
            alert_status=AlertStatus.MUTED,
            muted_until=muted_until,
            acknowledged_by_user_id=alert.acknowledged_by_user_id,
            acknowledged_at=alert.acknowledged_at,
            resolved_at=alert.resolved_at,
        )

    async def reconcile_mute_expiry(self, alert_id: str) -> Alert:
        """D25: a MUTED alert whose `muted_until` has passed transitions
        to ACKNOWLEDGED if it was ever acknowledged (`acknowledged_at` is
        set), otherwise back to ACTIVE. `muted_until` itself is preserved
        (never cleared) as a historical record. A non-MUTED alert is a
        no-op. A MUTED alert with a missing `muted_until` is corrupt
        persisted state and fails honestly (`RepositoryError`) rather
        than guessing an expiry — the same "never fabricate" pattern
        `GoogleSheetsRepository._require_alert_created_at` already
        established (B5A-01)."""
        alert = await self.get_alert(alert_id)
        if alert.alert_status != AlertStatus.MUTED:
            return alert
        if alert.muted_until is None:
            raise RepositoryError(
                f"Alert '{alert_id}' is MUTED but has no muted_until value — "
                "refusing to guess an expiry."
            )
        if utc_now() < alert.muted_until:
            return alert
        new_status = (
            AlertStatus.ACKNOWLEDGED if alert.acknowledged_at is not None else AlertStatus.ACTIVE
        )
        return await self._repository.update_alert_lifecycle(
            alert_id,
            alert_status=new_status,
            muted_until=alert.muted_until,
            acknowledged_by_user_id=alert.acknowledged_by_user_id,
            acknowledged_at=alert.acknowledged_at,
            resolved_at=alert.resolved_at,
        )

    async def resolve_condition_alert(self, alert_id: str) -> Alert:
        """D25: source-driven resolution only — ACTIVE, ACKNOWLEDGED, or
        MUTED all transition to RESOLVED. Idempotent: resolving an
        already-RESOLVED alert is a no-op that preserves the original
        `resolved_at`. RESOLVED is terminal — nothing in this service
        ever reopens a resolved alert; recurrence of the same underlying
        condition is `ensure_condition_alert` creating a brand-new row
        with a new `alert_id` once no open row for that identity remains
        (the resolved row is no longer "open")."""
        alert = await self.get_alert(alert_id)
        if alert.alert_status == AlertStatus.RESOLVED:
            return alert
        if alert.alert_status not in _OPEN_ALERT_STATUSES:
            raise ApiError(
                code="ALERT_RESOLVE_INVALID_TRANSITION",
                message=f"Alert '{alert_id}' cannot be resolved from status {alert.alert_status}",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return await self._repository.update_alert_lifecycle(
            alert_id,
            alert_status=AlertStatus.RESOLVED,
            muted_until=alert.muted_until,
            acknowledged_by_user_id=alert.acknowledged_by_user_id,
            acknowledged_at=alert.acknowledged_at,
            resolved_at=utc_now(),
        )


# ===========================================================================
# R7 Whole-Phase Mock/TEST (Owner source/policy gate 2026-11-17; policy R1 §5,
# P-6 … P-13). Everything below REUSES the unchanged D25 methods above — no second
# state machine — and adds: the three approved alert types and identities, the
# explicit TEST evaluation, ACK / MUTE with a Mock-only append-only audit log and
# replay repair, the central read, provenance and verified source links.
#
# Never: a scheduler, a write on any GET, a REAL / Google Sheets write, a NEAR_DUE
# window, lead days, notification, recipient routing, manual RESOLVE.
# ===========================================================================

import hashlib  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from urllib.parse import quote  # noqa: E402

ALERT_TYPE_PM_DUE = "PM_DUE"
ALERT_TYPE_PART_LIFETIME_DUE = "PART_LIFETIME_DUE"
ALERT_TYPE_CERTIFICATE_EXPIRED = "CERTIFICATE_EXPIRED"
SOURCE_TYPE_PM_DUE_SET = "PM_DUE_SET"
SOURCE_TYPE_PART_LIFETIME_DUE_KEY = "PART_LIFETIME_DUE_KEY"
SOURCE_TYPE_VEHICLE_CERTIFICATE = "VEHICLE_CERTIFICATE"
# P-6: the exact approved (alert_type -> source_type) pairs; severity WARNING for each
# (a per-type choice inside the D24 vocabulary — not D24 itself).
R7_ALERT_SOURCE_TYPES: dict[str, str] = {
    ALERT_TYPE_PM_DUE: SOURCE_TYPE_PM_DUE_SET,
    ALERT_TYPE_PART_LIFETIME_DUE: SOURCE_TYPE_PART_LIFETIME_DUE_KEY,
    ALERT_TYPE_CERTIFICATE_EXPIRED: SOURCE_TYPE_VEHICLE_CERTIFICATE,
}
R7_ALERT_SEVERITY = AlertSeverity.WARNING

DUE_STATE = "DUE"
NOT_DUE_STATE = "NOT_DUE"
UNKNOWN_STATE = "UNKNOWN"

ACTION_ACKNOWLEDGE = "ACKNOWLEDGE"
ACTION_MUTE = "MUTE"
ACTION_EVALUATE = "EVALUATE"
EVENT_INTENT = "INTENT"
EVENT_COMMIT = "COMMIT"
EVENT_ABORT = "ABORT"
EVENT_EVALUATION = "EVALUATION"
MAX_REASON_LENGTH = 500

PROVENANCE_NOT_CONFIGURED = "NOT_CONFIGURED"
PROVENANCE_CONFLICT = "SETTING_CONFLICT"
PROVENANCE_NOT_EVALUATED = "NOT_EVALUATED"
PROVENANCE_EVALUATED_NONE = "EVALUATED_NONE"
PROVENANCE_ALERTS = "ALERTS"
PROVENANCE_UNAVAILABLE = "UNAVAILABLE"
# Independent-review correction C2: the latest evaluation of this type did NOT prove a complete
# source enumeration (source incomplete / read failed / UNKNOWN items / identity conflicts or id
# collisions). It is never shown as a verified zero.
PROVENANCE_SOURCE_INCOMPLETE = "SOURCE_INCOMPLETE"
PROVENANCE_ALERTS_SOURCE_INCOMPLETE = "ALERTS_SOURCE_INCOMPLETE"


def _outcome_proves_complete(outcome: dict) -> bool:
    """'Verified zero' needs a successful COMPLETE source enumeration with nothing left
    unknown and no unresolved identity conflict or id collision."""
    if outcome.get("source") != "COMPLETE":
        return False
    for key in ("unknown", "conflicts", "collisions"):
        value = outcome.get(key)
        if not isinstance(value, int) or value != 0:
            return False
    return True


def new_alert_id() -> str:
    """P-8c (an R7-local proposal, not A01 for other entities): backend-generated opaque id."""
    return f"ALT-{uuid.uuid4().hex}"


def mute_expired(alert: Alert, now: datetime | None = None) -> bool:
    """P-9c: a DERIVED read flag — never a write. True for a MUTED alert whose
    `muted_until` has passed (D25 reconciliation happens only inside an action or
    an evaluation)."""
    if alert.alert_status != AlertStatus.MUTED or alert.muted_until is None:
        return False
    return (now or utc_now()) >= alert.muted_until


@dataclass(frozen=True)
class SourceObservation:
    source_id: str
    state: str  # DUE | NOT_DUE | UNKNOWN
    message_th: str


@dataclass
class SourceRead:
    """`complete` is True ONLY when the source read succeeded and covered every candidate
    identity of this vehicle and type (P-8 resolve-on-absence precondition)."""

    complete: bool
    observations: list[SourceObservation] = field(default_factory=list)
    reason: str | None = None
    # D3: certificates whose successor could not be verified ({source_id, reason}).
    not_resolved: list[dict[str, str]] = field(default_factory=list)
    # IR-C7: whether the ABSENCE of an identity from this source can ever be proof (False for
    # certificates: D3 — a missing row is never proof), and the reason when it cannot.
    absence_is_proof: bool = True
    absence_block_reason: str | None = None


ABSENCE_APPLIED = "APPLIED"
ABSENCE_NOT_APPLICABLE = "NOT_APPLICABLE"


SUCCESSOR_TYPE_UNKNOWN = "SUCCESSOR_TYPE_UNKNOWN"
SUCCESSOR_EVIDENCE_INCOMPLETE = "SUCCESSOR_EVIDENCE_INCOMPLETE"
SUCCESSOR_NOT_VALID_ACTIVE = "SUCCESSOR_NOT_VALID_ACTIVE"
SUCCESSOR_CHRONOLOGY_UNPROVEN = "SUCCESSOR_CHRONOLOGY_UNPROVEN"
SUCCESSOR_AMBIGUOUS = "SUCCESSOR_AMBIGUOUS"


def _verified_successor(old, certificates, vehicle_id: str, as_of):
    """Owner decision D3 (VERIFIED_ACTIVE_SUCCESSOR). Returns (successor, None) only when
    EXACTLY ONE other certificate of the SAME vehicle and the EXACT same (non-blank)
    certificate_type_code is stored ACTIVE, is effectively ACTIVE today, is in effect
    (issue date, when present, not in the future and not after its expiry) and is provably
    newer (its expiry strictly after the old expiry; issue dates, when both present, not
    earlier) — with no same-type row of unknown status or missing dates and no contradicting
    `replaced_by_certificate_id`. Otherwise (None, reason) — never a guess."""
    from app.domain.certificate_expiry_report import report_effective_status
    from app.domain.vehicle_certificate import CertificateStatus

    old_type = old.certificate_type_code
    if old_type is None or not old_type.strip() or old.vehicle_id != vehicle_id:
        return None, SUCCESSOR_TYPE_UNKNOWN if len(certificates) > 1 else None
    siblings = [c for c in certificates if c.certificate_id != old.certificate_id
                and c.certificate_type_code == old_type]
    if not siblings:
        return None, None  # nothing newer at all: the expired condition simply stands
    if any(c.vehicle_id != vehicle_id or c.certificate_status is None for c in siblings):
        return None, SUCCESSOR_EVIDENCE_INCOMPLETE
    valid_active = [c for c in siblings if c.certificate_status == CertificateStatus.ACTIVE
                    and report_effective_status(c.certificate_status.value, c.expiry_date, as_of)
                    == CertificateStatus.ACTIVE.value]
    if not valid_active:
        return None, SUCCESSOR_NOT_VALID_ACTIVE  # e.g. a merely expired second certificate
    if old.expiry_date is None or any(c.expiry_date is None for c in valid_active):
        return None, SUCCESSOR_EVIDENCE_INCOMPLETE
    newer = []
    for c in valid_active:
        if c.issue_date is not None and (c.issue_date > as_of or c.issue_date > c.expiry_date):
            continue
        if old.issue_date is not None and c.issue_date is not None and c.issue_date < old.issue_date:
            continue
        if c.expiry_date > old.expiry_date:
            newer.append(c)
    if not newer:
        return None, SUCCESSOR_CHRONOLOGY_UNPROVEN
    if len(valid_active) > 1:
        return None, SUCCESSOR_AMBIGUOUS  # two concurrently valid rows of one type: never pick one
    (successor,) = newer
    link = (old.replaced_by_certificate_id or "").strip()
    if link and link != successor.certificate_id:
        return None, SUCCESSOR_AMBIGUOUS
    return successor, None


def _forbidden(code: str, message: str) -> ApiError:
    return ApiError(code=code, message=message, status_code=status.HTTP_403_FORBIDDEN)


class R7AlertService:
    """R7 Whole-Phase Mock/TEST alert operations (policy R1 §5). The R4 PM Due read
    model, the R6 part lifetime read model and the read-only certificate expiry
    predicate are consumed as they are — no formula is duplicated here."""

    def __init__(self, repository: Repository, settings, pm_service, part_status_service) -> None:
        self._repository = repository
        self._settings = settings
        self._pm = pm_service
        self._parts = part_status_service
        self._alerts = AlertService(repository)

    # ---- authority (C-1 … C-3) ----

    def _require_test_authority(self, context, capability: str, action_th: str) -> None:
        """Mock (501) -> TEST context (403) -> AM-verified employee (403) -> the named
        TEST grant AND can_view (403). Nothing is read before this passes."""
        from app.config import DataRepositoryMode
        from app.domain import authz

        if self._settings.data_repository != DataRepositoryMode.MOCK:
            raise ApiError(code="FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE",
                           message="TEST alert actions are available only in the synthetic Mock/TEST repository",
                           status_code=status.HTTP_501_NOT_IMPLEMENTED, details={"feature": "test_alert_action"})
        if self._settings.registry_context_effective != "TEST":
            raise _forbidden("ALERT_ACTION_TEST_ONLY", f"{action_th} is available only in the TEST data context")
        if getattr(context, "access", None) is None or not getattr(context, "personnel_id", None) \
                or not (context.user_id or "").strip():
            raise _forbidden("ACCESS_ACTOR_NOT_VERIFIED",
                             f"{action_th} requires an active TEST employee linked to exactly one account")
        if capability not in context.capabilities or authz.CAN_VIEW not in context.capabilities:
            raise _forbidden("ALERT_ACTION_NOT_AUTHORIZED",
                             f"{action_th} requires the '{capability}' grant and 'can_view'")

    async def _require_test_vehicle(self, vehicle_id: str) -> None:
        from app.domain.attachment_service import require_test_vehicle_parent

        await require_test_vehicle_parent(self._repository, self._settings, vehicle_id)

    async def _test_vehicle_ids(self) -> list[str]:
        """Every vehicle that resolves in the server's TEST scope AND has a vehicle record."""
        from app.domain.technician_assignment import cutover_from_settings

        cutover = cutover_from_settings(self._settings)
        reference = await self._repository.read_vehicle_reference()
        ids: list[str] = []
        for row in reference.rows:
            vehicle_id = dict(row.values).get("vehicle_id") or ""
            if row.scope != "TEST" or row.test_batch_id != cutover.test_batch_id or not vehicle_id:
                continue
            try:
                await self._require_test_vehicle(vehicle_id)
            except ApiError:
                continue
            if await self._repository.get_vehicle(vehicle_id) is not None:
                ids.append(vehicle_id)
        return sorted(dict.fromkeys(ids))

    # ---- source reads (P-8; R7-09 single read models) ----

    async def _read_pm(self, context, vehicle_id: str) -> SourceRead:
        try:
            row = await self._pm.read_vehicle_pm_due(context, vehicle_id)
        except Exception as exc:  # noqa: BLE001 - any failure leaves the enumeration incomplete
            return SourceRead(False, reason=f"PM_READ_FAILED:{type(exc).__name__}")
        observations = [SourceObservation(f"{s.plan_code}|{s.set_key}",
                                          s.status if s.status in (DUE_STATE, NOT_DUE_STATE) else UNKNOWN_STATE,
                                          f"PM ถึงกำหนด: แผน {s.plan_code} ชุดงาน {s.set_code} ({s.section})")
                        for s in row.sets]
        complete = row.state == "AVAILABLE" and all(p.state in ("RESOLVED", "NO_APPLICABLE_SET") for p in row.plans)
        return SourceRead(complete, observations, None if complete else f"PM_STATE:{row.state}")

    async def _read_parts(self, vehicle_id: str) -> SourceRead:
        from app.domain.asset import AssetType

        try:
            summary = await self._parts.asset_summary(AssetType.VEHICLE, vehicle_id)
        except Exception as exc:  # noqa: BLE001
            return SourceRead(False, reason=f"PART_READ_FAILED:{type(exc).__name__}")
        observations: list[SourceObservation] = []

        def add(target: dict) -> None:
            for result in target.get("rules", ()):
                key = result.get("due_key") or ""
                if not key:
                    continue
                state = result.get("status")
                label = " [TEST_PROPOSED]" if result.get("policy_state") == "TEST_PROPOSED" else ""
                observations.append(SourceObservation(
                    key, state if state in (DUE_STATE, NOT_DUE_STATE) else UNKNOWN_STATE,
                    f"อะไหล่ถึงกำหนด ({result.get('due_action') or '-'}): {target.get('target_type')} "
                    f"{target.get('target_id')}{label}"))

        for instance in summary.get("instances", ()):
            add(instance)
            for position in instance.get("hosted_positions", ()):
                add(position)
        for position in summary.get("positions", ()):
            add(position)
        return SourceRead(True, observations)

    async def _read_certificates(self, vehicle_id: str) -> SourceRead:
        """The read-only report predicate on repository rows — never the legacy
        certificate service (whose reads write, R7-10). Expiry-only; no lead days.

        Owner decision D3 (VERIFIED_ACTIVE_SUCCESSOR, 2026-11-17): an expired (or REPLACED)
        certificate's condition closes ONLY on proof of a verified successor
        (`_verified_successor`). Without that proof an expired certificate stays DUE and a
        REPLACED one is UNKNOWN (no create, no resolve); the unprovable case is reported in
        `not_resolved`. No row is written, linked or inferred."""
        from app.domain.certificate_expiry_report import report_effective_status
        from app.domain.common import bangkok_today
        from app.domain.vehicle_certificate import CertificateStatus

        try:
            certificates = await self._repository.list_vehicle_certificates_for_vehicle(vehicle_id)
        except Exception as exc:  # noqa: BLE001
            return SourceRead(False, reason=f"CERTIFICATE_READ_FAILED:{type(exc).__name__}")
        as_of = bangkok_today()
        observations: list[SourceObservation] = []
        not_resolved: list[dict[str, str]] = []
        for certificate in certificates:
            status_value = certificate.certificate_status
            if status_value is None:
                state = UNKNOWN_STATE
            else:
                closes_by_itself = (status_value == CertificateStatus.ACTIVE and report_effective_status(
                    status_value.value, certificate.expiry_date, as_of) == CertificateStatus.ACTIVE.value)
                if closes_by_itself:
                    state = NOT_DUE_STATE  # the source itself is not expired (D25 source-driven)
                else:
                    successor, reason = _verified_successor(certificate, certificates, vehicle_id, as_of)
                    if successor is not None:
                        state = NOT_DUE_STATE
                    else:
                        state = UNKNOWN_STATE if status_value == CertificateStatus.REPLACED else DUE_STATE
                        if reason is not None:
                            not_resolved.append({"source_id": certificate.certificate_id, "reason": reason})
            name = certificate.certificate_type_name_th or certificate.certificate_type_code or "-"
            observations.append(SourceObservation(
                certificate.certificate_id, state,
                f"ใบรับรองหมดอายุ: {name} เลขที่ {certificate.document_no or '-'} "
                f"(หมดอายุ {certificate.expiry_date.isoformat() if certificate.expiry_date else '-'})"))
        return SourceRead(True, observations, not_resolved=not_resolved, absence_is_proof=False,
                          absence_block_reason="CERTIFICATE_ABSENCE_IS_NOT_PROOF")

    async def _read_source(self, context, alert_type: str, vehicle_id: str) -> SourceRead:
        if alert_type == ALERT_TYPE_PM_DUE:
            return await self._read_pm(context, vehicle_id)
        if alert_type == ALERT_TYPE_PART_LIFETIME_DUE:
            return await self._read_parts(vehicle_id)
        return await self._read_certificates(vehicle_id)

    # ---- explicit TEST evaluation (P-7, P-8, P-8b, P-8c) ----

    async def _setting_states(self) -> dict[str, str]:
        from app.domain.alert_setting_service import AlertSettingService

        service = AlertSettingService(self._repository)
        states: dict[str, str] = {}
        for alert_type in R7_ALERT_SOURCE_TYPES:
            try:
                setting = await service.get_effective_global_setting(alert_type)
            except ApiError as exc:
                if exc.code != "ALERT_SETTING_GLOBAL_CONFLICT":
                    raise
                states[alert_type] = PROVENANCE_CONFLICT
                continue
            states[alert_type] = "CONFIGURED" if setting is not None else PROVENANCE_NOT_CONFIGURED
        return states

    async def evaluate(self, context, vehicle_id: str | None, request_id: str) -> dict:
        from app.domain import authz

        self._require_test_authority(context, authz.CAN_RUN_TEST_ALERT_EVALUATION,
                                     "การประเมินการแจ้งเตือน (TEST alert evaluation)")
        if vehicle_id is not None:
            await self._require_test_vehicle(vehicle_id)
            if await self._repository.get_vehicle(vehicle_id) is None:
                raise ApiError(code="VEHICLE_NOT_FOUND", message=f"Vehicle '{vehicle_id}' was not found",
                               status_code=status.HTTP_404_NOT_FOUND)
            vehicle_ids = [vehicle_id]
        else:
            vehicle_ids = await self._test_vehicle_ids()
        settings_state = await self._setting_states()
        outcomes: list[dict] = []
        for vid in vehicle_ids:
            await self._reconcile_expired_mutes(vid)
            for alert_type, source_type in R7_ALERT_SOURCE_TYPES.items():
                outcome = {"vehicle_id": vid, "alert_type": alert_type, "setting": settings_state[alert_type],
                           "source": None, "source_reason": None, "created": 0, "reused": 0, "resolved": 0,
                           "unknown": 0, "conflicts": 0, "collisions": 0, "not_resolved": [],
                           "absence_resolution": ABSENCE_NOT_APPLICABLE}
                if settings_state[alert_type] != "CONFIGURED":
                    outcomes.append(outcome)  # not configured / conflict: no create, no resolve
                    continue
                read = await self._read_source(context, alert_type, vid)
                outcome["source_reason"] = read.reason
                outcome["not_resolved"] = list(read.not_resolved)
                await self._apply(vid, alert_type, source_type, read, outcome)
                # IR-C7: a complete enumeration that still holds UNKNOWN items is not a proven one.
                outcome["source"] = ("INCOMPLETE" if not read.complete
                                     else "COMPLETE_WITH_UNKNOWN" if outcome["unknown"] else "COMPLETE")
                outcomes.append(outcome)
        totals = {key: sum(o[key] for o in outcomes)
                  for key in ("created", "reused", "resolved", "unknown", "conflicts", "collisions")}
        evaluated_at = utc_now()
        event = self._event(EVENT_EVALUATION, ACTION_EVALUATE, request_id, context, alert_id="", vehicle_id="",
                            details={"vehicles": vehicle_ids, "outcomes": outcomes, "totals": totals})
        try:
            await self._repository.append_alert_action_event(event)
        except Exception as exc:  # noqa: BLE001 - never report a fully audited success
            raise ApiError(code="ALERT_ACTION_AUDIT_INCOMPLETE", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                           message="The evaluation changed alerts but its audit record could not be written; "
                                   "re-run the evaluation (it is idempotent) to record it",
                           details={"state_changed": True, "totals": totals}) from exc
        return {"request_id": request_id, "evaluated_at": evaluated_at, "vehicle_ids": vehicle_ids,
                "settings": settings_state, "outcomes": outcomes, "totals": totals}

    async def _reconcile_expired_mutes(self, vehicle_id: str) -> None:
        for alert in await self._repository.list_alerts_for_vehicle(vehicle_id):
            if mute_expired(alert):
                await self._alerts.reconcile_mute_expiry(alert.alert_id)

    async def _apply(self, vehicle_id: str, alert_type: str, source_type: str, read: SourceRead,
                     outcome: dict) -> None:
        open_rows = [a for a in await self._repository.list_alerts_for_vehicle(vehicle_id)
                     if a.alert_type == alert_type and a.source_type == source_type
                     and a.alert_status in _OPEN_ALERT_STATUSES]
        by_source: dict[str, list[Alert]] = {}
        for row in open_rows:
            by_source.setdefault(row.source_id or "", []).append(row)

        async def resolve(source_id: str) -> None:
            rows = by_source.get(source_id, [])
            if len(rows) == 1:
                await self._alerts.resolve_condition_alert(rows[0].alert_id)
                outcome["resolved"] += 1
            elif len(rows) > 1:
                outcome["conflicts"] += 1  # D25: never guess which open row is canonical

        # IR-C7: one identity observed with contradictory states in one read proves neither.
        states_by_id: dict[str, set[str]] = {}
        for observation in read.observations:
            states_by_id.setdefault(observation.source_id, set()).add(observation.state)
        contradictory = {sid for sid, states in states_by_id.items() if len(states) > 1}
        for sid in contradictory:
            outcome["unknown"] += 1
        for observation in read.observations:
            if observation.source_id in contradictory:
                continue
            if observation.state == DUE_STATE:
                generated = new_alert_id()
                try:
                    alert = await self._alerts.ensure_condition_alert(
                        alert_id=generated, vehicle_id=vehicle_id, alert_type=alert_type, source_type=source_type,
                        source_id=observation.source_id, severity=R7_ALERT_SEVERITY, created_at=utc_now(),
                        message_th=observation.message_th)
                except ApiError as exc:
                    if exc.code == "ALERT_OPEN_IDENTITY_CONFLICT":
                        outcome["conflicts"] += 1
                        continue
                    if exc.code == "ALERT_ID_ALREADY_EXISTS":
                        outcome["collisions"] += 1  # honest failure, no retry
                        continue
                    raise
                outcome["created" if alert.alert_id == generated else "reused"] += 1
            elif observation.state == NOT_DUE_STATE:
                await resolve(observation.source_id)
            else:
                outcome["unknown"] += 1  # UNKNOWN: no create and no resolve
        # IR-C7: resolve-on-absence is FAIL-CLOSED — only for a complete read in which every
        # observation is proven, with no identity conflict or id collision in this run, and
        # never for a source whose absence is not proof (certificates, D3).
        observed = {o.source_id for o in read.observations}
        absent = [source_id for source_id in by_source if source_id not in observed]
        if not absent:
            return
        if not read.complete:
            block = "SOURCE_INCOMPLETE"
        elif not read.absence_is_proof:
            block = read.absence_block_reason or "ABSENCE_IS_NOT_PROOF"
        elif outcome["unknown"]:
            block = "UNKNOWN_OBSERVATION"
        elif outcome["conflicts"]:
            block = "IDENTITY_CONFLICT"
        elif outcome["collisions"]:
            block = "ID_COLLISION"
        else:
            block = None
        if block is not None:
            outcome["absence_resolution"] = f"WITHHELD:{block}"
            return
        for source_id in absent:
            await resolve(source_id)
        outcome["absence_resolution"] = ABSENCE_APPLIED

    # ---- ACK / MUTE with audit and replay repair (P-9, P-9b) ----

    def _event(self, kind: str, action: str, request_id: str, context, *, alert_id: str, vehicle_id: str,
               from_status: str = "", to_status: str = "", reason: str = "", muted_until: str = "",
               fingerprint: str = "", outcome: str = "", details: dict | None = None) -> dict[str, str]:
        return {"event_id": f"ALAE-{uuid.uuid4().hex}", "kind": kind, "action": action, "alert_id": alert_id,
                "vehicle_id": vehicle_id, "request_id": request_id, "actor_user_id": context.user_id or "",
                "actor_personnel_id": getattr(context, "personnel_id", None) or "", "from_status": from_status,
                "to_status": to_status, "reason": reason, "muted_until": muted_until, "fingerprint": fingerprint,
                "outcome": outcome, "recorded_at": utc_now().isoformat(),
                "details_json": json.dumps(details or {}, ensure_ascii=False, sort_keys=True, default=str)}

    @staticmethod
    def _fingerprint(action: str, alert_id: str, actor: str, reason: str, muted_until: str) -> str:
        payload = json.dumps([action, alert_id, actor, reason, muted_until], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def act(self, context, alert_id: str, action: str, request_id: str, *, reason: str | None = None,
                  muted_until: datetime | None = None) -> dict:
        from app.domain import authz

        action_th = ("การรับทราบการแจ้งเตือน (acknowledge alert)" if action == ACTION_ACKNOWLEDGE
                     else "การปิดเสียงการแจ้งเตือน (mute alert)")
        self._require_test_authority(context, authz.CAN_ACT_ON_TEST_ALERT, action_th)
        reason_text = (reason or "").strip()
        if len(reason_text) > MAX_REASON_LENGTH:
            raise ApiError(code="ALERT_ACTION_REASON_TOO_LONG", message="The reason is too long",
                           status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, details={"max_length": MAX_REASON_LENGTH})
        if action == ACTION_MUTE:
            if not reason_text:
                raise ApiError(code="ALERT_ACTION_REASON_REQUIRED", message="A reason is required to mute an alert",
                               status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
            if muted_until is None or muted_until.tzinfo is None:
                raise ApiError(code="ALERT_MUTED_UNTIL_NOT_TZ_AWARE", message="muted_until must be timezone-aware",
                               status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        alert = await self._alerts.get_alert(alert_id)
        await self._require_test_vehicle(alert.vehicle_id)
        until_text = muted_until.isoformat() if muted_until is not None else ""
        fingerprint = self._fingerprint(action, alert_id, context.user_id or "", reason_text, until_text)

        earlier = [e for e in await self._repository.list_alert_action_events() if e.get("request_id") == request_id]
        if earlier:
            if any(e.get("fingerprint") != fingerprint for e in earlier):
                raise ApiError(code="ALERT_ACTION_REQUEST_ID_REUSED", status_code=status.HTTP_409_CONFLICT,
                               message="This request id was already used for a different alert action; "
                                       "nothing was changed")
            terminal = [e for e in earlier if e.get("kind") in (EVENT_COMMIT, EVENT_ABORT)]
            if terminal:
                last = terminal[-1]
                if last["kind"] == EVENT_ABORT:
                    raise ApiError(code=last["outcome"], status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                                   message="This request was already refused; nothing was changed",
                                   details={"replayed": True})
                return {"alert": await self._alerts.get_alert(alert_id), "replayed": True, "recovered": False,
                        "outcome": last["outcome"]}
            # An INTENT without a terminal record: an earlier attempt may have changed the
            # alert and then failed to record it. Complete it exactly once (below), never
            # re-attributing an existing acknowledgement.
            return await self._perform(context, alert, action, request_id, reason_text, muted_until, until_text,
                                       fingerprint, recovering=True)

        intent = self._event(EVENT_INTENT, action, request_id, context, alert_id=alert_id,
                             vehicle_id=alert.vehicle_id, from_status=alert.alert_status.value if alert.alert_status
                             else "", reason=reason_text, muted_until=until_text, fingerprint=fingerprint)
        try:
            await self._repository.append_alert_action_event(intent)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(code="ALERT_ACTION_AUDIT_UNAVAILABLE", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                           message="The audit log is unavailable; nothing was changed",
                           details={"state_changed": False}) from exc
        return await self._perform(context, alert, action, request_id, reason_text, muted_until, until_text,
                                   fingerprint, recovering=False)

    async def _perform(self, context, alert: Alert, action: str, request_id: str, reason_text: str,
                       muted_until: datetime | None, until_text: str, fingerprint: str, *, recovering: bool) -> dict:
        alert_id = alert.alert_id
        current = await self._alerts.get_alert(alert_id)
        from_status = current.alert_status.value if current.alert_status else ""
        already_applied = (
            (action == ACTION_ACKNOWLEDGE and current.acknowledged_at is not None
             and current.alert_status in (AlertStatus.ACKNOWLEDGED, AlertStatus.MUTED))
            or (action == ACTION_MUTE and current.alert_status == AlertStatus.MUTED
                and current.muted_until == muted_until)
        )
        try:
            if recovering and already_applied:
                result, outcome = current, "RECOVERED_ALREADY_APPLIED"
            else:
                if mute_expired(current):
                    current = await self._alerts.reconcile_mute_expiry(alert_id)
                if action == ACTION_ACKNOWLEDGE:
                    was_acknowledged = current.alert_status == AlertStatus.ACKNOWLEDGED
                    result = await self._alerts.acknowledge_alert(alert_id, context.user_id or "")
                    outcome = "NOOP_ALREADY_ACKNOWLEDGED" if was_acknowledged else "APPLIED"
                else:
                    was_same = current.alert_status == AlertStatus.MUTED and current.muted_until == muted_until
                    result = await self._alerts.mute_alert(alert_id, muted_until)  # type: ignore[arg-type]
                    outcome = "NOOP_ALREADY_MUTED" if was_same else "APPLIED"
        except ApiError as exc:
            abort = self._event(EVENT_ABORT, action, request_id, context, alert_id=alert_id,
                                vehicle_id=alert.vehicle_id, from_status=from_status, reason=reason_text,
                                muted_until=until_text, fingerprint=fingerprint, outcome=exc.code)
            try:
                await self._repository.append_alert_action_event(abort)
            except Exception:  # noqa: BLE001 - the original refusal is still reported unchanged
                pass
            raise
        commit = self._event(EVENT_COMMIT, action, request_id, context, alert_id=alert_id,
                             vehicle_id=alert.vehicle_id, from_status=from_status,
                             to_status=result.alert_status.value if result.alert_status else "", reason=reason_text,
                             muted_until=until_text, fingerprint=fingerprint, outcome=outcome,
                             details={"recovered": recovering,
                                      "acknowledged_by_user_id": result.acknowledged_by_user_id})
        try:
            await self._repository.append_alert_action_event(commit)
        except Exception as exc:  # noqa: BLE001 - never report success without the audit record
            raise ApiError(code="ALERT_ACTION_AUDIT_INCOMPLETE", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                           message="The alert changed but its audit record could not be written; repeat the SAME "
                                   "request (same X-Request-Id) to complete the record",
                           details={"state_changed": True, "alert_id": alert_id, "request_id": request_id}) from exc
        return {"alert": result, "replayed": recovering, "recovered": recovering, "outcome": outcome}

    # ---- reads: central list, provenance, verified source links (P-10, P-11) ----

    async def list_alerts(self, *, status_filter: str | None, alert_type: str | None, vehicle_id: str | None,
                          page: int, page_size: int) -> tuple[list[Alert], int]:
        alerts = await self._repository.list_alerts()
        if status_filter:
            alerts = [a for a in alerts if a.alert_status is not None and a.alert_status.value == status_filter]
        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]
        if vehicle_id:
            alerts = [a for a in alerts if a.vehicle_id == vehicle_id]
        alerts.sort(key=lambda a: (-a.created_at.timestamp(), a.alert_id))
        start = (page - 1) * page_size
        return alerts[start:start + page_size], len(alerts)

    async def source_link(self, alert: Alert) -> str | None:
        """A link only after verifying the source still belongs to the alert's vehicle,
        mapped through a fixed route key. Anything unknown, foreign, moved or failing ->
        None. Never built from a raw source_id."""
        vehicle = quote(alert.vehicle_id, safe="")
        try:
            if alert.alert_type == ALERT_TYPE_PM_DUE and alert.source_type == SOURCE_TYPE_PM_DUE_SET:
                await self._require_test_vehicle(alert.vehicle_id)
                return f"/vehicle/{vehicle}/pm/due"
            if (alert.alert_type == ALERT_TYPE_PART_LIFETIME_DUE
                    and alert.source_type == SOURCE_TYPE_PART_LIFETIME_DUE_KEY and alert.source_id):
                target_type, target_id = alert.source_id.split(":")[:2]
                if target_type == "PART_INSTANCE":
                    view = await self._parts.instance_status(target_id)
                else:
                    view = await self._parts.position_status(target_id)
                host = view.get("host") or {}
                if host.get("asset_type") != "VEHICLE" or host.get("asset_id") != alert.vehicle_id:
                    return None
                return (f"/part-instances/{quote(target_id, safe='')}" if target_type == "PART_INSTANCE"
                        else f"/vehicle/{vehicle}/parts")
            if (alert.alert_type == ALERT_TYPE_CERTIFICATE_EXPIRED
                    and alert.source_type == SOURCE_TYPE_VEHICLE_CERTIFICATE and alert.source_id):
                certificate = await self._repository.get_vehicle_certificate(alert.source_id)
                if certificate is None or certificate.vehicle_id != alert.vehicle_id:
                    return None
                return f"/vehicle/{vehicle}/certificates"
        except Exception:  # noqa: BLE001 - an unverifiable source never yields a link
            return None
        return None

    async def provenance(self, vehicle_id: str) -> dict[str, str]:
        """Per approved type: NOT_CONFIGURED / SETTING_CONFLICT / NOT_EVALUATED /
        EVALUATED_NONE (verified zero: complete source, nothing unknown) / ALERTS /
        SOURCE_INCOMPLETE / ALERTS_SOURCE_INCOMPLETE — from server records only (the latest evaluation audit
        event covering the vehicle); UNAVAILABLE where the log is not supported."""
        from app.repositories.base import RepositoryFeatureNotImplementedError

        try:
            events = await self._repository.list_alert_action_events()
        except RepositoryFeatureNotImplementedError:
            return {alert_type: PROVENANCE_UNAVAILABLE for alert_type in R7_ALERT_SOURCE_TYPES}
        latest: dict[str, dict] = {}
        for event in events:
            if event.get("kind") != EVENT_EVALUATION:
                continue
            try:
                details = json.loads(event.get("details_json") or "{}")
            except ValueError:
                continue
            for outcome in details.get("outcomes", ()):
                if outcome.get("vehicle_id") == vehicle_id:
                    latest[outcome.get("alert_type")] = outcome
        open_types = {a.alert_type for a in await self._repository.list_alerts_for_vehicle(vehicle_id)
                      if a.alert_status in _OPEN_ALERT_STATUSES}
        result: dict[str, str] = {}
        for alert_type in R7_ALERT_SOURCE_TYPES:
            outcome = latest.get(alert_type)
            if outcome is None:
                result[alert_type] = PROVENANCE_ALERTS if alert_type in open_types else PROVENANCE_NOT_EVALUATED
            elif outcome.get("setting") in (PROVENANCE_NOT_CONFIGURED, PROVENANCE_CONFLICT):
                result[alert_type] = outcome["setting"]
            elif _outcome_proves_complete(outcome):
                result[alert_type] = PROVENANCE_ALERTS if alert_type in open_types else PROVENANCE_EVALUATED_NONE
            else:
                result[alert_type] = (PROVENANCE_ALERTS_SOURCE_INCOMPLETE if alert_type in open_types
                                      else PROVENANCE_SOURCE_INCOMPLETE)
        return result


__all__ = ["AlertService", "R7AlertService", "R7_ALERT_SOURCE_TYPES", "mute_expired", "new_alert_id"]
