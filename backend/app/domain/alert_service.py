"""Alert service (Web/API Phase 6 Batch 5A — Alert Read Foundation). See
`app.domain.alert` for the `Alert`/`AlertSeverity`/`AlertStatus` models
and the read-only framing.

Batch 5A responsibilities only: validate a requested vehicle exists
before listing its alerts, fetch one alert by id (404-style `ApiError`
when missing, matching every other Phase 6 domain's not-found pattern),
and provide a DETERMINISTIC display ordering for a vehicle's alert list.

That ordering (`created_at` descending, `alert_id` ascending as the final
tie-break) is technical/display determinism only — it is not a ranking
by severity or an importance judgment, and this service never evaluates
suppression, mute expiry, or which alert is "more important". Those all
require the still-unresolved A07 (Alert Deduplication / Auto-Resolve)
and are explicitly out of scope here."""
from __future__ import annotations

from fastapi import status

from app.domain.alert import Alert
from app.errors import ApiError
from app.repositories.base import Repository


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


__all__ = ["AlertService"]
