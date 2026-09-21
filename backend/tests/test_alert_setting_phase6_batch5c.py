"""Web/API Phase 6 Batch 5C — Alert Setting Read Foundation.

Proves the Batch 5C scope (see `app.domain.alert_setting`/`app.domain.
alert_setting_service` module docstrings, restated from the task's own
frozen sections):

- exact 13-column live `alert_setting` schema declaration
- empty sheet / no rows -> empty list, never an error
- multiple settings parse correctly, opaque fields preserved unchanged
  (alert_type/scope_type/setting_status/threshold_unit/lead_unit)
- blank nullable cells stay honestly `None` — no invented defaults
- TRUE/FALSE boolean parsing for `enabled`/`auto_reenable_on_online`
  (tri-state: blank -> `None`, never a fabricated `False`)
- numeric threshold_value/lead_value parsing with no unit conversion
- timezone-aware `muted_until` parsing when present
- deterministic ordering (`alert_setting_id` ascending) at the service
  layer
- `list_alert_settings_for_type` filters by exact opaque `alert_type`
  equality
- a missing `alert_setting_id` returns `None` at the repository level /
  raises a 404-style `ApiError` at the service level
- no write/mutation method or HTTP mutation route exists anywhere in
  this batch
- shuffled live header handling stays safe (header-name mapping, not
  position)
- Batch 5A `Alert` read behavior and Batch 5B D25 lifecycle tests are
  unaffected by this batch (proven by those existing test modules still
  passing unmodified — not re-asserted here)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.domain.alert_setting import AlertSetting
from app.domain.alert_setting_service import AlertSettingService
from app.errors import ApiError
from app.repositories.base import RepositoryError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.mock import MockRepository

from tests.test_google_sheets_real_io import FakeSpreadsheet, FakeWorksheet, _ws


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


def _setting(alert_setting_id: str, **overrides) -> AlertSetting:
    return AlertSetting(alert_setting_id=alert_setting_id, **overrides)


# ---------------------------------------------------------------------------
# 1. EXACT 13-COLUMN LIVE SCHEMA DECLARATION
# ---------------------------------------------------------------------------


def test_1_alert_setting_schema_uses_the_exact_live_column_list() -> None:
    assert schemas.ALERT_SETTING_SHEET.tab_name == "alert_setting"
    assert schemas.ALERT_SETTING_SHEET.required_headers == (
        "alert_setting_id",
        "scope_type",
        "scope_id",
        "alert_type",
        "enabled",
        "threshold_value",
        "threshold_unit",
        "lead_value",
        "lead_unit",
        "muted_until",
        "auto_reenable_on_online",
        "setting_status",
        "note_th",
    )
    assert len(schemas.ALERT_SETTING_SHEET.required_headers) == 13


# ---------------------------------------------------------------------------
# 2. EMPTY SHEET
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_2_empty_sheet_returns_empty_list() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    repo = _repo_with_fake_sheets(ws)

    settings = await repo.list_alert_settings()

    assert settings == []


# ---------------------------------------------------------------------------
# 3. MULTIPLE SETTINGS PARSE CORRECTLY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_3_multiple_settings_parse_correctly() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        [
            "ASET-0001", "GLOBAL", "", "PM_DUE_HOUR", "TRUE", "", "", "50", "h",
            "", "", "ACTIVE", "",
        ]
    )
    ws.append_row(
        [
            "ASET-0003", "GLOBAL", "", "DEVICE_OFFLINE", "TRUE", "24", "h", "", "",
            "", "TRUE", "ACTIVE", "",
        ]
    )
    repo = _repo_with_fake_sheets(ws)

    settings = await repo.list_alert_settings()

    assert {s.alert_setting_id for s in settings} == {"ASET-0001", "ASET-0003"}
    by_id = {s.alert_setting_id: s for s in settings}

    pm_due = by_id["ASET-0001"]
    assert pm_due.scope_type == "GLOBAL"
    assert pm_due.alert_type == "PM_DUE_HOUR"
    assert pm_due.enabled is True
    assert pm_due.lead_value == 50
    assert pm_due.lead_unit == "h"
    assert pm_due.setting_status == "ACTIVE"

    offline = by_id["ASET-0003"]
    assert offline.alert_type == "DEVICE_OFFLINE"
    assert offline.threshold_value == 24
    assert offline.threshold_unit == "h"
    assert offline.auto_reenable_on_online is True


# ---------------------------------------------------------------------------
# 4. BLANK NULLABLE VALUES REMAIN NONE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_4_blank_nullable_fields_remain_none() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        ["ASET-9001", "", "", "", "", "", "", "", "", "", "", "", ""]
    )
    repo = _repo_with_fake_sheets(ws)

    setting = await repo.get_alert_setting("ASET-9001")

    assert setting is not None
    assert setting.scope_type is None
    assert setting.scope_id is None
    assert setting.alert_type is None
    assert setting.enabled is None
    assert setting.threshold_value is None
    assert setting.threshold_unit is None
    assert setting.lead_value is None
    assert setting.lead_unit is None
    assert setting.muted_until is None
    assert setting.auto_reenable_on_online is None
    assert setting.setting_status is None
    assert setting.note_th is None


# ---------------------------------------------------------------------------
# 5. TRUE/FALSE BOOLEAN PARSING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_5_true_false_boolean_parsing() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        ["ASET-T1", "GLOBAL", "", "PM_DUE_HOUR", "TRUE", "", "", "", "", "", "FALSE", "ACTIVE", ""]
    )
    ws.append_row(
        ["ASET-T2", "GLOBAL", "", "PM_DUE_KM", "FALSE", "", "", "", "", "", "TRUE", "ACTIVE", ""]
    )
    repo = _repo_with_fake_sheets(ws)

    t1 = await repo.get_alert_setting("ASET-T1")
    t2 = await repo.get_alert_setting("ASET-T2")

    assert t1 is not None and t1.enabled is True and t1.auto_reenable_on_online is False
    assert t2 is not None and t2.enabled is False and t2.auto_reenable_on_online is True


# ---------------------------------------------------------------------------
# 6. NUMERIC THRESHOLD/LEAD PARSING — NO INVENTED UNIT CONVERSION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_6_numeric_threshold_and_lead_parsed_without_unit_conversion() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        ["ASET-0004", "GLOBAL", "", "INACTIVE_VEHICLE", "TRUE", "3", "month", "", "", "", "", "ACTIVE", ""]
    )
    repo = _repo_with_fake_sheets(ws)

    setting = await repo.get_alert_setting("ASET-0004")

    assert setting is not None
    assert setting.threshold_value == 3
    assert setting.threshold_unit == "month"
    # No conversion to hours/days/seconds — the raw value and unit are
    # returned exactly as stored.


# ---------------------------------------------------------------------------
# 7. TIMEZONE-AWARE MUTED_UNTIL PARSING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_7_muted_until_parses_as_timezone_aware_datetime() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        [
            "ASET-M1", "VEHICLE", "VEH-1", "REPAIR_OPEN", "TRUE", "", "", "", "",
            "2026-02-01T00:00:00+00:00", "", "MUTED", "",
        ]
    )
    repo = _repo_with_fake_sheets(ws)

    setting = await repo.get_alert_setting("ASET-M1")

    assert setting is not None
    assert setting.muted_until == datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert setting.muted_until.tzinfo is not None


# ---------------------------------------------------------------------------
# 8-10. OPAQUE STRING PRESERVATION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_8_opaque_alert_type_preserved_unchanged() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        [
            "ASET-0012", "GLOBAL", "", "FIRMWARE_UPDATE_FAILED", "TRUE", "", "",
            "", "", "", "", "ACTIVE", "",
        ]
    )
    repo = _repo_with_fake_sheets(ws)

    setting = await repo.get_alert_setting("ASET-0012")

    assert setting is not None
    assert setting.alert_type == "FIRMWARE_UPDATE_FAILED"


@pytest.mark.asyncio
async def test_9_opaque_scope_type_preserved_unchanged() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        [
            "ASET-S1", "SOME_FUTURE_SCOPE_NOT_IN_ANY_ENUM", "000009", "PM_DUE_HOUR", "TRUE",
            "", "", "", "", "", "", "ACTIVE", "",
        ]
    )
    repo = _repo_with_fake_sheets(ws)

    setting = await repo.get_alert_setting("ASET-S1")

    assert setting is not None
    assert setting.scope_type == "SOME_FUTURE_SCOPE_NOT_IN_ANY_ENUM"
    # leading-zero scope_id also survives as text, never numerically coerced
    assert setting.scope_id == "000009"
    assert setting.scope_id != 9  # type: ignore[comparison-overlap]


@pytest.mark.asyncio
async def test_10_opaque_setting_status_preserved_unchanged() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        [
            "ASET-ST1", "GLOBAL", "", "PM_DUE_HOUR", "TRUE", "", "", "", "",
            "", "", "SOME_FUTURE_STATUS_NOT_IN_ANY_ENUM", "",
        ]
    )
    repo = _repo_with_fake_sheets(ws)

    setting = await repo.get_alert_setting("ASET-ST1")

    assert setting is not None
    assert setting.setting_status == "SOME_FUTURE_STATUS_NOT_IN_ANY_ENUM"


# ---------------------------------------------------------------------------
# 11. DETERMINISTIC ORDERING (service layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_11_service_deterministic_ordering_by_alert_setting_id() -> None:
    repo = MockRepository()
    repo._alert_settings.extend(
        [
            _setting("ASET-0007", alert_type="REPAIR_OPEN"),
            _setting("ASET-0001", alert_type="PM_DUE_HOUR"),
            _setting("ASET-0003", alert_type="DEVICE_OFFLINE"),
        ]
    )
    service = AlertSettingService(repo)

    ordered = await service.list_alert_settings()

    assert [s.alert_setting_id for s in ordered] == ["ASET-0001", "ASET-0003", "ASET-0007"]


# ---------------------------------------------------------------------------
# 12. LIST BY ALERT_TYPE FILTERS CORRECTLY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_12_list_by_alert_type_filters_correctly() -> None:
    repo = MockRepository()
    repo._alert_settings.extend(
        [
            _setting("ASET-0001", alert_type="PM_DUE_HOUR"),
            _setting("ASET-0002", alert_type="PM_DUE_KM"),
            _setting("ASET-0003", alert_type="DEVICE_OFFLINE"),
        ]
    )
    service = AlertSettingService(repo)

    matched = await service.list_alert_settings_for_type("PM_DUE_KM")

    assert [s.alert_setting_id for s in matched] == ["ASET-0002"]

    matched_none = await service.list_alert_settings_for_type("SOME_TYPE_WITH_NO_SETTING")
    assert matched_none == []


# ---------------------------------------------------------------------------
# 13. MISSING ID RETURNS NONE AT REPOSITORY LEVEL / 404 AT SERVICE LEVEL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_13_missing_id_returns_none_at_repository_level() -> None:
    repo = MockRepository()
    result = await repo.get_alert_setting("ASET-DOES-NOT-EXIST")
    assert result is None

    ws = _ws(schemas.ALERT_SETTING_SHEET)
    sheets_repo = _repo_with_fake_sheets(ws)
    sheets_result = await sheets_repo.get_alert_setting("ASET-DOES-NOT-EXIST")
    assert sheets_result is None


@pytest.mark.asyncio
async def test_13b_missing_id_raises_404_apierror_at_service_level() -> None:
    repo = MockRepository()
    service = AlertSettingService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.get_alert_setting("ASET-DOES-NOT-EXIST")
    assert exc_info.value.code == "ALERT_SETTING_NOT_FOUND"
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 14. NO WRITE/MUTATION METHOD OR HTTP MUTATION ROUTE EXISTS
# ---------------------------------------------------------------------------


def test_14_no_mutation_method_exists_on_repository() -> None:
    for repo_cls in (MockRepository, GoogleSheetsRepository):
        for forbidden in (
            "create_alert_setting",
            "update_alert_setting",
            "delete_alert_setting",
            "enable_alert_setting",
            "disable_alert_setting",
            "mute_alert_setting",
        ):
            assert not hasattr(repo_cls, forbidden), (
                f"{repo_cls.__name__} must not expose {forbidden!r} — "
                "Batch 5C is read-only."
            )


@pytest.mark.asyncio
async def test_14b_no_alert_setting_http_route_exists(client: AsyncClient) -> None:
    # No public HTTP surface at all in this batch — neither read nor write.
    get_list_response = await client.get("/api/v1/alert-settings")
    assert get_list_response.status_code == 404

    get_one_response = await client.get("/api/v1/alert-settings/ASET-0001")
    assert get_one_response.status_code == 404

    post_response = await client.post("/api/v1/alert-settings", json={})
    assert post_response.status_code == 404

    patch_response = await client.patch("/api/v1/alert-settings/ASET-0001", json={})
    assert patch_response.status_code == 404

    delete_response = await client.delete("/api/v1/alert-settings/ASET-0001")
    assert delete_response.status_code == 404


# ---------------------------------------------------------------------------
# 15-16. EXISTING BATCH 5A/5B BEHAVIOR IS UNCHANGED
# ---------------------------------------------------------------------------
#
# Covered by the existing, unmodified test_alert_phase6_batch5a.py and
# test_alert_phase6_batch5b.py modules (run as part of the same suite —
# see the Batch 5C phase report for the full pytest results). Nothing in
# this module patches, monkeypatches, or otherwise alters `Alert`/
# `AlertService`/`AlertStatus`/`AlertSeverity` or the `alert` sheet
# schema/repository methods.


def test_15_alert_domain_module_is_untouched_by_this_batch() -> None:
    from app.domain.alert import Alert, AlertSeverity, AlertStatus

    assert {s.value for s in AlertSeverity} == {"INFO", "WARNING", "CRITICAL"}
    assert {s.value for s in AlertStatus} == {"ACTIVE", "ACKNOWLEDGED", "MUTED", "RESOLVED"}
    assert set(Alert.model_fields.keys()) == {
        "alert_id", "vehicle_id", "alert_type", "source_type", "source_id",
        "severity", "created_at", "alert_status", "muted_until",
        "acknowledged_by_user_id", "acknowledged_at", "resolved_at", "message_th",
    }


def test_16_alert_sheet_schema_is_untouched_by_this_batch() -> None:
    assert schemas.ALERT_SHEET.tab_name == "alert"
    assert schemas.ALERT_SHEET.required_headers == (
        "alert_id", "vehicle_id", "alert_type", "source_type", "source_id",
        "severity", "created_at", "alert_status", "muted_until",
        "acknowledged_by_user_id", "acknowledged_at", "resolved_at", "message_th",
    )


# ---------------------------------------------------------------------------
# 17. SHUFFLED LIVE HEADER HANDLING REMAINS SAFE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_17_shuffled_header_order_is_mapped_by_name_not_position() -> None:
    scrambled_header = (
        "alert_setting_id", "note_th", "scope_type", "setting_status", "alert_type",
        "muted_until", "scope_id", "auto_reenable_on_online", "threshold_unit",
        "threshold_value", "lead_unit", "lead_value", "enabled",
    )
    assert set(scrambled_header) == set(schemas.ALERT_SETTING_SHEET.required_headers)
    ws = FakeWorksheet(schemas.ALERT_SETTING_SHEET.tab_name, scrambled_header)
    # Numeric-looking scope_id ("000009") under a reordered header must
    # survive unchanged — text-protection column positions are resolved
    # from the LIVE header, never the declared schema order.
    scrambled_row = [
        "ASET-SH1", "หมายเหตุ", "GLOBAL", "ACTIVE", "PM_DUE_HOUR",
        "", "000009", "TRUE", "h", "24", "km", "500", "TRUE",
    ]
    ws.append_row(scrambled_row)
    repo = _repo_with_fake_sheets(ws)

    setting = await repo.get_alert_setting("ASET-SH1")

    assert setting is not None
    assert setting.scope_id == "000009"
    assert setting.scope_id != 9  # type: ignore[comparison-overlap]
    assert setting.note_th == "หมายเหตุ"
    assert setting.threshold_value == 24
    assert setting.threshold_unit == "h"
    assert setting.lead_value == 500
    assert setting.lead_unit == "km"
    assert setting.enabled is True
    assert setting.auto_reenable_on_online is True
    assert setting.setting_status == "ACTIVE"


# ---------------------------------------------------------------------------
# GOOGLE SHEETS READ PATH NEVER WRITES
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sheets_read_path_performs_no_write() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        ["ASET-0001", "GLOBAL", "", "PM_DUE_HOUR", "TRUE", "", "", "50", "h", "", "", "ACTIVE", ""]
    )
    repo = _repo_with_fake_sheets(ws)

    append_row_calls_before = ws.append_row_calls
    append_rows_calls_before = ws.append_rows_calls
    delete_rows_calls_before = ws.delete_rows_calls
    rows_before = len(ws.rows)

    await repo.get_alert_setting("ASET-0001")
    await repo.list_alert_settings()
    await repo.list_alert_settings_for_type("PM_DUE_HOUR")
    await repo.get_alert_setting("ASET-DOES-NOT-EXIST")

    assert ws.append_row_calls == append_row_calls_before
    assert ws.append_rows_calls == append_rows_calls_before
    assert ws.delete_rows_calls == delete_rows_calls_before
    assert len(ws.rows) == rows_before


# ---------------------------------------------------------------------------
# REQUIRED-FIELD PROTECTION — blank/missing alert_setting_id fails
# honestly rather than fabricating an identity (same pattern as B5A-01).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blank_alert_setting_id_fails_honestly_not_invented() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        ["", "GLOBAL", "", "PM_DUE_HOUR", "TRUE", "", "", "", "", "", "", "ACTIVE", ""]
    )
    repo = _repo_with_fake_sheets(ws)

    with pytest.raises(RepositoryError):
        await repo.get_alert_setting("")
