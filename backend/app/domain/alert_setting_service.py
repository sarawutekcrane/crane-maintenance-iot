"""Alert Setting service (Web/API Phase 6 Batch 5C — Alert Setting Read
Foundation; Batch 5D — Alert Effective-Setting Policy Core). See
`app.domain.alert_setting` for the `AlertSetting` model.

READ-ONLY FOUNDATION (Batch 5C, unchanged): `list_alert_settings`/
`list_alert_settings_for_type` impose one DETERMINISTIC display ordering
— `alert_setting_id` ascending — purely for stable/reproducible output.
This is technical/display determinism only, exactly like
`AlertService.list_for_vehicle`'s own ordering docstring already states
for `Alert`: it is not a ranking by importance and never implies which
setting "wins" for a given scope.

BATCH 5D — D26 (A11, APPROVED/FROZEN — see `docs/project-governance/
OPEN_DECISIONS_REGISTER_EN.txt`) is now implemented here, and ONLY here,
via `get_effective_global_setting`/`should_suppress_device_offline`.

D26 NOW freezes (implemented below):
- effective-setting eligibility (enabled/setting_status/muted_until,
  fail-closed on anything not exactly matching the frozen shape),
- GLOBAL-only scope matching (a GLOBAL row requires a blank scope_id;
  MODEL/VEHICLE rows are never usable by this resolver),
- duplicate GLOBAL conflict behavior (>1 usable GLOBAL row for one
  alert_type fails closed with `ALERT_SETTING_GLOBAL_CONFLICT`, never a
  guessed winner),
- DEVICE_OFFLINE operational-status suppression (`should_suppress_
  device_offline`, the exact frozen table only),
- zero-write evaluation (this module still has no create/update/delete
  method anywhere, on this service or any repository).

Still UNRESOLVED, and NOT implemented anywhere in this batch:
- MODEL/VEHICLE scope precedence (a MODEL/VEHICLE row is simply never
  usable here — no hierarchy, no fallback, no override of GLOBAL),
- `auto_reenable_on_online` behavioral semantics (read-only metadata;
  zero branching on it anywhere in this service),
- A05 (DEVICE_OFFLINE heartbeat interval / grace period / recovery
  timing / evaluation cadence / online-offline detection itself —
  `should_suppress_device_offline` only answers a suppression-policy
  question about an already-known `OperationalStatus`, it never detects
  or computes offline state),
- alert_type -> severity mapping (A06/D24),
- actual alert generation rules for any alert_type,
- A01 alert_id generation, A09 concurrency/optimistic locking,
- any AlertSetting/Alert mutation RBAC or mutation API.

This service NEVER creates, updates, deletes, acknowledges, mutes, or
resolves an `Alert` or `AlertSetting` row. `get_effective_global_setting`
performs reads only (via the existing exact-`alert_type` repository
filter, `list_alert_settings_for_type` — never an invented alias between
opaque `alert_type` strings such as PM_DUE/PM_DUE_HOUR)."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import status

from app.domain.alert_setting import AlertSetting
from app.domain.common import OperationalStatus, utc_now
from app.errors import ApiError
from app.repositories.base import Repository

logger = logging.getLogger(__name__)

# D26 (A11) section 3 — the exact frozen DEVICE_OFFLINE x OperationalStatus
# suppression table. `OperationalStatus` is the existing Vehicle enum
# (`app.domain.common`) — no new enum is introduced. Deliberately a plain
# dict, not a fallback/default: an `OperationalStatus` value with no entry
# here is a bug (the enum grew and this table wasn't updated), and a
# `KeyError` is the correct fail-loud signal rather than a fabricated
# default suppression decision.
_DEVICE_OFFLINE_SUPPRESSION: dict[OperationalStatus, bool] = {
    OperationalStatus.WORKING: False,
    OperationalStatus.READY: False,
    OperationalStatus.MAINTENANCE: True,
    OperationalStatus.OUT_OF_SERVICE: True,
    OperationalStatus.LONG_TERM_PARKING: True,
}


def _is_blank(value: str | None) -> bool:
    """D26's "canonical blank" for `scope_id`: `None` or an empty/
    whitespace-only string are both "blank"; a non-blank value is
    returned unaffected elsewhere (this helper only classifies)."""
    return value is None or not value.strip()


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

    # ---- Effective-setting resolution (Web/API Phase 6 Batch 5D — D26/A11) ----

    async def get_effective_global_setting(
        self,
        alert_type: str,
        *,
        now: datetime | None = None,
    ) -> AlertSetting | None:
        """D26 (A11) sections 1-3, 6: the GLOBAL-only effective-setting
        resolver. Reads `alert_type` candidates via the existing exact
        opaque-string repository filter (`list_alert_settings_for_type`)
        — no alias/mapping between different opaque `alert_type` strings
        is ever invented.

        Returns the single usable GLOBAL `AlertSetting` for `alert_type`,
        or `None` if zero usable GLOBAL rows exist. Raises `ApiError`
        (`ALERT_SETTING_GLOBAL_CONFLICT`, 422) if two or more usable
        GLOBAL rows exist — this method never guesses a winner by
        `alert_setting_id`, list/row order, or any other heuristic.

        `now` defaults to the project's existing UTC clock helper
        (`app.domain.common.utc_now`) when omitted. An explicitly
        supplied `now` must be timezone-aware; a naive value is rejected
        with `ApiError` (`ALERT_SETTING_EVALUATION_TIME_NOT_TZ_AWARE`,
        422) rather than silently assumed to be UTC.

        Performs ZERO writes — no repository mutation method exists for
        `AlertSetting`, and none is added by this method. Unusable rows
        (including configuration anomalies) are only ever surfaced via
        `logging`, never persisted, never resolved into an `Alert`.
        """
        if now is None:
            now = utc_now()
        elif now.tzinfo is None:
            raise ApiError(
                code="ALERT_SETTING_EVALUATION_TIME_NOT_TZ_AWARE",
                message="now must be timezone-aware",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        candidates = await self._repository.list_alert_settings_for_type(alert_type)
        usable = [setting for setting in candidates if self._is_usable_global(setting, now)]

        if not usable:
            return None
        if len(usable) > 1:
            raise ApiError(
                code="ALERT_SETTING_GLOBAL_CONFLICT",
                message=(
                    f"{len(usable)} usable GLOBAL alert_setting rows exist for "
                    f"alert_type {alert_type!r} — refusing to guess which one is "
                    "effective"
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={
                    "alert_type": alert_type,
                    "alert_setting_ids": sorted(s.alert_setting_id for s in usable),
                },
            )
        return usable[0]

    @staticmethod
    def _is_usable_global(setting: AlertSetting, now: datetime) -> bool:
        """D26 (A11) sections 1, 2, 4, 6 — fail-closed eligibility for a
        single row. Distinguishes NORMAL INELIGIBILITY (enabled=False; a
        valid ACTIVE GLOBAL row temporarily suppressed by a future
        `muted_until`) — no logging needed — from a CONFIGURATION
        ANOMALY (missing/unrecognized `scope_type`, a GLOBAL row with a
        nonblank `scope_id`, `enabled=None`, missing/unrecognized
        `setting_status`, a naive `muted_until`) — surfaced via
        `logging.warning`, per section 2's non-goal list: no anomaly
        persistence, no new alert, no notification. MODEL/VEHICLE rows
        are their own case (section 4): not an anomaly, just
        unsupported-for-current-policy — logged at `info` and never
        counted as a usable GLOBAL candidate, so they can never create a
        false GLOBAL duplicate conflict and never override a real GLOBAL
        row (no precedence is implemented)."""
        setting_id = setting.alert_setting_id

        if setting.scope_type is None:
            logger.warning(
                "alert_setting %s: configuration anomaly — missing scope_type; "
                "treated as not usable",
                setting_id,
            )
            return False
        if setting.scope_type in ("MODEL", "VEHICLE"):
            logger.info(
                "alert_setting %s: scope_type=%s is unsupported for the current "
                "D26 policy (MODEL/VEHICLE precedence remains unresolved) — "
                "treated as not usable, no precedence/fallback applied",
                setting_id,
                setting.scope_type,
            )
            return False
        if setting.scope_type != "GLOBAL":
            logger.warning(
                "alert_setting %s: configuration anomaly — unrecognized "
                "scope_type %r; treated as not usable",
                setting_id,
                setting.scope_type,
            )
            return False
        if not _is_blank(setting.scope_id):
            logger.warning(
                "alert_setting %s: configuration anomaly — scope_type=GLOBAL "
                "with a nonblank scope_id %r; treated as not usable",
                setting_id,
                setting.scope_id,
            )
            return False

        if setting.enabled is None:
            logger.warning(
                "alert_setting %s: configuration anomaly — enabled is missing "
                "(NULL); treated as not usable",
                setting_id,
            )
            return False
        if setting.enabled is False:
            return False  # normal ineligibility — not an anomaly

        if setting.setting_status is None:
            logger.warning(
                "alert_setting %s: configuration anomaly — missing "
                "setting_status; treated as not usable",
                setting_id,
            )
            return False
        if setting.setting_status != "ACTIVE":
            logger.warning(
                "alert_setting %s: configuration anomaly — unrecognized "
                "setting_status %r; treated as not usable",
                setting_id,
                setting.setting_status,
            )
            return False

        if setting.muted_until is not None:
            if setting.muted_until.tzinfo is None:
                logger.warning(
                    "alert_setting %s: configuration anomaly — naive "
                    "(non-timezone-aware) muted_until; treated as not usable",
                    setting_id,
                )
                return False
            if setting.muted_until > now:
                return False  # normal ineligibility — temporarily muted

        return True

    @staticmethod
    def should_suppress_device_offline(operational_status: OperationalStatus) -> bool:
        """D26 (A11) section 3 — the exact frozen DEVICE_OFFLINE x
        Vehicle `OperationalStatus` suppression table, and nothing else.
        Answers a pure suppression-POLICY question about an
        already-known status; it never reads or infers Vehicle status
        itself, never implements a status transition rule (C01 remains
        separately unresolved), and never detects/computes DEVICE_OFFLINE
        itself (A05 remains separately unresolved and TBD-BLOCKING)."""
        return _DEVICE_OFFLINE_SUPPRESSION[operational_status]


__all__ = ["AlertSettingService"]
