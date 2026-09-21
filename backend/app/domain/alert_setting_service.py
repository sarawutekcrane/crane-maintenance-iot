"""Alert Setting service (Web/API Phase 6 Batch 5C — Alert Setting Read
Foundation). See `app.domain.alert_setting` for the `AlertSetting` model
and the full list of decisions this batch explicitly does NOT make.

READ-ONLY FOUNDATION: this service exists only so a later alert-
policy/generation batch has a stable read surface to build on. It does
not, and must not, choose a winning setting across scopes, apply scope
precedence, evaluate DEVICE_OFFLINE timing, compute PM due/certificate
expiry, generate or resolve `Alert` rows, or implement any suppression/
notification behavior.

`list_alert_settings`/`list_alert_settings_for_type` impose one
DETERMINISTIC display ordering — `alert_setting_id` ascending — purely
for stable/reproducible output. This is technical/display determinism
only, exactly like `AlertService.list_for_vehicle`'s own ordering
docstring already states for `Alert`: it is not a ranking by importance
and never implies which setting "wins" for a given scope."""
from __future__ import annotations

from fastapi import status

from app.domain.alert_setting import AlertSetting
from app.errors import ApiError
from app.repositories.base import Repository


class AlertSettingService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def get_alert_setting(self, alert_setting_id: str) -> AlertSetting:
        setting = await self._repository.get_alert_setting(alert_setting_id)
        if setting is None:
            raise ApiError(
                code="ALERT_SETTING_NOT_FOUND",
                message=f"Alert setting '{alert_setting_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return setting

    async def list_alert_settings(self) -> list[AlertSetting]:
        settings = await self._repository.list_alert_settings()
        return sorted(settings, key=lambda s: s.alert_setting_id)

    async def list_alert_settings_for_type(self, alert_type: str) -> list[AlertSetting]:
        settings = await self._repository.list_alert_settings_for_type(alert_type)
        return sorted(settings, key=lambda s: s.alert_setting_id)


__all__ = ["AlertSettingService"]
