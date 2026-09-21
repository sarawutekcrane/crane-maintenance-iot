"""Web/API Phase 6 Batch 5D — Alert Effective-Setting Policy Core.

Proves D26 (A11, APPROVED/FROZEN — see `docs/project-governance/
OPEN_DECISIONS_REGISTER_EN.txt`), implemented ONLY as two new internal
`AlertSettingService` methods (`get_effective_global_setting`/
`should_suppress_device_offline`):

- fail-closed GLOBAL-only effective-setting eligibility (enabled exactly
  TRUE, setting_status exactly "ACTIVE", muted_until absent or <= now)
- GLOBAL-only scope matching (blank scope_id required; MODEL/VEHICLE
  rows are never usable, never given precedence/fallback)
- duplicate-GLOBAL conflict behavior (>1 usable GLOBAL row for one
  alert_type -> `ALERT_SETTING_GLOBAL_CONFLICT`, never a guessed winner)
- configuration-anomaly vs. normal-ineligibility distinction, surfaced
  only via `logging`
- the exact frozen DEVICE_OFFLINE x Vehicle OperationalStatus
  suppression table
- zero writes anywhere in this batch

FAIL-CLOSED GAP FIX (post-commit 133c345 source review): the Google
Sheets parser used to collapse a malformed NONBLANK `enabled` (e.g.
`"MAYBE"`) or `muted_until` (e.g. `"not-a-date"`) cell to the exact same
`False`/`None` a genuinely blank cell produces, which the D26 resolver
could not then distinguish from a legitimate value. Tests
`test_gap_*` below (against the FAKE GOOGLE SHEETS path, not direct Mock
construction — a malformed source STRING only exists on that path) prove
the fix: such a row is NOT usable, an anomaly is surfaced via logging,
and — critically — it never blocks a different valid usable GLOBAL row
for the same `alert_type`, never creates a false
`ALERT_SETTING_GLOBAL_CONFLICT`, and never aborts evaluation of the rest
of the list.

This batch never creates, updates, acknowledges, mutes, or resolves an
`Alert`, and never adds an `AlertSetting` mutation method or HTTP route.
Batch 5A (`test_alert_phase6_batch5a.py`), Batch 5B/D25
(`test_alert_phase6_batch5b.py`), and Batch 5C
(`test_alert_setting_phase6_batch5c.py`) are unmodified and run alongside
this module as part of the same suite — their continued passing is the
regression proof for items 26/27 below; nothing in this module patches,
monkeypatches, or otherwise alters those domains."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.domain.alert_setting import AlertSetting
from app.domain.alert_setting_service import AlertSettingService
from app.domain.common import OperationalStatus
from app.errors import ApiError
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
    defaults = {
        "scope_type": "GLOBAL",
        "scope_id": None,
        "alert_type": "PM_DUE_HOUR",
        "enabled": True,
        "setting_status": "ACTIVE",
    }
    defaults.update(overrides)
    return AlertSetting(alert_setting_id=alert_setting_id, **defaults)


NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _future(seconds: int = 3600) -> datetime:
    return NOW + timedelta(seconds=seconds)


def _past(seconds: int = 3600) -> datetime:
    return NOW - timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# 1-2. BASIC ELIGIBILITY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_1_eligible_global_active_enabled_returns_setting() -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0001"))
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-0001"


@pytest.mark.asyncio
async def test_2_enabled_false_returns_none() -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0002", enabled=False))
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None


# ---------------------------------------------------------------------------
# 3-5. CONFIGURATION ANOMALIES -> NONE, SURFACED VIA LOGGING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_3_enabled_none_returns_none_and_logs_anomaly(caplog) -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0003", enabled=None))
    service = AlertSettingService(repo)

    with caplog.at_level("WARNING"):
        result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None
    assert any("ASET-0003" in r.message and "anomaly" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_4_setting_status_none_returns_none_and_logs_anomaly(caplog) -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0004", setting_status=None))
    service = AlertSettingService(repo)

    with caplog.at_level("WARNING"):
        result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None
    assert any("ASET-0004" in r.message and "anomaly" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_5_setting_status_unknown_lowercase_returns_none_and_logs_anomaly(caplog) -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0005", setting_status="active"))
    service = AlertSettingService(repo)

    with caplog.at_level("WARNING"):
        result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None
    assert any("ASET-0005" in r.message and "anomaly" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 6-8. muted_until BOUNDARY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_6_future_muted_until_returns_none() -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0006", muted_until=_future()))
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None


@pytest.mark.asyncio
async def test_7_past_muted_until_is_usable() -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0007", muted_until=_past()))
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-0007"


@pytest.mark.asyncio
async def test_8_muted_until_exactly_equal_to_now_is_usable() -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0008", muted_until=NOW))
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-0008"


# ---------------------------------------------------------------------------
# 9-10. SCOPE ANOMALIES
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_9_global_with_nonblank_scope_id_not_usable_and_logs_anomaly(caplog) -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0009", scope_id="VEH-1"))
    service = AlertSettingService(repo)

    with caplog.at_level("WARNING"):
        result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None
    assert any("ASET-0009" in r.message and "anomaly" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_10_unknown_scope_type_not_usable_and_logs_anomaly(caplog) -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0010", scope_type="REGION"))
    service = AlertSettingService(repo)

    with caplog.at_level("WARNING"):
        result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None
    assert any("ASET-0010" in r.message and "anomaly" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 11-12. MODEL / VEHICLE — UNSUPPORTED, NO PRECEDENCE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_11_model_scope_not_usable_no_precedence() -> None:
    repo = MockRepository()
    repo._alert_settings.append(
        _setting("ASET-0011", scope_type="MODEL", scope_id="MODEL-X")
    )
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None


@pytest.mark.asyncio
async def test_12_vehicle_scope_not_usable_no_precedence() -> None:
    repo = MockRepository()
    repo._alert_settings.append(
        _setting("ASET-0012", scope_type="VEHICLE", scope_id="VEH-1046")
    )
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None


# ---------------------------------------------------------------------------
# 13. VALID GLOBAL + UNSUPPORTED SCOPE -> GLOBAL WINS, NO CONFLICT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_13_valid_global_plus_unsupported_scope_returns_global_no_conflict() -> None:
    repo = MockRepository()
    repo._alert_settings.extend(
        [
            _setting("ASET-0013A", scope_type="VEHICLE", scope_id="VEH-1046"),
            _setting("ASET-0013B"),
        ]
    )
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-0013B"


# ---------------------------------------------------------------------------
# 14. ZERO MATCHING SETTINGS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_14_zero_matching_settings_returns_none() -> None:
    repo = MockRepository()
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("SOME_TYPE_WITH_NO_SETTING", now=NOW)

    assert result is None


# ---------------------------------------------------------------------------
# 15-16. DUPLICATE GLOBAL CONFLICT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_15_duplicate_usable_global_rows_raise_conflict() -> None:
    repo = MockRepository()
    repo._alert_settings.extend(
        [
            _setting("ASET-0015A"),
            _setting("ASET-0015B"),
        ]
    )
    service = AlertSettingService(repo)

    with pytest.raises(ApiError) as exc_info:
        await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert exc_info.value.code == "ALERT_SETTING_GLOBAL_CONFLICT"
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_16_conflict_details_contain_both_setting_ids() -> None:
    repo = MockRepository()
    repo._alert_settings.extend(
        [
            _setting("ASET-0016B"),
            _setting("ASET-0016A"),
        ]
    )
    service = AlertSettingService(repo)

    with pytest.raises(ApiError) as exc_info:
        await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert exc_info.value.details is not None
    assert exc_info.value.details["alert_setting_ids"] == ["ASET-0016A", "ASET-0016B"]


# ---------------------------------------------------------------------------
# 17. VALID GLOBAL + MALFORMED GLOBAL -> VALID WINS, NO CONFLICT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_17_valid_global_plus_malformed_global_no_conflict(caplog) -> None:
    repo = MockRepository()
    repo._alert_settings.extend(
        [
            _setting("ASET-0017A", enabled=None),
            _setting("ASET-0017B"),
        ]
    )
    service = AlertSettingService(repo)

    with caplog.at_level("WARNING"):
        result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-0017B"
    assert any("ASET-0017A" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 18. RESULT DOES NOT DEPEND ON REPOSITORY ORDERING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_18_result_deterministic_regardless_of_repository_order() -> None:
    repo_a = MockRepository()
    repo_a._alert_settings.extend(
        [
            _setting("ASET-0018B", scope_type="MODEL", scope_id="M-1"),
            _setting("ASET-0018A"),
        ]
    )
    repo_b = MockRepository()
    repo_b._alert_settings.extend(
        [
            _setting("ASET-0018A"),
            _setting("ASET-0018B", scope_type="MODEL", scope_id="M-1"),
        ]
    )

    result_a = await AlertSettingService(repo_a).get_effective_global_setting(
        "PM_DUE_HOUR", now=NOW
    )
    result_b = await AlertSettingService(repo_b).get_effective_global_setting(
        "PM_DUE_HOUR", now=NOW
    )

    assert result_a is not None and result_b is not None
    assert result_a.alert_setting_id == result_b.alert_setting_id == "ASET-0018A"


# ---------------------------------------------------------------------------
# 19. EXPLICIT NAIVE now REJECTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_19_explicit_naive_now_rejected() -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0019"))
    service = AlertSettingService(repo)

    naive_now = datetime(2026, 6, 1, 12, 0, 0)  # no tzinfo
    with pytest.raises(ApiError) as exc_info:
        await service.get_effective_global_setting("PM_DUE_HOUR", now=naive_now)

    assert exc_info.value.code == "ALERT_SETTING_EVALUATION_TIME_NOT_TZ_AWARE"
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# 20. muted_until IS NEVER CLEARED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_20_muted_until_is_never_cleared() -> None:
    repo = MockRepository()
    past = _past()
    repo._alert_settings.append(_setting("ASET-0020", muted_until=past))
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.muted_until == past

    stored = await repo.get_alert_setting("ASET-0020")
    assert stored is not None
    assert stored.muted_until == past


# ---------------------------------------------------------------------------
# 21. ZERO REPOSITORY/SHEET WRITES
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_21_evaluation_performs_zero_sheet_writes() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(
        ["ASET-0021", "GLOBAL", "", "PM_DUE_HOUR", "TRUE", "", "", "", "", "", "", "ACTIVE", ""]
    )
    repo = _repo_with_fake_sheets(ws)
    service = AlertSettingService(repo)

    append_row_calls_before = ws.append_row_calls
    append_rows_calls_before = ws.append_rows_calls
    delete_rows_calls_before = ws.delete_rows_calls
    rows_before = len(ws.rows)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)
    service.should_suppress_device_offline(OperationalStatus.MAINTENANCE)

    assert result is not None
    assert result.alert_setting_id == "ASET-0021"
    assert ws.append_row_calls == append_row_calls_before
    assert ws.append_rows_calls == append_rows_calls_before
    assert ws.delete_rows_calls == delete_rows_calls_before
    assert len(ws.rows) == rows_before


# ---------------------------------------------------------------------------
# 22. NO ALERT ROW IS CREATED/UPDATED/RESOLVED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_22_no_alert_row_is_created_or_modified() -> None:
    repo = MockRepository()
    repo._alert_settings.append(_setting("ASET-0022", alert_type="DEVICE_OFFLINE"))
    alerts_before = [a.model_copy(deep=True) for a in repo._alerts]
    service = AlertSettingService(repo)

    await service.get_effective_global_setting("DEVICE_OFFLINE", now=NOW)
    service.should_suppress_device_offline(OperationalStatus.WORKING)

    assert repo._alerts == alerts_before


# ---------------------------------------------------------------------------
# 23. NO ALERTSETTING MUTATION METHOD/API IS INTRODUCED
# ---------------------------------------------------------------------------


def test_23_no_mutation_method_exists_anywhere() -> None:
    forbidden = (
        "create_alert_setting",
        "update_alert_setting",
        "delete_alert_setting",
        "enable_alert_setting",
        "disable_alert_setting",
        "mute_alert_setting",
    )
    for repo_cls in (MockRepository, GoogleSheetsRepository):
        for name in forbidden:
            assert not hasattr(repo_cls, name), (
                f"{repo_cls.__name__} must not expose {name!r} — Batch 5D is "
                "zero-write."
            )
    for name in forbidden:
        assert not hasattr(AlertSettingService, name), (
            f"AlertSettingService must not expose {name!r} — Batch 5D is "
            "zero-write."
        )


@pytest.mark.asyncio
async def test_23b_no_alert_setting_http_route_exists(client) -> None:
    get_list_response = await client.get("/api/v1/alert-settings")
    assert get_list_response.status_code == 404

    post_response = await client.post("/api/v1/alert-settings", json={})
    assert post_response.status_code == 404


# ---------------------------------------------------------------------------
# 24. auto_reenable_on_online HAS ZERO EFFECT ON RESOLVER BEHAVIOR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_24_auto_reenable_on_online_has_zero_effect() -> None:
    repo_true = MockRepository()
    repo_true._alert_settings.append(
        _setting("ASET-0024T", alert_type="DEVICE_OFFLINE", auto_reenable_on_online=True)
    )
    repo_false = MockRepository()
    repo_false._alert_settings.append(
        _setting("ASET-0024F", alert_type="DEVICE_OFFLINE", auto_reenable_on_online=False)
    )
    repo_none = MockRepository()
    repo_none._alert_settings.append(
        _setting("ASET-0024N", alert_type="DEVICE_OFFLINE", auto_reenable_on_online=None)
    )

    result_true = await AlertSettingService(repo_true).get_effective_global_setting(
        "DEVICE_OFFLINE", now=NOW
    )
    result_false = await AlertSettingService(repo_false).get_effective_global_setting(
        "DEVICE_OFFLINE", now=NOW
    )
    result_none = await AlertSettingService(repo_none).get_effective_global_setting(
        "DEVICE_OFFLINE", now=NOW
    )

    assert result_true is not None and result_true.alert_setting_id == "ASET-0024T"
    assert result_false is not None and result_false.alert_setting_id == "ASET-0024F"
    assert result_none is not None and result_none.alert_setting_id == "ASET-0024N"


# ---------------------------------------------------------------------------
# 25. EXACT DEVICE_OFFLINE SUPPRESSION TABLE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_25_device_offline_suppression_table_matches_d26_exactly() -> None:
    repo = MockRepository()
    service = AlertSettingService(repo)

    expected = {
        OperationalStatus.WORKING: False,
        OperationalStatus.READY: False,
        OperationalStatus.MAINTENANCE: True,
        OperationalStatus.OUT_OF_SERVICE: True,
        OperationalStatus.LONG_TERM_PARKING: True,
    }
    assert set(expected.keys()) == set(OperationalStatus)

    for status_value, expected_suppress in expected.items():
        assert service.should_suppress_device_offline(status_value) is expected_suppress


# ---------------------------------------------------------------------------
# 26-27. D25 LIFECYCLE / BATCH 5C READ-FOUNDATION REGRESSION
# ---------------------------------------------------------------------------
#
# Proven by `test_alert_phase6_batch5a.py`, `test_alert_phase6_batch5b.py`,
# and `test_alert_setting_phase6_batch5c.py` running unmodified as part of
# the same suite (see the Batch 5D verification report). This module does
# not patch, monkeypatch, or otherwise alter `Alert`/`AlertService`/
# `AlertStatus`/`AlertSeverity`, the `alert` sheet schema/repository
# methods, or any Batch 5C `AlertSetting` read behavior.


def test_26_alert_domain_module_is_untouched_by_this_batch() -> None:
    from app.domain.alert import Alert, AlertSeverity, AlertStatus

    assert {s.value for s in AlertSeverity} == {"INFO", "WARNING", "CRITICAL"}
    assert {s.value for s in AlertStatus} == {"ACTIVE", "ACKNOWLEDGED", "MUTED", "RESOLVED"}
    assert set(Alert.model_fields.keys()) == {
        "alert_id", "vehicle_id", "alert_type", "source_type", "source_id",
        "severity", "created_at", "alert_status", "muted_until",
        "acknowledged_by_user_id", "acknowledged_at", "resolved_at", "message_th",
    }


def test_27_alert_setting_schema_is_untouched_by_this_batch() -> None:
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
    assert set(AlertSetting.model_fields.keys()) == {
        "alert_setting_id", "scope_type", "scope_id", "alert_type", "enabled",
        "threshold_value", "threshold_unit", "lead_value", "lead_unit",
        "muted_until", "auto_reenable_on_online", "setting_status", "note_th",
    }


# ---------------------------------------------------------------------------
# 28. MALFORMED ROW FOR AN UNRELATED alert_type DOES NOT BLOCK RESOLUTION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_28_malformed_row_for_unrelated_type_does_not_block_target_type() -> None:
    repo = MockRepository()
    repo._alert_settings.extend(
        [
            _setting("ASET-0028X", alert_type="DEVICE_OFFLINE", enabled=None),
            _setting("ASET-0028Y", alert_type="PM_DUE_HOUR"),
        ]
    )
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-0028Y"


# ---------------------------------------------------------------------------
# GAP FIX — malformed NONBLANK source values must fail closed, not
# silently collapse to the same representation as a genuinely blank cell
# (post-commit 133c345 source review). Exercised against the FAKE GOOGLE
# SHEETS repository path, since a malformed raw STRING only exists there
# — MockRepository/AlertSetting construction is already strongly typed
# and cannot represent "the string 'not-a-date' in a datetime field".
# ---------------------------------------------------------------------------


def _row(
    alert_setting_id: str,
    scope_type: str = "GLOBAL",
    scope_id: str = "",
    alert_type: str = "PM_DUE_HOUR",
    enabled: str = "TRUE",
    threshold_value: str = "",
    threshold_unit: str = "",
    lead_value: str = "",
    lead_unit: str = "",
    muted_until: str = "",
    auto_reenable_on_online: str = "",
    setting_status: str = "ACTIVE",
    note_th: str = "",
) -> list:
    return [
        alert_setting_id, scope_type, scope_id, alert_type, enabled,
        threshold_value, threshold_unit, lead_value, lead_unit, muted_until,
        auto_reenable_on_online, setting_status, note_th,
    ]


@pytest.mark.asyncio
async def test_gap_1_malformed_muted_until_not_usable_and_logs_anomaly(caplog) -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(_row("ASET-G1", muted_until="not-a-date"))
    repo = _repo_with_fake_sheets(ws)
    service = AlertSettingService(repo)

    with caplog.at_level("WARNING"):
        result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None
    assert any(
        "ASET-G1" in r.message and "anomaly" in r.message and "muted_until" in r.message
        for r in caplog.records
    )
    # And the parser itself never silently converted it into a legitimate
    # blank — the parsed field is still honestly `None` (never fabricated),
    # but the private marker records that this was NOT a genuine blank.
    stored = await repo.get_alert_setting("ASET-G1")
    assert stored is not None
    assert stored.muted_until is None
    assert stored.has_malformed_field("muted_until") is True


@pytest.mark.asyncio
async def test_gap_2_malformed_muted_until_row_does_not_block_valid_same_type_row() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(_row("ASET-G2A", muted_until="not-a-date"))
    ws.append_row(_row("ASET-G2B"))
    repo = _repo_with_fake_sheets(ws)
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-G2B"


@pytest.mark.asyncio
async def test_gap_3_malformed_enabled_not_usable_and_logs_anomaly(caplog) -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(_row("ASET-G3", enabled="MAYBE"))
    repo = _repo_with_fake_sheets(ws)
    service = AlertSettingService(repo)

    with caplog.at_level("WARNING"):
        result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is None
    assert any(
        "ASET-G3" in r.message and "anomaly" in r.message and "enabled" in r.message
        for r in caplog.records
    )
    stored = await repo.get_alert_setting("ASET-G3")
    assert stored is not None
    assert stored.enabled is False  # conservative parsed value, never fabricated True
    assert stored.has_malformed_field("enabled") is True


@pytest.mark.asyncio
async def test_gap_4_malformed_enabled_row_does_not_block_valid_same_type_row() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(_row("ASET-G4A", enabled="MAYBE"))
    ws.append_row(_row("ASET-G4B"))
    repo = _repo_with_fake_sheets(ws)
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-G4B"


@pytest.mark.asyncio
async def test_gap_5_blank_muted_until_remains_valid_absence() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(_row("ASET-G5", muted_until=""))
    repo = _repo_with_fake_sheets(ws)
    service = AlertSettingService(repo)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-G5"
    assert result.muted_until is None
    assert result.has_malformed_field("muted_until") is False


@pytest.mark.asyncio
async def test_gap_6_true_false_blank_enabled_behavior_unchanged(caplog) -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(_row("ASET-G6T", enabled="TRUE"))
    ws.append_row(_row("ASET-G6F", enabled="FALSE", alert_type="PM_DUE_KM"))
    ws.append_row(_row("ASET-G6N", enabled="", alert_type="INACTIVE_VEHICLE"))
    repo = _repo_with_fake_sheets(ws)
    service = AlertSettingService(repo)

    with caplog.at_level("WARNING"):
        result_true = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)
        result_false = await service.get_effective_global_setting("PM_DUE_KM", now=NOW)
        result_none = await service.get_effective_global_setting("INACTIVE_VEHICLE", now=NOW)

    assert result_true is not None and result_true.alert_setting_id == "ASET-G6T"
    assert result_true.has_malformed_field("enabled") is False
    assert result_false is None  # normal ineligibility, not an anomaly
    assert not any("ASET-G6F" in r.message for r in caplog.records)
    assert result_none is None  # NULL enabled IS an anomaly
    assert any("ASET-G6N" in r.message and "anomaly" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_gap_7_no_writes_occur_for_malformed_rows() -> None:
    ws = _ws(schemas.ALERT_SETTING_SHEET)
    ws.append_row(_row("ASET-G7A", muted_until="not-a-date"))
    ws.append_row(_row("ASET-G7B", enabled="MAYBE"))
    ws.append_row(_row("ASET-G7C"))
    repo = _repo_with_fake_sheets(ws)
    service = AlertSettingService(repo)

    append_row_calls_before = ws.append_row_calls
    append_rows_calls_before = ws.append_rows_calls
    delete_rows_calls_before = ws.delete_rows_calls
    rows_before = len(ws.rows)

    result = await service.get_effective_global_setting("PM_DUE_HOUR", now=NOW)

    assert result is not None
    assert result.alert_setting_id == "ASET-G7C"
    assert ws.append_row_calls == append_row_calls_before
    assert ws.append_rows_calls == append_rows_calls_before
    assert ws.delete_rows_calls == delete_rows_calls_before
    assert len(ws.rows) == rows_before


# Item 8 (full Batch 5A/5B/5C/5D suite remains green) is proven by running
# this module alongside test_alert_phase6_batch5a.py/test_alert_phase6_
# batch5b.py/test_alert_setting_phase6_batch5c.py in the same pytest
# invocation (see the Batch 5D gap-fix verification report) — not
# re-asserted as a single test here, consistent with items 26/27 above.
