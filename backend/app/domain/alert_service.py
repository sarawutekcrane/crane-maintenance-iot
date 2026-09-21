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


__all__ = ["AlertService"]
