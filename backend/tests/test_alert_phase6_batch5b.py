"""Web/API Phase 6 Batch 5B — Alert Lifecycle Core + D25 Governance Freeze.

Proves D25 (APPROVED/FROZEN — see `docs/project-governance/
OPEN_DECISIONS_REGISTER_EN.txt` A07), implemented entirely as INTERNAL
`AlertService`/repository methods:

- open-identity dedup (`ensure_condition_alert`): the
  `(vehicle_id, alert_type, source_type, source_id)` tuple, exact-equality
  only; exactly one open (ACTIVE/ACKNOWLEDGED/MUTED) match is reused
  unchanged; more than one open match is an honest
  `ALERT_OPEN_IDENTITY_CONFLICT` (the non-transactional-write race); zero
  open matches creates a brand-new row using the caller-supplied
  `alert_id` (never generated here)
- acknowledge/mute/mute-expiry/resolve transitions, each independently
  idempotent, each failing honestly on an invalid source status
- no reopen: RESOLVED is terminal; recurrence creates a new row
- `GoogleSheetsRepository`'s three new methods persist exactly the given
  state with no business logic of their own
- no HTTP mutation route exists anywhere in this batch — `app.api.v1.
  alerts` is unchanged
- A07 is now APPROVED/FROZEN recording D25; A06 is untouched by this
  batch"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.domain.alert import Alert, AlertSeverity, AlertStatus
from app.domain.alert_service import AlertService
from app.errors import ApiError
from app.repositories.base import RepositoryError
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.mock import MockRepository

from tests.test_google_sheets_real_io import (
    FakeSpreadsheet,
    FakeWorksheet,
    _parse_single_row_range,
    _ws,
)

VEHICLE_ID = "VEH-1046"  # pre-seeded by MockRepository's seed data (see test_alert_phase6_batch5a.py)


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


def _alert_row(
    alert_id: str = "ALT-1",
    vehicle_id: str = "VEH-1",
    alert_type: str = "",
    source_type: str = "",
    source_id: str = "",
    severity: str = "",
    created_at: str = "2026-01-01T00:00:00+00:00",
    alert_status: str = "",
    muted_until: str = "",
    acknowledged_by_user_id: str = "",
    acknowledged_at: str = "",
    resolved_at: str = "",
    message_th: str = "",
) -> list:
    return [
        alert_id, vehicle_id, alert_type, source_type, source_id, severity,
        created_at, alert_status, muted_until, acknowledged_by_user_id,
        acknowledged_at, resolved_at, message_th,
    ]


def _future(seconds: int = 3600) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _past(seconds: int = 3600) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def _seed(repo: MockRepository, alert: Alert) -> Alert:
    return await repo.create_alert(alert)


def _alert(
    alert_id: str,
    vehicle_id: str = VEHICLE_ID,
    alert_type: str | None = "PM_DUE",
    source_type: str | None = "PM_WORK_ORDER",
    source_id: str | None = "WO-1",
    created_at: datetime | None = None,
    alert_status: AlertStatus | None = AlertStatus.ACTIVE,
    **overrides,
) -> Alert:
    return Alert(
        alert_id=alert_id,
        vehicle_id=vehicle_id,
        alert_type=alert_type,
        source_type=source_type,
        source_id=source_id,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        alert_status=alert_status,
        **overrides,
    )


# ---------------------------------------------------------------------------
# A. IDENTITY / DEDUP — ensure_condition_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a1_creates_new_active_alert_when_no_identity_match() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    created = await service.ensure_condition_alert(
        alert_id="ALT-A1",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-1",
        severity=AlertSeverity.WARNING,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th="msg",
    )
    assert created.alert_id == "ALT-A1"
    assert created.alert_status == AlertStatus.ACTIVE
    assert created.severity == AlertSeverity.WARNING


@pytest.mark.asyncio
async def test_a2_reuses_unchanged_existing_open_active_alert() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-EXIST", alert_status=AlertStatus.ACTIVE, severity=AlertSeverity.INFO))
    service = AlertService(repo)
    result = await service.ensure_condition_alert(
        alert_id="ALT-NEW-WOULD-BE",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-1",
        severity=AlertSeverity.CRITICAL,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        message_th="different message",
    )
    assert result.alert_id == "ALT-EXIST"
    assert result.severity == AlertSeverity.INFO  # unchanged, never overwritten
    assert result.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_a3_reuses_unchanged_existing_open_acknowledged_alert() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-ACK", alert_status=AlertStatus.ACKNOWLEDGED))
    service = AlertService(repo)
    result = await service.ensure_condition_alert(
        alert_id="ALT-IGNORED",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-1",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert result.alert_id == "ALT-ACK"


@pytest.mark.asyncio
async def test_a4_reuses_unchanged_existing_open_muted_alert() -> None:
    repo = MockRepository()
    await _seed(
        repo,
        _alert("ALT-MUTED", alert_status=AlertStatus.MUTED, muted_until=_future()),
    )
    service = AlertService(repo)
    result = await service.ensure_condition_alert(
        alert_id="ALT-IGNORED",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-1",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert result.alert_id == "ALT-MUTED"


@pytest.mark.asyncio
async def test_a5_creates_new_row_when_only_resolved_row_exists_for_identity() -> None:
    repo = MockRepository()
    await _seed(
        repo,
        _alert("ALT-OLD-RESOLVED", alert_status=AlertStatus.RESOLVED, resolved_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
    )
    service = AlertService(repo)
    recurrence = await service.ensure_condition_alert(
        alert_id="ALT-RECUR-1",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-1",
        severity=AlertSeverity.WARNING,
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert recurrence.alert_id == "ALT-RECUR-1"
    assert recurrence.alert_status == AlertStatus.ACTIVE
    # the resolved row still exists, untouched
    old = await repo.get_alert("ALT-OLD-RESOLVED")
    assert old is not None
    assert old.alert_status == AlertStatus.RESOLVED


@pytest.mark.asyncio
async def test_a6_open_identity_conflict_when_two_open_rows_match() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-OPEN-1", alert_status=AlertStatus.ACTIVE))
    await _seed(repo, _alert("ALT-OPEN-2", alert_status=AlertStatus.ACKNOWLEDGED))
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.ensure_condition_alert(
            alert_id="ALT-NEW",
            vehicle_id=VEHICLE_ID,
            alert_type="PM_DUE",
            source_type="PM_WORK_ORDER",
            source_id="WO-1",
            severity=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            message_th=None,
        )
    assert exc_info.value.code == "ALERT_OPEN_IDENTITY_CONFLICT"
    assert set(exc_info.value.details["open_alert_ids"]) == {"ALT-OPEN-1", "ALT-OPEN-2"}


@pytest.mark.asyncio
async def test_a7_identity_distinguishes_by_vehicle_id() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-OTHER-VEHICLE", vehicle_id="VEH-9999", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    created = await service.ensure_condition_alert(
        alert_id="ALT-DIFFERENT-VEHICLE",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-1",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert created.alert_id == "ALT-DIFFERENT-VEHICLE"


@pytest.mark.asyncio
async def test_a8_identity_distinguishes_by_alert_type() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-OTHER-TYPE", alert_type="DEVICE_OFFLINE", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    created = await service.ensure_condition_alert(
        alert_id="ALT-DIFFERENT-TYPE",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-1",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert created.alert_id == "ALT-DIFFERENT-TYPE"


@pytest.mark.asyncio
async def test_a9_identity_distinguishes_by_source_type_and_source_id() -> None:
    repo = MockRepository()
    await _seed(
        repo,
        _alert("ALT-OTHER-SOURCE", source_type="PM_WORK_ORDER", source_id="WO-999", alert_status=AlertStatus.ACTIVE),
    )
    service = AlertService(repo)
    created = await service.ensure_condition_alert(
        alert_id="ALT-DIFFERENT-SOURCE",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-1",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert created.alert_id == "ALT-DIFFERENT-SOURCE"


@pytest.mark.asyncio
async def test_a10_none_source_fields_never_match_a_non_none_row() -> None:
    repo = MockRepository()
    await _seed(
        repo,
        _alert("ALT-WITH-SOURCE", source_type="PM_WORK_ORDER", source_id="WO-1", alert_status=AlertStatus.ACTIVE),
    )
    service = AlertService(repo)
    created = await service.ensure_condition_alert(
        alert_id="ALT-NO-SOURCE",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type=None,
        source_id=None,
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert created.alert_id == "ALT-NO-SOURCE"


@pytest.mark.asyncio
async def test_a11_alert_id_already_exists_rejected() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-TAKEN", alert_type="OTHER_TYPE", alert_status=AlertStatus.RESOLVED))
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.ensure_condition_alert(
            alert_id="ALT-TAKEN",
            vehicle_id=VEHICLE_ID,
            alert_type="PM_DUE",
            source_type="PM_WORK_ORDER",
            source_id="WO-1",
            severity=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            message_th=None,
        )
    assert exc_info.value.code == "ALERT_ID_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_a12_blank_alert_id_rejected() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.ensure_condition_alert(
            alert_id="   ",
            vehicle_id=VEHICLE_ID,
            alert_type="PM_DUE",
            source_type=None,
            source_id=None,
            severity=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            message_th=None,
        )
    assert exc_info.value.code == "ALERT_ID_REQUIRED"


@pytest.mark.asyncio
async def test_a13_blank_alert_type_rejected() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.ensure_condition_alert(
            alert_id="ALT-X",
            vehicle_id=VEHICLE_ID,
            alert_type="",
            source_type=None,
            source_id=None,
            severity=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            message_th=None,
        )
    assert exc_info.value.code == "ALERT_TYPE_REQUIRED"


@pytest.mark.asyncio
async def test_a14_non_tz_aware_created_at_rejected() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.ensure_condition_alert(
            alert_id="ALT-X",
            vehicle_id=VEHICLE_ID,
            alert_type="PM_DUE",
            source_type=None,
            source_id=None,
            severity=None,
            created_at=datetime(2026, 1, 1),  # naive
            message_th=None,
        )
    assert exc_info.value.code == "ALERT_CREATED_AT_NOT_TZ_AWARE"


@pytest.mark.asyncio
async def test_a15_unknown_vehicle_rejected() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.ensure_condition_alert(
            alert_id="ALT-X",
            vehicle_id="VEH-DOES-NOT-EXIST",
            alert_type="PM_DUE",
            source_type=None,
            source_id=None,
            severity=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            message_th=None,
        )
    assert exc_info.value.code == "VEHICLE_NOT_FOUND"


# ---------------------------------------------------------------------------
# B. ACKNOWLEDGEMENT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b1_active_to_acknowledged_succeeds() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-B1", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    result = await service.acknowledge_alert("ALT-B1", "USR-1")
    assert result.alert_status == AlertStatus.ACKNOWLEDGED
    assert result.acknowledged_by_user_id == "USR-1"
    assert result.acknowledged_at is not None


@pytest.mark.asyncio
async def test_b2_acknowledge_idempotent_preserves_original_provenance() -> None:
    repo = MockRepository()
    original_ts = datetime(2026, 1, 5, tzinfo=timezone.utc)
    await _seed(
        repo,
        _alert(
            "ALT-B2",
            alert_status=AlertStatus.ACKNOWLEDGED,
            acknowledged_by_user_id="USR-ORIGINAL",
            acknowledged_at=original_ts,
        ),
    )
    service = AlertService(repo)
    result = await service.acknowledge_alert("ALT-B2", "USR-DIFFERENT")
    assert result.acknowledged_by_user_id == "USR-ORIGINAL"
    assert result.acknowledged_at == original_ts


@pytest.mark.asyncio
async def test_b3_acknowledge_rejects_from_muted() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-B3", alert_status=AlertStatus.MUTED, muted_until=_future()))
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.acknowledge_alert("ALT-B3", "USR-1")
    assert exc_info.value.code == "ALERT_ACKNOWLEDGE_INVALID_TRANSITION"


@pytest.mark.asyncio
async def test_b4_acknowledge_rejects_from_resolved() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-B4", alert_status=AlertStatus.RESOLVED, resolved_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.acknowledge_alert("ALT-B4", "USR-1")
    assert exc_info.value.code == "ALERT_ACKNOWLEDGE_INVALID_TRANSITION"


@pytest.mark.asyncio
async def test_b5_blank_acknowledged_by_user_id_rejected() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-B5", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.acknowledge_alert("ALT-B5", "   ")
    assert exc_info.value.code == "ALERT_ACKNOWLEDGED_BY_USER_ID_REQUIRED"


@pytest.mark.asyncio
async def test_b6_acknowledge_missing_alert_404() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.acknowledge_alert("ALT-DOES-NOT-EXIST", "USR-1")
    assert exc_info.value.code == "ALERT_NOT_FOUND"
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# C. MUTE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c1_active_to_muted_succeeds() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-C1", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    until = _future()
    result = await service.mute_alert("ALT-C1", until)
    assert result.alert_status == AlertStatus.MUTED
    assert result.muted_until == until


@pytest.mark.asyncio
async def test_c2_acknowledged_to_muted_succeeds() -> None:
    repo = MockRepository()
    await _seed(
        repo,
        _alert(
            "ALT-C2",
            alert_status=AlertStatus.ACKNOWLEDGED,
            acknowledged_by_user_id="USR-1",
            acknowledged_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    service = AlertService(repo)
    until = _future()
    result = await service.mute_alert("ALT-C2", until)
    assert result.alert_status == AlertStatus.MUTED
    assert result.acknowledged_by_user_id == "USR-1"  # provenance preserved while muting


@pytest.mark.asyncio
async def test_c3_mute_idempotent_when_same_muted_until() -> None:
    repo = MockRepository()
    until = _future()
    await _seed(repo, _alert("ALT-C3", alert_status=AlertStatus.MUTED, muted_until=until))
    service = AlertService(repo)
    result = await service.mute_alert("ALT-C3", until)
    assert result.alert_status == AlertStatus.MUTED
    assert result.muted_until == until


@pytest.mark.asyncio
async def test_c4_mute_rejects_conflicting_muted_until_when_already_muted() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-C4", alert_status=AlertStatus.MUTED, muted_until=_future(1000)))
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.mute_alert("ALT-C4", _future(2000))
    assert exc_info.value.code == "ALERT_MUTE_CONFLICTING_MUTED_UNTIL"


@pytest.mark.asyncio
async def test_c5_mute_rejects_from_resolved() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-C5", alert_status=AlertStatus.RESOLVED, resolved_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.mute_alert("ALT-C5", _future())
    assert exc_info.value.code == "ALERT_MUTE_INVALID_TRANSITION"


@pytest.mark.asyncio
async def test_c6_mute_rejects_naive_datetime() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-C6", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.mute_alert("ALT-C6", datetime.now() + timedelta(hours=1))
    assert exc_info.value.code == "ALERT_MUTED_UNTIL_NOT_TZ_AWARE"


@pytest.mark.asyncio
async def test_c7_mute_rejects_past_or_present_muted_until() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-C7", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.mute_alert("ALT-C7", _past())
    assert exc_info.value.code == "ALERT_MUTED_UNTIL_NOT_FUTURE"


@pytest.mark.asyncio
async def test_c8_mute_missing_alert_404() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    with pytest.raises(ApiError) as exc_info:
        await service.mute_alert("ALT-DOES-NOT-EXIST", _future())
    assert exc_info.value.code == "ALERT_NOT_FOUND"


# ---------------------------------------------------------------------------
# D. MUTE EXPIRY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d1_reconcile_noop_when_not_muted() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-D1", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    result = await service.reconcile_mute_expiry("ALT-D1")
    assert result.alert_status == AlertStatus.ACTIVE


@pytest.mark.asyncio
async def test_d2_reconcile_noop_when_muted_until_in_future() -> None:
    repo = MockRepository()
    until = _future()
    await _seed(repo, _alert("ALT-D2", alert_status=AlertStatus.MUTED, muted_until=until))
    service = AlertService(repo)
    result = await service.reconcile_mute_expiry("ALT-D2")
    assert result.alert_status == AlertStatus.MUTED
    assert result.muted_until == until


@pytest.mark.asyncio
async def test_d3_reconcile_transitions_to_active_when_never_acknowledged() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-D3", alert_status=AlertStatus.MUTED, muted_until=_past()))
    service = AlertService(repo)
    result = await service.reconcile_mute_expiry("ALT-D3")
    assert result.alert_status == AlertStatus.ACTIVE


@pytest.mark.asyncio
async def test_d4_reconcile_transitions_to_acknowledged_when_previously_acknowledged() -> None:
    repo = MockRepository()
    await _seed(
        repo,
        _alert(
            "ALT-D4",
            alert_status=AlertStatus.MUTED,
            muted_until=_past(),
            acknowledged_by_user_id="USR-1",
            acknowledged_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    service = AlertService(repo)
    result = await service.reconcile_mute_expiry("ALT-D4")
    assert result.alert_status == AlertStatus.ACKNOWLEDGED
    assert result.acknowledged_by_user_id == "USR-1"


@pytest.mark.asyncio
async def test_d5_reconcile_preserves_muted_until_after_expiry() -> None:
    repo = MockRepository()
    past = _past()
    await _seed(repo, _alert("ALT-D5", alert_status=AlertStatus.MUTED, muted_until=past))
    service = AlertService(repo)
    result = await service.reconcile_mute_expiry("ALT-D5")
    assert result.muted_until == past


@pytest.mark.asyncio
async def test_d6_reconcile_fails_honestly_when_muted_until_missing() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-D6", alert_status=AlertStatus.MUTED, muted_until=None))
    service = AlertService(repo)
    with pytest.raises(RepositoryError):
        await service.reconcile_mute_expiry("ALT-D6")


# ---------------------------------------------------------------------------
# E. RESOLUTION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e1_resolve_from_active_succeeds() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-E1", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    result = await service.resolve_condition_alert("ALT-E1")
    assert result.alert_status == AlertStatus.RESOLVED
    assert result.resolved_at is not None


@pytest.mark.asyncio
async def test_e2_resolve_from_acknowledged_succeeds() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-E2", alert_status=AlertStatus.ACKNOWLEDGED))
    service = AlertService(repo)
    result = await service.resolve_condition_alert("ALT-E2")
    assert result.alert_status == AlertStatus.RESOLVED


@pytest.mark.asyncio
async def test_e3_resolve_from_muted_succeeds() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-E3", alert_status=AlertStatus.MUTED, muted_until=_future()))
    service = AlertService(repo)
    result = await service.resolve_condition_alert("ALT-E3")
    assert result.alert_status == AlertStatus.RESOLVED


@pytest.mark.asyncio
async def test_e4_resolve_idempotent_preserves_original_resolved_at() -> None:
    repo = MockRepository()
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await _seed(repo, _alert("ALT-E4", alert_status=AlertStatus.RESOLVED, resolved_at=original))
    service = AlertService(repo)
    result = await service.resolve_condition_alert("ALT-E4")
    assert result.resolved_at == original


def test_e5_resolve_is_terminal_no_reopen_method_exists() -> None:
    # D25: RESOLVED is terminal — no reopen/reactivate method exists on
    # AlertService at all.
    method_names = {name for name in dir(AlertService) if not name.startswith("_")}
    assert not any("reopen" in name.lower() or "reactivate" in name.lower() for name in method_names)


@pytest.mark.asyncio
async def test_e6_recurrence_after_resolution_creates_new_alert_id() -> None:
    repo = MockRepository()
    await _seed(repo, _alert("ALT-E6-FIRST", alert_status=AlertStatus.ACTIVE))
    service = AlertService(repo)
    resolved = await service.resolve_condition_alert("ALT-E6-FIRST")
    assert resolved.alert_status == AlertStatus.RESOLVED

    recurrence = await service.ensure_condition_alert(
        alert_id="ALT-E6-SECOND",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-1",
        severity=None,
        created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert recurrence.alert_id == "ALT-E6-SECOND"
    assert recurrence.alert_status == AlertStatus.ACTIVE
    first_still_resolved = await repo.get_alert("ALT-E6-FIRST")
    assert first_still_resolved.alert_status == AlertStatus.RESOLVED


# ---------------------------------------------------------------------------
# F. GOOGLE SHEETS — new repository methods persist exactly what they're given
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f1_sheets_create_alert_appends_row_and_round_trips() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    repo = _repo_with_fake_sheets(ws)
    alert = Alert(
        alert_id="ALT-NEW-1",
        vehicle_id="VEH-1",
        alert_type="PM_DUE",
        source_type="PM_WORK_ORDER",
        source_id="WO-000123",
        severity=AlertSeverity.WARNING,
        created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        alert_status=AlertStatus.ACTIVE,
        message_th="test message",
    )
    created = await repo.create_alert(alert)
    assert created.alert_id == "ALT-NEW-1"
    assert ws.append_row_calls == 1

    fetched = await repo.get_alert("ALT-NEW-1")
    assert fetched is not None
    assert fetched.alert_type == "PM_DUE"
    assert fetched.source_id == "WO-000123"
    assert fetched.severity == AlertSeverity.WARNING
    assert fetched.alert_status == AlertStatus.ACTIVE
    assert fetched.message_th == "test message"


@pytest.mark.asyncio
async def test_f2_sheets_create_alert_rejects_duplicate_alert_id() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(_alert_row("ALT-DUP", "VEH-1"))
    repo = _repo_with_fake_sheets(ws)
    dup = Alert(alert_id="ALT-DUP", vehicle_id="VEH-2", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(RepositoryError):
        await repo.create_alert(dup)


@pytest.mark.asyncio
async def test_f3_sheets_update_alert_lifecycle_preserves_other_columns() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(
        _alert_row(
            "ALT-U1", "VEH-1", "PM_DUE", "PM_WORK_ORDER", "WO-1",
            "CRITICAL", "2026-01-01T00:00:00+00:00", "ACTIVE",
            message_th="original message",
        )
    )
    repo = _repo_with_fake_sheets(ws)
    updated = await repo.update_alert_lifecycle(
        "ALT-U1",
        alert_status=AlertStatus.ACKNOWLEDGED,
        muted_until=None,
        acknowledged_by_user_id="USR-9",
        acknowledged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        resolved_at=None,
    )
    assert updated.alert_status == AlertStatus.ACKNOWLEDGED
    assert updated.acknowledged_by_user_id == "USR-9"
    assert updated.alert_type == "PM_DUE"
    assert updated.source_id == "WO-1"
    assert updated.severity == AlertSeverity.CRITICAL
    assert updated.message_th == "original message"
    assert updated.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)

    refetched = await repo.get_alert("ALT-U1")
    assert refetched is not None
    assert refetched.alert_status == AlertStatus.ACKNOWLEDGED
    assert refetched.message_th == "original message"


@pytest.mark.asyncio
async def test_f4_sheets_update_alert_lifecycle_missing_alert_raises() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    repo = _repo_with_fake_sheets(ws)
    with pytest.raises(RepositoryError):
        await repo.update_alert_lifecycle(
            "ALT-MISSING",
            alert_status=AlertStatus.RESOLVED,
            muted_until=None,
            acknowledged_by_user_id=None,
            acknowledged_at=None,
            resolved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_f5_sheets_list_alerts_by_identity_exact_match_only() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(_alert_row("ALT-1", "VEH-1", "PM_DUE", "PM_WORK_ORDER", "WO-1", alert_status="ACTIVE"))
    ws.append_row(_alert_row("ALT-2", "VEH-1", "PM_DUE", "PM_WORK_ORDER", "WO-2", alert_status="ACTIVE"))
    ws.append_row(_alert_row("ALT-3", "VEH-1", "PM_DUE", alert_status="ACTIVE"))
    repo = _repo_with_fake_sheets(ws)

    matches = await repo.list_alerts_by_identity("VEH-1", "PM_DUE", "PM_WORK_ORDER", "WO-1")
    assert [a.alert_id for a in matches] == ["ALT-1"]

    none_source_matches = await repo.list_alerts_by_identity("VEH-1", "PM_DUE", None, None)
    assert [a.alert_id for a in none_source_matches] == ["ALT-3"]


@pytest.mark.asyncio
async def test_f6_sheets_create_alert_force_texts_opaque_source_id() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    repo = _repo_with_fake_sheets(ws)
    alert = Alert(
        alert_id="ALT-LZ",
        vehicle_id="VEH-1",
        source_type="COMPONENT",
        source_id="000042",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    await repo.create_alert(alert)
    fetched = await repo.get_alert("ALT-LZ")
    assert fetched is not None
    assert fetched.source_id == "000042"
    assert fetched.source_id != 42  # type: ignore[comparison-overlap]


# ---------------------------------------------------------------------------
# G. API BOUNDARY — no lifecycle mutation route exists anywhere in this batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g1_no_lifecycle_mutation_routes_exist(client: AsyncClient) -> None:
    # R7 Whole-Phase (Owner gate 2026-11-17, policy R1 P-9): acknowledge / mute now exist as
    # TEST-only actions; a legacy actor (no TEST grant) is always refused. Resolve / reopen /
    # mute-expiry reconciliation are still never routable (resolution is source-driven only).
    for action in ("resolve", "reopen", "reconcile-mute-expiry"):
        response = await client.post(f"/api/v1/alerts/ALT-1/{action}", json={})
        assert response.status_code == 404, f"{action} unexpectedly routable: {response.status_code}"
    for action in ("acknowledge", "mute"):
        response = await client.post(f"/api/v1/alerts/ALT-1/{action}", json={})
        assert response.status_code in (403, 422), f"{action} not refused: {response.status_code}"


@pytest.mark.asyncio
async def test_g2_existing_get_routes_still_work(client: AsyncClient) -> None:
    from app.dependencies import get_repository

    repo = get_repository()
    repo._alerts.append(_alert("ALT-G2"))  # type: ignore[attr-defined]
    response = await client.get(f"/api/v1/vehicles/{VEHICLE_ID}/alerts")
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# H. GOVERNANCE — A07 recorded D25, A06 untouched
# ---------------------------------------------------------------------------

_GOVERNANCE_DOC = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project-governance"
    / "OPEN_DECISIONS_REGISTER_EN.txt"
).read_text(encoding="utf-8")


def test_h1_a07_is_approved_frozen_not_tbd_blocking() -> None:
    a07_section = _GOVERNANCE_DOC.split("A07 Alert Deduplication / Auto-Resolve")[1]
    a07_section = a07_section.split("A08 Soft Delete")[0]
    assert "APPROVED / FROZEN" in a07_section
    assert "TBD-BLOCKING" not in a07_section


def test_h2_a07_mentions_d25_and_key_lifecycle_terms() -> None:
    a07_section = _GOVERNANCE_DOC.split("A07 Alert Deduplication / Auto-Resolve")[1]
    a07_section = a07_section.split("A08 Soft Delete")[0]
    assert "D25" in a07_section
    for term in ("ALERT_OPEN_IDENTITY_CONFLICT", "RESOLVED", "muted_until", "idempotent"):
        assert term in a07_section


def test_h3_a06_unchanged_by_this_batch() -> None:
    a06_section = _GOVERNANCE_DOC.split("A06 Alert Severity Model")[1]
    a06_section = a06_section.split("A07 Alert Deduplication")[0]
    assert "APPROVED / FROZEN (vocabulary only)" in a06_section
    assert "D24" in a06_section
    assert "D25" not in a06_section


# ---------------------------------------------------------------------------
# B5B-01 REVIEW FIX — GoogleSheetsRepository.update_alert_lifecycle must
# write ONLY the 5 lifecycle columns, never rewrite the row in full.
# ---------------------------------------------------------------------------

_ORIGINAL_ALERT_ROW = [
    "ALT-U1", "VEH-1", "PM_DUE", "PM_WORK_ORDER", "000009",
    "CRITICAL", "2026-01-01T00:00:00+00:00", "ACTIVE",
    "", "", "", "", "original message",
]

_LIFECYCLE_COLUMNS = {
    "alert_status", "muted_until", "acknowledged_by_user_id", "acknowledged_at", "resolved_at",
}


@pytest.mark.asyncio
async def test_b5b01_1_lifecycle_update_targets_only_the_five_lifecycle_columns() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(list(_ORIGINAL_ALERT_ROW))
    repo = _repo_with_fake_sheets(ws)

    await repo.update_alert_lifecycle(
        "ALT-U1",
        alert_status=AlertStatus.ACKNOWLEDGED,
        muted_until=None,
        acknowledged_by_user_id="USR-9",
        acknowledged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        resolved_at=None,
    )

    # exactly one targeted write, spanning only alert_status..resolved_at
    # (H2:L2 in ALERT_SHEET's declared column order) — never a full
    # A2:M2 row rewrite.
    assert ws.update_calls == 1
    assert ws.update_ranges == ["H2:L2"]


@pytest.mark.asyncio
async def test_b5b01_2_non_lifecycle_columns_are_byte_identical_after_update() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(list(_ORIGINAL_ALERT_ROW))
    repo = _repo_with_fake_sheets(ws)

    await repo.update_alert_lifecycle(
        "ALT-U1",
        alert_status=AlertStatus.RESOLVED,
        muted_until=None,
        acknowledged_by_user_id="USR-9",
        acknowledged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        resolved_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )

    header = list(schemas.ALERT_SHEET.required_headers)
    for index, column in enumerate(header):
        if column in _LIFECYCLE_COLUMNS:
            continue
        assert ws.rows[0][index] == _ORIGINAL_ALERT_ROW[index], f"{column} was rewritten"


@pytest.mark.asyncio
async def test_b5b01_3_leading_zero_source_id_unchanged_after_lifecycle_mutation() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(list(_ORIGINAL_ALERT_ROW))
    repo = _repo_with_fake_sheets(ws)

    updated = await repo.update_alert_lifecycle(
        "ALT-U1",
        alert_status=AlertStatus.ACKNOWLEDGED,
        muted_until=None,
        acknowledged_by_user_id="USR-1",
        acknowledged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        resolved_at=None,
    )
    assert updated.source_id == "000009"

    refetched = await repo.get_alert("ALT-U1")
    assert refetched is not None
    assert refetched.source_id == "000009"
    assert refetched.source_id != 9  # type: ignore[comparison-overlap]


@pytest.mark.asyncio
async def test_b5b01_4_message_th_unchanged_after_lifecycle_mutation() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(list(_ORIGINAL_ALERT_ROW))
    repo = _repo_with_fake_sheets(ws)

    updated = await repo.update_alert_lifecycle(
        "ALT-U1",
        alert_status=AlertStatus.MUTED,
        muted_until=_future(),
        acknowledged_by_user_id=None,
        acknowledged_at=None,
        resolved_at=None,
    )
    assert updated.message_th == "original message"


@pytest.mark.asyncio
async def test_b5b01_5_created_at_unchanged_after_lifecycle_mutation() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(list(_ORIGINAL_ALERT_ROW))
    repo = _repo_with_fake_sheets(ws)

    updated = await repo.update_alert_lifecycle(
        "ALT-U1",
        alert_status=AlertStatus.RESOLVED,
        muted_until=None,
        acknowledged_by_user_id=None,
        acknowledged_at=None,
        resolved_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    assert updated.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_b5b01_6_identity_and_source_fields_unchanged_after_lifecycle_mutation() -> None:
    ws = _ws(schemas.ALERT_SHEET)
    ws.append_row(list(_ORIGINAL_ALERT_ROW))
    repo = _repo_with_fake_sheets(ws)

    updated = await repo.update_alert_lifecycle(
        "ALT-U1",
        alert_status=AlertStatus.ACKNOWLEDGED,
        muted_until=None,
        acknowledged_by_user_id="USR-2",
        acknowledged_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        resolved_at=None,
    )
    assert updated.alert_id == "ALT-U1"
    assert updated.vehicle_id == "VEH-1"
    assert updated.alert_type == "PM_DUE"
    assert updated.source_type == "PM_WORK_ORDER"
    assert updated.source_id == "000009"
    assert updated.severity == AlertSeverity.CRITICAL


@pytest.mark.asyncio
async def test_b5b01_7_targeted_update_works_with_rearranged_header_order() -> None:
    # Mapping is by header NAME, never fixed position — the live sheet's
    # physical column order need not match ALERT_SHEET.required_headers.
    scrambled_header = (
        "alert_id", "message_th", "vehicle_id", "alert_status", "alert_type",
        "muted_until", "source_type", "acknowledged_by_user_id", "source_id",
        "acknowledged_at", "severity", "resolved_at", "created_at",
    )
    assert set(scrambled_header) == set(schemas.ALERT_SHEET.required_headers)
    ws = FakeWorksheet(schemas.ALERT_SHEET.tab_name, scrambled_header)
    # Numeric-looking source_id ("000009") under a reordered header — the
    # B5B review fix to `GoogleSheetsClient._numericise_ignore_columns`
    # resolves text-protection column positions from the LIVE header
    # (never `schema.required_headers`'s declared order), so this must
    # survive unchanged with no workaround.
    scrambled_row = [
        "ALT-U2", "original message", "VEH-1", "ACTIVE", "PM_DUE",
        "", "PM_WORK_ORDER", "", "000009", "", "CRITICAL", "",
        "2026-01-01T00:00:00+00:00",
    ]
    ws.append_row(scrambled_row)
    repo = _repo_with_fake_sheets(ws)

    updated = await repo.update_alert_lifecycle(
        "ALT-U2",
        alert_status=AlertStatus.ACKNOWLEDGED,
        muted_until=None,
        acknowledged_by_user_id="USR-3",
        acknowledged_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        resolved_at=None,
    )
    assert updated.alert_status == AlertStatus.ACKNOWLEDGED
    assert updated.acknowledged_by_user_id == "USR-3"
    # non-lifecycle fields survived the reorder untouched
    assert updated.message_th == "original message"
    assert updated.source_id == "000009"
    assert updated.source_id != 9  # type: ignore[comparison-overlap]
    assert updated.severity == AlertSeverity.CRITICAL
    assert updated.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)

    refetched = await repo.get_alert("ALT-U2")
    assert refetched is not None
    assert refetched.source_id == "000009"

    # None of the written ranges touched message_th's column, proving the
    # write is scoped by resolved header position, not a fixed offset.
    message_th_col = scrambled_header.index("message_th") + 1
    for range_name in ws.update_ranges:
        start_col, _, end_col = _parse_single_row_range(range_name)
        assert message_th_col not in range(start_col, end_col + 1)


# ---------------------------------------------------------------------------
# B5B-02 REVIEW FIX — blank/None source identity canonicalization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b5b02_8_blank_source_strings_canonicalize_to_none_on_create() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    created = await service.ensure_condition_alert(
        alert_id="ALT-CANON-1",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="",
        source_id="",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert created.source_type is None
    assert created.source_id is None


@pytest.mark.asyncio
async def test_b5b02_9_repeating_with_none_reuses_the_blank_created_alert() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    first = await service.ensure_condition_alert(
        alert_id="ALT-CANON-2",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="",
        source_id="",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    second = await service.ensure_condition_alert(
        alert_id="ALT-CANON-2-IGNORED",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type=None,
        source_id=None,
        severity=None,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert second.alert_id == first.alert_id
    all_matches = await repo.list_alerts_by_identity(VEHICLE_ID, "PM_DUE", None, None)
    assert len(all_matches) == 1


@pytest.mark.asyncio
async def test_b5b02_10_reverse_direction_none_then_blank_also_dedupes() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    first = await service.ensure_condition_alert(
        alert_id="ALT-CANON-3",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type=None,
        source_id=None,
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    second = await service.ensure_condition_alert(
        alert_id="ALT-CANON-3-IGNORED",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="",
        source_id="",
        severity=None,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert second.alert_id == first.alert_id


@pytest.mark.asyncio
async def test_b5b02_11_whitespace_only_source_canonicalizes_to_none() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    created = await service.ensure_condition_alert(
        alert_id="ALT-CANON-4",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="   ",
        source_id="\t",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert created.source_type is None
    assert created.source_id is None


@pytest.mark.asyncio
async def test_b5b02_12_nonblank_source_values_remain_exact() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    created = await service.ensure_condition_alert(
        alert_id="ALT-CANON-5",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="  PM_WORK_ORDER  ",
        source_id="WO-1",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    # non-blank values are preserved EXACTLY — never trimmed
    assert created.source_type == "  PM_WORK_ORDER  "
    assert created.source_id == "WO-1"


@pytest.mark.asyncio
async def test_b5b02_13_source_id_leading_zero_preserved_through_canonicalization() -> None:
    repo = MockRepository()
    service = AlertService(repo)
    created = await service.ensure_condition_alert(
        alert_id="ALT-CANON-6",
        vehicle_id=VEHICLE_ID,
        alert_type="PM_DUE",
        source_type="COMPONENT",
        source_id="000009",
        severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_th=None,
    )
    assert created.source_id == "000009"


@pytest.mark.asyncio
async def test_b5b02_14_mock_and_sheets_repositories_behave_consistently_for_canonical_missing_source() -> None:
    # MockRepository, through AlertService
    mock_repo = MockRepository()
    mock_service = AlertService(mock_repo)
    mock_first = await mock_service.ensure_condition_alert(
        alert_id="ALT-CONSIST-M1", vehicle_id=VEHICLE_ID, alert_type="PM_DUE",
        source_type="", source_id="", severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), message_th=None,
    )
    mock_second = await mock_service.ensure_condition_alert(
        alert_id="ALT-CONSIST-M2", vehicle_id=VEHICLE_ID, alert_type="PM_DUE",
        source_type=None, source_id=None, severity=None,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc), message_th=None,
    )
    assert mock_second.alert_id == mock_first.alert_id

    # GoogleSheetsRepository, through the SAME AlertService logic — proves
    # both repositories dedupe identically once the canonicalization
    # boundary is applied by the service.
    vehicle_ws = _ws(schemas.VEHICLE_SHEET)
    vehicle_ws.append_row(
        ["VEH-SHEET-1", "MC-1", "MDL-1", "", "READY", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"]
    )
    alert_ws = _ws(schemas.ALERT_SHEET)
    sheets_repo = _repo_with_fake_sheets(vehicle_ws, alert_ws)
    sheets_service = AlertService(sheets_repo)

    sheets_first = await sheets_service.ensure_condition_alert(
        alert_id="ALT-CONSIST-S1", vehicle_id="VEH-SHEET-1", alert_type="PM_DUE",
        source_type="", source_id="", severity=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), message_th=None,
    )
    sheets_second = await sheets_service.ensure_condition_alert(
        alert_id="ALT-CONSIST-S2", vehicle_id="VEH-SHEET-1", alert_type="PM_DUE",
        source_type=None, source_id=None, severity=None,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc), message_th=None,
    )
    assert sheets_second.alert_id == sheets_first.alert_id
    assert alert_ws.append_row_calls == 1  # only the first call actually created a row


# ===========================================================================
# R7 Whole-Phase Mock/TEST (Owner gate 2026-11-17, policy R1 §5): the explicit TEST
# evaluation, source-driven create / resolve, and TEST ACK / MUTE with the Mock-only
# audit log and replay repair. Positive paths use REAL audited Access Management
# grants (the AM seed's synthetic employees); no effective context is injected.
# ===========================================================================

import uuid as _uuid  # noqa: E402

from app.domain import alert_service as r7  # noqa: E402

R7_API = "/api/v1"
R7_VEHICLE = "VEH-1048"  # TEST-scoped (server reference), model MODEL-0003, seeded due part
R7_PART_KEY = "PART_INSTANCE:PINST-TEST-R7-0001:LTR-TEST-R7-0001:PLC-TEST-R7-0001:REPLACE"


@pytest.fixture
def r7_env(monkeypatch):
    for name, value in (("ACCESS_MANAGEMENT_MODE", "true"), ("DEV_AUTH_MODE", "true"), ("APP_ENV", "development"),
                        ("DATA_REPOSITORY", "mock")):
        monkeypatch.setenv(name, value)


def _am():
    from tests import test_access_management as am

    return am


async def _r7_store(grants: dict[str, dict[str, bool]] | None = None, store=None):
    am = _am()
    store = store or MockRepository(access_management_seed=True)
    for user, changes in (grants or {}).items():
        response = await am.grant(store, am.MGR, am.employee(user), changes)
        assert response.status_code == 200, response.text
    return store


def _ev_caps():
    return {"can_view": True, "can_run_test_alert_evaluation": True}


def _act_caps():
    return {"can_view": True, "can_act_on_test_alert": True}


async def _evaluate(store, user, vehicle_id: str | None = R7_VEHICLE, request_id: str = "auto"):
    am = _am()
    body = {} if vehicle_id is None else {"vehicle_id": vehicle_id}
    return await am.http("POST", f"{R7_API}/alerts/test-evaluations", store, user, json=body, request_id=request_id)


def _open(store, alert_type: str | None = None):
    return [a for a in store._alerts if a.alert_status in (AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED,
                                                              AlertStatus.MUTED)
            and (alert_type is None or a.alert_type == alert_type)]


def _outcome(body: dict, alert_type: str, vehicle_id: str = R7_VEHICLE) -> dict:
    (row,) = [o for o in body["outcomes"] if o["alert_type"] == alert_type and o["vehicle_id"] == vehicle_id]
    return row


@pytest.mark.asyncio
async def test_r7_u24_u25_real_grant_evaluation_creates_the_seeded_part_alert_once(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.CLERK: _ev_caps()})
    assert "can_run_test_alert_evaluation" in await am.caps(store, am.CLERK)
    assert "can_run_test_alert_evaluation" not in await am.caps(store, am.MGR)  # never automatic
    first = await _evaluate(store, am.CLERK)
    assert first.status_code == 200, first.text
    part = _outcome(first.json(), "PART_LIFETIME_DUE")
    assert (part["setting"], part["source"], part["created"], part["reused"]) == ("CONFIGURED", "COMPLETE", 1, 0)
    (alert,) = _open(store)
    assert (alert.alert_type, alert.source_type, alert.source_id, alert.vehicle_id) == (
        "PART_LIFETIME_DUE", "PART_LIFETIME_DUE_KEY", R7_PART_KEY, R7_VEHICLE)
    assert alert.severity == AlertSeverity.WARNING and alert.alert_id.startswith("ALT-") and len(alert.alert_id) == 36
    assert "TEST_PROPOSED" in (alert.message_th or "")
    pm = _outcome(first.json(), "PM_DUE")  # PM Master dormant in the app: never complete, nothing created
    assert (pm["source"], pm["created"]) == ("INCOMPLETE", 0) and pm["source_reason"] == "PM_STATE:MASTER_NOT_ACTIVE"
    second = await _evaluate(store, am.CLERK)
    part2 = _outcome(second.json(), "PART_LIFETIME_DUE")
    assert (part2["created"], part2["reused"]) == (0, 1)
    assert [a.alert_id for a in _open(store)] == [alert.alert_id]
    evaluations = [e for e in store._alert_action_events if e["kind"] == "EVALUATION"]
    assert len(evaluations) == 2 and evaluations[0]["actor_user_id"] == am.CLERK


class _FakeParts:
    """A fake R6 read model returning a scripted status for the one seeded key (unit level)."""

    def __init__(self, statuses):
        self.statuses = list(statuses)

    async def asset_summary(self, asset_type, asset_id):
        status = self.statuses.pop(0)
        if status == "RAISE":
            raise RuntimeError("source down")
        if status == "ABSENT":
            return {"instances": [], "positions": []}
        return {"instances": [{"target_type": "PART_INSTANCE", "target_id": "PINST-TEST-R7-0001",
                               "rules": [{"due_key": R7_PART_KEY, "status": status, "due_action": "REPLACE",
                                          "policy_state": "TEST_PROPOSED"}], "hosted_positions": []}],
                "positions": []}


def _ctx(caps: set[str]):
    from app.context import RequestContext

    return RequestContext(request_id="r7", user_id="USR-TEST-AM-CLERK", roles=("TECHNICIAN",), is_dev_auth=True,
                          capabilities=frozenset(caps), personnel_id="PER-TEST-AM-CLERK", access=object())


def _unit_service(store, parts=None, pm=None):
    from app.config import get_settings

    get_settings.cache_clear()
    return r7.R7AlertService(store, get_settings(), pm or _NoPm(), parts or _FakeParts([]))


class _NoPm:
    async def read_vehicle_pm_due(self, context, vehicle_id):
        raise RuntimeError("PM not used in this test")


_EVAL = {"can_view", "can_run_test_alert_evaluation"}


@pytest.mark.asyncio
async def test_r7_u26_u29_resolve_only_on_verified_not_due_or_complete_absence_then_recur(r7_env) -> None:
    store = MockRepository(access_management_seed=True)
    parts = _FakeParts(["DUE", "UNKNOWN", "RAISE", "NOT_DUE", "DUE", "ABSENT", "DUE"])
    service = _unit_service(store, parts=parts)
    first = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert _outcome(first, "PART_LIFETIME_DUE")["created"] == 1
    (original,) = _open(store, "PART_LIFETIME_DUE")
    unknown = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))  # UNKNOWN: no change
    assert _outcome(unknown, "PART_LIFETIME_DUE")["unknown"] == 1 and _open(store, "PART_LIFETIME_DUE") == [original]
    failed = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))  # read error: incomplete, no resolve
    assert _outcome(failed, "PART_LIFETIME_DUE")["source"] == "INCOMPLETE"
    assert _open(store, "PART_LIFETIME_DUE") == [original]
    not_due = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))  # verified NOT_DUE: resolve
    assert _outcome(not_due, "PART_LIFETIME_DUE")["resolved"] == 1 and _open(store, "PART_LIFETIME_DUE") == []
    recurred = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))  # recurrence: a NEW row
    (second,) = _open(store, "PART_LIFETIME_DUE")
    assert second.alert_id != original.alert_id and _outcome(recurred, "PART_LIFETIME_DUE")["created"] == 1
    resolved_original = await store.get_alert(original.alert_id)
    assert resolved_original.alert_status == AlertStatus.RESOLVED  # RESOLVED is terminal, never reopened
    absent = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))  # complete + absent: resolve
    assert _outcome(absent, "PART_LIFETIME_DUE")["resolved"] == 1 and _open(store, "PART_LIFETIME_DUE") == []


@pytest.mark.asyncio
async def test_r7_u27_pm_due_with_a_test_read_model_creates_resolves_and_ignores_unknown(r7_env) -> None:
    """Unit level only (exception E-1): a scripted TEST PM read model of the REAL
    VehiclePmDue / PmDueSet types. No live PM alert is claimed."""
    from app.domain.pm_service import PmDuePlan, PmDueSet, VehiclePmDue

    def vehicle(status: str, state: str = "AVAILABLE") -> VehiclePmDue:
        plan = PmDuePlan("PLAN-T", "RESOLVED", 1, "VAR", "x")
        pm_set = PmDueSet("PLAN-T", 1, "VAR|ENGINE|S1", "VAR", "ENGINE", "S1", "ENGINE_HOUR", 250.0, "HOUR",
                          "CRANE_ENGINE", "ENG-1", status, "x", None, None, None, None, None, None, None)
        return VehiclePmDue(R7_VEHICLE, "M-1", "MODEL-0003", state, "x", (), (plan,), (pm_set,))

    class ScriptedPm:
        def __init__(self, rows):
            self.rows = list(rows)

        async def read_vehicle_pm_due(self, context, vehicle_id):
            return self.rows.pop(0)

    store = MockRepository(access_management_seed=True)
    store._alert_settings[:] = [s for s in store._alert_settings if s.alert_type == "PM_DUE"]
    pm = ScriptedPm([vehicle("DUE"), vehicle("UNKNOWN"), vehicle("NOT_DUE")])
    service = _unit_service(store, pm=pm)
    first = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert _outcome(first, "PM_DUE")["created"] == 1
    (alert,) = _open(store, "PM_DUE")
    assert (alert.source_type, alert.source_id) == ("PM_DUE_SET", "PLAN-T|VAR|ENGINE|S1")
    unknown = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert _outcome(unknown, "PM_DUE")["unknown"] == 1 and _open(store, "PM_DUE") == [alert]
    resolved = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert _outcome(resolved, "PM_DUE")["resolved"] == 1 and _open(store, "PM_DUE") == []


@pytest.mark.asyncio
async def test_r7_u28_master_not_active_never_resolves_an_open_pm_alert(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.CLERK: _ev_caps()})
    store._alerts.append(Alert(alert_id="ALT-PRE-PM", vehicle_id=R7_VEHICLE, alert_type="PM_DUE",
                               source_type="PM_DUE_SET", source_id="PLAN-X|A|B|C", severity=AlertSeverity.WARNING,
                               created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), alert_status=AlertStatus.ACTIVE))
    response = await _evaluate(store, am.CLERK)
    pm = _outcome(response.json(), "PM_DUE")
    assert pm["source"] == "INCOMPLETE" and pm["resolved"] == 0
    assert (await store.get_alert("ALT-PRE-PM")).alert_status == AlertStatus.ACTIVE  # incomplete -> no resolve


@pytest.mark.asyncio
async def test_r7_u30_certificate_expired_alert_resolves_only_on_a_verified_active_successor(r7_env) -> None:
    """EXPIRED (read-only report predicate) creates the alert; alert_lead_days is never a
    trigger. Owner decision D3 (VERIFIED_ACTIVE_SUCCESSOR): the existing, protected renewal
    rule still refuses to renew an EXPIRED certificate (unchanged), so the real path is a NEW
    certificate created through the real gated route. Only a newer, valid ACTIVE certificate
    of the same vehicle and EXACT type resolves it; a different type or a merely expired
    second certificate does not. Old rows and their files are never changed."""
    am = _am()
    store = await _r7_store({am.CLERK: {**_ev_caps(), "can_manage_test_document_master": True}})

    async def create(type_code: str, expiry: str, name: str = "ทดสอบ", **extra):
        response = await am.http("POST", f"{R7_API}/vehicles/{R7_VEHICLE}/certificates", store, am.CLERK, json={
            "certificate_type_code": type_code, "certificate_type_name_th": name, "expiry_date": expiry,
            "certificate_status": "ACTIVE", **extra})
        assert response.status_code == 200, response.text
        return response.json()

    expired = await create("R7-EXP", "2020-01-01", "ทดสอบหมดอายุ", issue_date="2019-01-01")
    await create("R7-NEAR", (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat(), alert_lead_days=365)
    first = await _evaluate(store, am.CLERK)
    assert _outcome(first.json(), "CERTIFICATE_EXPIRED")["created"] == 1  # only the EXPIRED one
    (alert,) = _open(store, "CERTIFICATE_EXPIRED")
    assert alert.source_id == expired["certificate_id"] and alert.source_type == "VEHICLE_CERTIFICATE"
    refused = await am.http("POST", f"{R7_API}/certificates/{alert.source_id}/renew", store, am.CLERK,
                            json={"expiry_date": "2100-01-01"})
    assert refused.json()["error"]["code"] == "VEHICLE_CERTIFICATE_NOT_ACTIVE"  # existing rule, unchanged

    # A merely expired second certificate of the same type: never a successor (it alerts itself).
    second_expired = await create("R7-EXP", "2021-06-01", issue_date="2020-06-01")
    run = _outcome((await _evaluate(store, am.CLERK)).json(), "CERTIFICATE_EXPIRED")
    assert run["resolved"] == 0
    assert {"source_id": expired["certificate_id"], "reason": "SUCCESSOR_NOT_VALID_ACTIVE"} in run["not_resolved"]
    assert alert.alert_id in [a.alert_id for a in _open(store, "CERTIFICATE_EXPIRED")]
    # A valid ACTIVE certificate of a DIFFERENT type: not a successor.
    await create("R7-OTHER", "2100-01-01")
    run = _outcome((await _evaluate(store, am.CLERK)).json(), "CERTIFICATE_EXPIRED")
    assert run["resolved"] == 0 and len(_open(store, "CERTIFICATE_EXPIRED")) == 2

    certificates_before = [c.model_dump() for c in store._vehicle_certificates[R7_VEHICLE]]
    attachments_before = {k: a.model_dump() for k, a in store._attachments.items()}
    fresh = await create("R7-EXP", "2100-01-01", "ฉบับใหม่", issue_date=datetime.now(timezone.utc).date().isoformat())
    run = _outcome((await _evaluate(store, am.CLERK)).json(), "CERTIFICATE_EXPIRED")
    assert run["resolved"] == 2 and run["not_resolved"] == []  # both expired R7-EXP rows close on the successor
    assert _open(store, "CERTIFICATE_EXPIRED") == []
    after = [c.model_dump() for c in store._vehicle_certificates[R7_VEHICLE]]
    assert after[:len(certificates_before)] == certificates_before  # history untouched, nothing linked
    assert after[-1]["certificate_id"] == fresh["certificate_id"]
    assert {k: a.model_dump() for k, a in store._attachments.items()} == attachments_before  # files untouched
    again = _outcome((await _evaluate(store, am.CLERK)).json(), "CERTIFICATE_EXPIRED")
    assert (again["created"], again["resolved"]) == (0, 0)  # resolved stays terminal, no re-creation
    assert second_expired["certificate_id"] != fresh["certificate_id"]


def _cert(certificate_id: str, *, type_code: str | None = "R7-T", status: str | None = "ACTIVE",
          expiry: str | None = "2100-01-01", issue: str | None = None, vehicle_id: str = R7_VEHICLE,
          replaced_by: str | None = None):
    from datetime import date as _date

    from app.domain.vehicle_certificate import CertificateStatus, VehicleCertificate

    return VehicleCertificate(
        certificate_id=certificate_id, vehicle_id=vehicle_id, certificate_type_code=type_code,
        certificate_type_name_th="t", expiry_date=_date.fromisoformat(expiry) if expiry else None,
        issue_date=_date.fromisoformat(issue) if issue else None,
        certificate_status=CertificateStatus(status) if status else None, replaced_by_certificate_id=replaced_by,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


_OLD = dict(status="ACTIVE", expiry="2020-01-01", issue="2019-01-01")


@pytest.mark.parametrize(("rows", "reason"), [
    ([_cert("OLD", **_OLD)], None),  # nothing newer at all: stays DUE, no limitation to report
    ([_cert("OLD", **_OLD), _cert("NEW", type_code="R7-t")], None),  # exact type only (case matters)
    ([_cert("OLD", **_OLD), _cert("NEW", expiry="2021-01-01")], "SUCCESSOR_NOT_VALID_ACTIVE"),
    ([_cert("OLD", **_OLD), _cert("NEW", status="EXPIRED", expiry="2100-01-01")], "SUCCESSOR_NOT_VALID_ACTIVE"),
    ([_cert("OLD", **_OLD), _cert("NEW", status="REPLACED")], "SUCCESSOR_NOT_VALID_ACTIVE"),
    ([_cert("OLD", **_OLD), _cert("NEW"), _cert("ODD", status=None)], "SUCCESSOR_EVIDENCE_INCOMPLETE"),
    ([_cert("OLD", **_OLD), _cert("NEW", expiry=None)], "SUCCESSOR_EVIDENCE_INCOMPLETE"),
    ([_cert("OLD", status="EXPIRED", expiry=None), _cert("NEW")], "SUCCESSOR_EVIDENCE_INCOMPLETE"),
    ([_cert("OLD", **_OLD), _cert("NEW", issue="2018-01-01")], "SUCCESSOR_CHRONOLOGY_UNPROVEN"),
    ([_cert("OLD", **_OLD), _cert("NEW", issue="2099-01-01")], "SUCCESSOR_CHRONOLOGY_UNPROVEN"),  # not yet in effect
    ([_cert("OLD", **_OLD), _cert("NEW-1"), _cert("NEW-2")], "SUCCESSOR_AMBIGUOUS"),
    ([_cert("OLD", replaced_by="NEW-X", **_OLD), _cert("NEW")], "SUCCESSOR_AMBIGUOUS"),
    ([_cert("OLD", type_code=" ", **{k: v for k, v in _OLD.items()}), _cert("NEW", type_code=" ")],
     "SUCCESSOR_TYPE_UNKNOWN"),
    ([_cert("OLD", type_code=None, **_OLD), _cert("NEW", type_code=None)], "SUCCESSOR_TYPE_UNKNOWN"),
])
@pytest.mark.asyncio
async def test_r7_d3_unprovable_successors_never_resolve_and_are_reported(r7_env, rows, reason) -> None:
    store = MockRepository(access_management_seed=True)
    store._alert_settings[:] = [s for s in store._alert_settings if s.alert_type == "CERTIFICATE_EXPIRED"]
    store._vehicle_certificates[R7_VEHICLE] = list(rows)
    store._alerts.append(Alert(alert_id="ALT-OLD-CERT", vehicle_id=R7_VEHICLE, alert_type="CERTIFICATE_EXPIRED",
                               source_type="VEHICLE_CERTIFICATE", source_id="OLD", severity=AlertSeverity.WARNING,
                               created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), alert_status=AlertStatus.ACTIVE))
    snapshot = [c.model_dump() for c in store._vehicle_certificates[R7_VEHICLE]]
    result = await _unit_service(store).evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    outcome = _outcome(result, "CERTIFICATE_EXPIRED")
    assert (await store.get_alert("ALT-OLD-CERT")).alert_status == AlertStatus.ACTIVE  # NOT_RESOLVED
    old_entries = [e for e in outcome["not_resolved"] if e["source_id"] == "OLD"]
    assert old_entries == ([] if reason is None else [{"source_id": "OLD", "reason": reason}])
    assert [c.model_dump() for c in store._vehicle_certificates[R7_VEHICLE]] == snapshot  # no write, no link


@pytest.mark.asyncio
async def test_r7_d3_verified_successor_resolves_and_a_read_failure_or_replaced_alone_never_does(r7_env) -> None:
    store = MockRepository(access_management_seed=True)
    store._alert_settings[:] = [s for s in store._alert_settings if s.alert_type == "CERTIFICATE_EXPIRED"]

    def open_alert(alert_id: str, source_id: str) -> None:
        store._alerts.append(Alert(alert_id=alert_id, vehicle_id=R7_VEHICLE, alert_type="CERTIFICATE_EXPIRED",
                                   source_type="VEHICLE_CERTIFICATE", source_id=source_id,
                                   severity=AlertSeverity.WARNING, alert_status=AlertStatus.ACTIVE,
                                   created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))

    service = _unit_service(store)
    # REPLACED alone (successor not valid): UNKNOWN — no create, no resolve.
    store._vehicle_certificates[R7_VEHICLE] = [_cert("OLD", status="REPLACED", expiry="2020-01-01",
                                                     replaced_by="NEW"),
                                               _cert("NEW", status="ACTIVE", expiry="2021-01-01")]
    open_alert("ALT-R", "OLD")
    run = _outcome(await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4())), "CERTIFICATE_EXPIRED")
    assert run["unknown"] == 1 and (await store.get_alert("ALT-R")).alert_status == AlertStatus.ACTIVE
    # The source read fails: incomplete, nothing resolved even though a successor might exist.
    store._vehicle_certificates[R7_VEHICLE] = [_cert("OLD", **_OLD), _cert("NEW")]
    original = store.list_vehicle_certificates_for_vehicle

    async def broken(vehicle_id):
        raise RuntimeError("certificate source down")

    store.list_vehicle_certificates_for_vehicle = broken
    open_alert("ALT-E", "OLD")
    run = _outcome(await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4())), "CERTIFICATE_EXPIRED")
    assert run["source"] == "INCOMPLETE" and run["resolved"] == 0
    assert (await store.get_alert("ALT-E")).alert_status == AlertStatus.ACTIVE
    # Verified: same vehicle, exact type, valid ACTIVE, newer, consistent link.
    store.list_vehicle_certificates_for_vehicle = original
    store._vehicle_certificates[R7_VEHICLE] = [_cert("OLD", replaced_by="NEW", **_OLD),
                                               _cert("NEW", issue="2019-06-01")]
    run = _outcome(await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4())), "CERTIFICATE_EXPIRED")
    # ALT-R and ALT-E share OLD: D25 never guesses (conflict). The one resolution is the alert the
    # first step raised for the then-expired "NEW" row (its own source is now valid).
    assert run["resolved"] == 1 and run["conflicts"] == 1
    assert {(await store.get_alert(i)).alert_status for i in ("ALT-R", "ALT-E")} == {AlertStatus.ACTIVE}
    store._alerts[:] = [a for a in store._alerts if a.alert_id != "ALT-R"]
    run = _outcome(await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4())), "CERTIFICATE_EXPIRED")
    assert run["resolved"] == 1 and (await store.get_alert("ALT-E")).alert_status == AlertStatus.RESOLVED


def _pm_vehicle(status: str | None, state: str = "AVAILABLE", plan_state: str = "RESOLVED"):
    """A scripted TEST PM read model of the REAL VehiclePmDue / PmDueSet types (no formula)."""
    from app.domain.pm_service import PmDuePlan, PmDueSet, VehiclePmDue

    plan = PmDuePlan("PLAN-T", plan_state, 1, "VAR", "x")
    sets = () if status is None else (PmDueSet(
        "PLAN-T", 1, "VAR|ENGINE|S1", "VAR", "ENGINE", "S1", "ENGINE_HOUR", 250.0, "HOUR", "CRANE_ENGINE", "ENG-1",
        status, "x", None, None, None, None, None, None, None),)
    return VehiclePmDue(R7_VEHICLE, "M-1", "MODEL-0003", state, "x", (), (plan,), sets)


class _ScriptedPm:
    def __init__(self, rows):
        self.rows = list(rows)

    async def read_vehicle_pm_due(self, context, vehicle_id):
        row = self.rows.pop(0)
        if row == "RAISE":
            raise RuntimeError("PM source down")
        return row


@pytest.mark.parametrize(("pm_row", "expected"), [
    (_pm_vehicle(None, state="MASTER_NOT_ACTIVE"), "SOURCE_INCOMPLETE"),  # inactive / dormant PM Master
    (_pm_vehicle("UNKNOWN"), "SOURCE_INCOMPLETE"),  # missing evidence: an UNKNOWN set is never a zero
    (_pm_vehicle("NOT_DUE", plan_state="UNRESOLVED"), "SOURCE_INCOMPLETE"),  # a plan not resolved
    ("RAISE", "SOURCE_INCOMPLETE"),  # source-read error
    (_pm_vehicle("NOT_DUE"), "EVALUATED_NONE"),  # successful, complete enumeration, nothing due
    (_pm_vehicle(None, plan_state="NO_APPLICABLE_SET"), "EVALUATED_NONE"),  # complete: no applicable set
    (_pm_vehicle("DUE"), "ALERTS"),
])
@pytest.mark.asyncio
async def test_r7_c2_provenance_is_a_verified_zero_only_after_a_complete_source(r7_env, pm_row, expected) -> None:
    store = MockRepository(access_management_seed=True)
    store._alert_settings[:] = [s for s in store._alert_settings if s.alert_type == "PM_DUE"]
    service = _unit_service(store, pm=_ScriptedPm([pm_row]))
    await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    snapshot = ([a.model_dump() for a in store._alerts], list(store._alert_action_events),
                [x.model_dump() for x in store._alert_settings])
    provenance = await service.provenance(R7_VEHICLE)
    assert provenance["PM_DUE"] == expected
    assert provenance["PART_LIFETIME_DUE"] == "NOT_CONFIGURED"  # setting precedence kept
    assert ([a.model_dump() for a in store._alerts], list(store._alert_action_events),
            [x.model_dump() for x in store._alert_settings]) == snapshot  # the GET path is read-only


@pytest.mark.asyncio
async def test_r7_c2_open_alerts_stay_visible_with_an_incomplete_source_and_settings_take_precedence(r7_env) -> None:
    store = MockRepository(access_management_seed=True)
    store._alert_settings[:] = [s for s in store._alert_settings if s.alert_type == "PM_DUE"]
    service = _unit_service(store, pm=_ScriptedPm([_pm_vehicle("DUE"), "RAISE", _pm_vehicle("UNKNOWN"),
                                                   _pm_vehicle("NOT_DUE")]))
    assert (await service.provenance(R7_VEHICLE))["PM_DUE"] == "NOT_EVALUATED"
    await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert (await service.provenance(R7_VEHICLE))["PM_DUE"] == "ALERTS"
    (alert,) = _open(store, "PM_DUE")
    await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))  # read error: alert kept, not verified
    assert (await service.provenance(R7_VEHICLE))["PM_DUE"] == "ALERTS_SOURCE_INCOMPLETE"
    await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))  # UNKNOWN: alert kept, not verified
    assert (await service.provenance(R7_VEHICLE))["PM_DUE"] == "ALERTS_SOURCE_INCOMPLETE"
    assert _open(store, "PM_DUE") == [alert]  # the correction never suppresses a valid alert
    await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))  # verified NOT_DUE
    assert (await service.provenance(R7_VEHICLE))["PM_DUE"] == "EVALUATED_NONE" and _open(store, "PM_DUE") == []
    # Settings: a conflict / no setting is shown as such (precedence), never as a zero.
    from app.repositories.mock import seed_data

    rows = [r for r in seed_data.seed_r7_alert_settings() if r.alert_type == "PM_DUE"]
    store._alert_settings.extend([rows[0].model_copy(update={"alert_setting_id": "ASET-DUP"})])
    await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert (await service.provenance(R7_VEHICLE))["PM_DUE"] == "SETTING_CONFLICT"
    store._alert_settings.clear()
    await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert (await service.provenance(R7_VEHICLE))["PM_DUE"] == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_r7_c2_identity_conflicts_and_id_collisions_are_not_a_verified_zero(r7_env, monkeypatch) -> None:
    store = MockRepository(access_management_seed=True)
    store._alert_settings[:] = [s for s in store._alert_settings if s.alert_type == "PART_LIFETIME_DUE"]
    monkeypatch.setattr(r7, "new_alert_id", lambda: "ALT-FIXED")
    store._alerts.append(Alert(alert_id="ALT-FIXED", vehicle_id="VEH-OTHER", alert_type="X", source_type="Y",
                               source_id="Z", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                               alert_status=AlertStatus.RESOLVED))
    service = _unit_service(store, parts=_FakeParts(["DUE"]))
    result = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert _outcome(result, "PART_LIFETIME_DUE")["collisions"] == 1 and _open(store, "PART_LIFETIME_DUE") == []
    assert (await service.provenance(R7_VEHICLE))["PART_LIFETIME_DUE"] == "SOURCE_INCOMPLETE"


# ---------------------------------------------------------------------------
# IR-C7 (Owner-approved 2026-11-17): resolve-on-absence is FAIL-CLOSED. An open alert whose
# source identity is merely absent is resolved ONLY when the read is complete AND every
# observation is proven (no UNKNOWN) AND no identity conflict / id collision compromised the
# run; certificates never resolve by absence (D3). A verified NOT_DUE of the SAME identity
# still resolves that identity. Every assertion checks the stored alert record.
# ---------------------------------------------------------------------------


class _RulesParts:
    """Scripted R6 read model: each call returns the next list of (due_key, status); "RAISE" fails."""

    def __init__(self, scripts):
        self.scripts = list(scripts)

    async def asset_summary(self, asset_type, asset_id):
        rules = self.scripts.pop(0)
        if rules == "RAISE":
            raise RuntimeError("part source down")
        return {"instances": [{"target_type": "PART_INSTANCE", "target_id": "PINST-C7",
                               "rules": [{"due_key": k, "status": st, "due_action": "REPLACE",
                                          "policy_state": "TEST_PROPOSED"} for k, st in rules],
                               "hosted_positions": []}], "positions": []}


def _c7_store(alert_type: str):
    store = MockRepository(access_management_seed=True)
    store._alert_settings[:] = [s for s in store._alert_settings if s.alert_type == alert_type]
    return store


async def _status(store, source_id: str):
    rows = [a for a in store._alerts if a.source_id == source_id]
    assert len(rows) == 1, rows
    return rows[0].alert_status


async def _c7_run(service, store, alert_type="PART_LIFETIME_DUE"):
    result = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    return _outcome(result, alert_type)


@pytest.mark.asyncio
async def test_r7_c7_part_absent_alert_stays_open_while_another_identity_is_unknown(r7_env) -> None:
    store = _c7_store("PART_LIFETIME_DUE")
    service = _unit_service(store, parts=_RulesParts([[("KEY-A", "DUE")], [("KEY-B", "UNKNOWN")]]))
    await _c7_run(service, store)
    assert await _status(store, "KEY-A") == AlertStatus.ACTIVE
    run = await _c7_run(service, store)
    assert await _status(store, "KEY-A") == AlertStatus.ACTIVE  # NOT resolved by absence
    assert run["resolved"] == 0 and run["unknown"] == 1
    assert run["source"] == "COMPLETE_WITH_UNKNOWN"
    assert run["absence_resolution"] == "WITHHELD:UNKNOWN_OBSERVATION"
    snapshot = [a.model_dump() for a in store._alerts]
    assert (await service.provenance(R7_VEHICLE))["PART_LIFETIME_DUE"] == "ALERTS_SOURCE_INCOMPLETE"
    assert [a.model_dump() for a in store._alerts] == snapshot  # provenance GET writes nothing


@pytest.mark.asyncio
async def test_r7_c7_pm_absent_alert_stays_open_while_another_set_is_unknown(r7_env) -> None:
    """PM pattern with a scripted read model of the REAL VehiclePmDue / PmDueSet types (E-1)."""
    from app.domain.pm_service import PmDuePlan, PmDueSet, VehiclePmDue

    def row(*sets):
        plan = PmDuePlan("PLAN-T", "RESOLVED", 1, "VAR", "x")
        built = tuple(PmDueSet("PLAN-T", 1, key, "VAR", "ENGINE", key, "ENGINE_HOUR", 250.0, "HOUR", "CRANE_ENGINE",
                               "ENG-1", status, "x", None, None, None, None, None, None, None) for key, status in sets)
        return VehiclePmDue(R7_VEHICLE, "M-1", "MODEL-0003", "AVAILABLE", "x", (), (plan,), built)

    store = _c7_store("PM_DUE")
    service = _unit_service(store, pm=_ScriptedPm([row(("SET-A", "DUE")), row(("SET-B", "UNKNOWN")),
                                                  row(("SET-B", "NOT_DUE"))]))
    await _c7_run(service, store, "PM_DUE")
    run = await _c7_run(service, store, "PM_DUE")
    assert await _status(store, "PLAN-T|SET-A") == AlertStatus.ACTIVE
    assert run["absence_resolution"] == "WITHHELD:UNKNOWN_OBSERVATION" and run["resolved"] == 0
    run = await _c7_run(service, store, "PM_DUE")  # complete and fully proven: absence may resolve
    assert run["absence_resolution"] == "APPLIED" and run["resolved"] == 1
    assert await _status(store, "PLAN-T|SET-A") == AlertStatus.RESOLVED


@pytest.mark.asyncio
async def test_r7_c7_certificate_alert_never_resolves_because_its_row_is_missing(r7_env) -> None:
    """D3 + C7: a vanished certificate row is not proof — with or without UNKNOWN rows."""
    store = _c7_store("CERTIFICATE_EXPIRED")
    service = _unit_service(store)
    store._vehicle_certificates[R7_VEHICLE] = [_cert("OLD-A", **_OLD)]
    await _c7_run(service, store, "CERTIFICATE_EXPIRED")
    assert await _status(store, "OLD-A") == AlertStatus.ACTIVE
    store._vehicle_certificates[R7_VEHICLE] = [_cert("ODD-B", status=None)]  # A missing, B UNKNOWN
    run = await _c7_run(service, store, "CERTIFICATE_EXPIRED")
    assert await _status(store, "OLD-A") == AlertStatus.ACTIVE and run["resolved"] == 0
    store._vehicle_certificates[R7_VEHICLE] = []  # complete and empty: still not proof (D3)
    run = await _c7_run(service, store, "CERTIFICATE_EXPIRED")
    assert await _status(store, "OLD-A") == AlertStatus.ACTIVE and run["resolved"] == 0
    assert run["absence_resolution"] == "WITHHELD:CERTIFICATE_ABSENCE_IS_NOT_PROOF"


@pytest.mark.asyncio
async def test_r7_c7_complete_not_due_and_complete_empty_enumeration_still_resolve(r7_env) -> None:
    store = _c7_store("PART_LIFETIME_DUE")
    service = _unit_service(store, parts=_RulesParts([[("KEY-A", "DUE"), ("KEY-C", "DUE")],
                                                      [("KEY-A", "NOT_DUE"), ("KEY-B", "NOT_DUE")], []]))
    await _c7_run(service, store)
    run = await _c7_run(service, store)  # A: same-identity NOT_DUE; C: absent, every observation proven
    assert (run["resolved"], run["absence_resolution"], run["source"]) == (2, "APPLIED", "COMPLETE")
    assert await _status(store, "KEY-A") == AlertStatus.RESOLVED
    assert await _status(store, "KEY-C") == AlertStatus.RESOLVED
    store2 = _c7_store("PART_LIFETIME_DUE")
    service2 = _unit_service(store2, parts=_RulesParts([[("KEY-A", "DUE")], []]))
    await _c7_run(service2, store2)
    run = await _c7_run(service2, store2)  # complete, empty enumeration
    assert (run["resolved"], run["absence_resolution"]) == (1, "APPLIED")
    assert await _status(store2, "KEY-A") == AlertStatus.RESOLVED
    assert (await service2.provenance(R7_VEHICLE))["PART_LIFETIME_DUE"] == "EVALUATED_NONE"


@pytest.mark.asyncio
async def test_r7_c7_read_error_never_resolves_by_absence(r7_env) -> None:
    store = _c7_store("PART_LIFETIME_DUE")
    service = _unit_service(store, parts=_RulesParts([[("KEY-A", "DUE")], "RAISE"]))
    await _c7_run(service, store)
    run = await _c7_run(service, store)
    assert (run["source"], run["resolved"], run["absence_resolution"]) == (
        "INCOMPLETE", 0, "WITHHELD:SOURCE_INCOMPLETE")
    assert await _status(store, "KEY-A") == AlertStatus.ACTIVE


@pytest.mark.asyncio
async def test_r7_c7_mixed_due_unknown_conflicts_and_collisions_fail_closed(r7_env, monkeypatch) -> None:
    # Mixed DUE / UNKNOWN with A absent: the new DUE is raised, A stays open.
    store = _c7_store("PART_LIFETIME_DUE")
    service = _unit_service(store, parts=_RulesParts([[("KEY-A", "DUE")], [("KEY-D", "DUE"), ("KEY-U", "UNKNOWN")]]))
    await _c7_run(service, store)
    run = await _c7_run(service, store)
    assert run["created"] == 1 and await _status(store, "KEY-D") == AlertStatus.ACTIVE
    assert await _status(store, "KEY-A") == AlertStatus.ACTIVE
    assert run["absence_resolution"] == "WITHHELD:UNKNOWN_OBSERVATION"
    # An identity conflict (two open rows for X) compromises the run: A (absent) stays open.
    store = _c7_store("PART_LIFETIME_DUE")
    for i in (1, 2):
        store._alerts.append(Alert(alert_id=f"ALT-X-{i}", vehicle_id=R7_VEHICLE, alert_type="PART_LIFETIME_DUE",
                                   source_type="PART_LIFETIME_DUE_KEY", source_id="KEY-X",
                                   severity=AlertSeverity.WARNING, alert_status=AlertStatus.ACTIVE,
                                   created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    store._alerts.append(Alert(alert_id="ALT-A", vehicle_id=R7_VEHICLE, alert_type="PART_LIFETIME_DUE",
                               source_type="PART_LIFETIME_DUE_KEY", source_id="KEY-A", severity=AlertSeverity.WARNING,
                               alert_status=AlertStatus.ACTIVE, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    service = _unit_service(store, parts=_RulesParts([[("KEY-X", "DUE")]]))
    run = await _c7_run(service, store)
    assert run["conflicts"] == 1 and run["absence_resolution"] == "WITHHELD:IDENTITY_CONFLICT"
    assert await _status(store, "KEY-A") == AlertStatus.ACTIVE
    # An id collision on a DUE item compromises the run: A (absent) stays open.
    store = _c7_store("PART_LIFETIME_DUE")
    store._alerts.append(Alert(alert_id="ALT-A", vehicle_id=R7_VEHICLE, alert_type="PART_LIFETIME_DUE",
                               source_type="PART_LIFETIME_DUE_KEY", source_id="KEY-A", severity=AlertSeverity.WARNING,
                               alert_status=AlertStatus.ACTIVE, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    store._alerts.append(Alert(alert_id="ALT-FIXED", vehicle_id="VEH-OTHER", alert_type="X", source_type="Y",
                               source_id="Z", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                               alert_status=AlertStatus.RESOLVED))
    monkeypatch.setattr(r7, "new_alert_id", lambda: "ALT-FIXED")
    service = _unit_service(store, parts=_RulesParts([[("KEY-N", "DUE")]]))
    run = await _c7_run(service, store)
    assert run["collisions"] == 1 and run["absence_resolution"] == "WITHHELD:ID_COLLISION"
    assert await _status(store, "KEY-A") == AlertStatus.ACTIVE


@pytest.mark.asyncio
async def test_r7_c7_exact_identity_not_due_resolves_even_with_unknown_elsewhere_but_not_when_ambiguous(
        r7_env) -> None:
    store = _c7_store("PART_LIFETIME_DUE")
    service = _unit_service(store, parts=_RulesParts([[("KEY-A", "DUE"), ("KEY-E", "DUE")],
                                                      [("KEY-A", "NOT_DUE"), ("KEY-B", "UNKNOWN"),
                                                       ("KEY-E", "NOT_DUE"), ("KEY-E", "DUE")]]))
    await _c7_run(service, store)
    run = await _c7_run(service, store)
    assert await _status(store, "KEY-A") == AlertStatus.RESOLVED  # its own verified NOT_DUE
    # KEY-E is observed both NOT_DUE and DUE in one read: contradictory evidence -> no change.
    assert await _status(store, "KEY-E") == AlertStatus.ACTIVE
    assert run["resolved"] == 1 and run["unknown"] == 2 and run["created"] == 0 and run["reused"] == 0


@pytest.mark.asyncio
async def test_r7_u31_settings_gate_not_configured_conflict_and_zero_setting_writes(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.CLERK: _ev_caps()})
    store._alert_settings.clear()  # zero usable GLOBAL rows
    none = await _evaluate(store, am.CLERK)
    assert none.json()["settings"]["PART_LIFETIME_DUE"] == "NOT_CONFIGURED" and _open(store) == []
    from app.repositories.mock import seed_data

    rows = seed_data.seed_r7_alert_settings()
    store._alert_settings.extend(rows + [rows[1].model_copy(update={"alert_setting_id": "ASET-DUP"})])
    snapshot = [s.model_dump() for s in store._alert_settings]
    conflict = await _evaluate(store, am.CLERK)
    assert conflict.json()["settings"]["PART_LIFETIME_DUE"] == "SETTING_CONFLICT" and _open(store) == []
    assert [s.model_dump() for s in store._alert_settings] == snapshot  # D26: zero writes


@pytest.mark.asyncio
async def test_r7_u32_u33_open_identity_conflict_and_id_collision_fail_honestly(r7_env, monkeypatch) -> None:
    store = MockRepository(access_management_seed=True)
    two = [Alert(alert_id=f"ALT-DUP-{i}", vehicle_id=R7_VEHICLE, alert_type="PART_LIFETIME_DUE",
                 source_type="PART_LIFETIME_DUE_KEY", source_id=R7_PART_KEY, severity=AlertSeverity.WARNING,
                 created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), alert_status=AlertStatus.ACTIVE) for i in (1, 2)]
    store._alerts.extend(two)
    service = _unit_service(store, parts=_FakeParts(["DUE", "NOT_DUE"]))
    conflict = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert _outcome(conflict, "PART_LIFETIME_DUE")["conflicts"] == 1
    not_due = await service.evaluate(_ctx(_EVAL), R7_VEHICLE, str(_uuid.uuid4()))
    assert _outcome(not_due, "PART_LIFETIME_DUE")["conflicts"] == 1  # never guesses which row to resolve
    assert len(_open(store)) == 2
    clean = MockRepository(access_management_seed=True)
    clean._alerts.append(Alert(alert_id="ALT-TAKEN", vehicle_id=R7_VEHICLE, alert_type="OTHER",
                               created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), alert_status=AlertStatus.RESOLVED))
    monkeypatch.setattr(r7, "new_alert_id", lambda: "ALT-TAKEN")
    collided = await _unit_service(clean, parts=_FakeParts(["DUE"])).evaluate(_ctx(_EVAL), R7_VEHICLE,
                                                                                str(_uuid.uuid4()))
    assert _outcome(collided, "PART_LIFETIME_DUE")["collisions"] == 1 and _open(clean) == []


@pytest.mark.asyncio
async def test_r7_u34_u35_scope_and_authority_refusals_before_any_read(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.CLERK: _ev_caps(), am.DRV1: {"can_view": True}})
    real = await _evaluate(store, am.CLERK, vehicle_id="VEH-1046")
    assert real.status_code == 403 and real.json()["error"]["code"] == "DOCUMENT_PARENT_SCOPE_UNPROVEN"
    for user, expected in ((am.DRV1, "ALERT_ACTION_NOT_AUTHORIZED"), ("USR-UNKNOWN", "ACCESS_ACTOR_NOT_VERIFIED"),
                           (am.MGR, "ALERT_ACTION_NOT_AUTHORIZED")):
        response = await _evaluate(store, user)
        assert (response.status_code, response.json()["error"]["code"]) == (403, expected), user
    no_rid = await _evaluate(store, am.CLERK, request_id=None)
    assert no_rid.status_code == 422  # a client X-Request-Id is required
    assert _open(store) == [] and [e for e in store._alert_action_events] == []
    all_vehicles = await _evaluate(store, am.CLERK, vehicle_id=None)
    assert all_vehicles.json()["vehicle_ids"] == [R7_VEHICLE]  # only TEST-scoped vehicles with a record


@pytest.mark.asyncio
async def test_r7_u34_an_equipment_hosted_due_part_never_alerts_a_vehicle_and_equipment_is_not_evaluable(
        r7_env) -> None:
    """C5 / U-34: the seeded DUE part, moved onto equipment EQP-0002 (and then held in stock),
    is no longer in the vehicle's asset summary: no vehicle alert is created for it, an
    equipment id is not an evaluable target, and the all-TEST-vehicles run lists vehicles only."""
    from dataclasses import replace as _replace
    from types import MappingProxyType

    from app.domain.asset import AssetType
    from app.domain.part_instance import InstallationSegmentStatus

    am = _am()
    store = await _r7_store({am.CLERK: _ev_caps()})
    now = datetime.now(timezone.utc)
    state = store._part_state
    old_seg = state.segments["PINST-TEST-R7-0001"][0]
    closed = old_seg.model_copy(update={"status": InstallationSegmentStatus.CLOSED, "removed_at": now,
                                        "removed_effective_at": now})
    on_equipment = old_seg.model_copy(update={"segment_id": "SEG-TEST-R7-EQP", "asset_type": AssetType.EQUIPMENT,
                                              "asset_id": "EQP-0002", "installed_at": now,
                                              "installed_effective_at": now})
    store._part_state = _replace(state, segments=MappingProxyType({**state.segments,
                                                                   "PINST-TEST-R7-0001": (closed, on_equipment)}))
    run = await _evaluate(store, am.CLERK)
    assert run.status_code == 200, run.text
    part = _outcome(run.json(), "PART_LIFETIME_DUE")
    assert (part["source"], part["created"]) == ("COMPLETE", 0) and _open(store, "PART_LIFETIME_DUE") == []
    equipment = await _evaluate(store, am.CLERK, vehicle_id="EQP-0002")
    assert equipment.status_code in (403, 404) and _open(store) == []
    everyone = await _evaluate(store, am.CLERK, vehicle_id=None)
    assert everyone.json()["vehicle_ids"] == [R7_VEHICLE]
    assert all(o["vehicle_id"] == R7_VEHICLE for o in everyone.json()["outcomes"]) and _open(store) == []
    # A STOCK part (removed, installed nowhere) is not in any vehicle summary either.
    store._part_state = _replace(state, segments=MappingProxyType({**state.segments, "PINST-TEST-R7-0001": (closed,)}))
    stock = _outcome((await _evaluate(store, am.CLERK)).json(), "PART_LIFETIME_DUE")
    assert (stock["source"], stock["created"]) == ("COMPLETE", 0) and _open(store) == []


@pytest.mark.asyncio
async def test_r7_u35_explicit_non_mock_and_real_context_guards_on_evaluation_and_actions(
        r7_env, monkeypatch) -> None:
    """C5 / U-35: through HTTP with real grants, a non-Mock repository answers 501 and a REAL
    server context is refused, for the evaluation AND both actions, with zero writes. AM
    cannot be configured with a non-Mock repository (settings validator), so the settings
    are overridden only to prove this defence in depth."""
    from app.config import DataRepositoryMode as Mode, RegistryDataContext, get_settings as real_settings
    from app.dependencies import get_repository, get_settings_dependency, reset_dependency_cache
    from app.main import create_app

    am = _am()
    store = await _r7_store({am.CLERK: {**_ev_caps(), "can_act_on_test_alert": True}})
    await _seed_open_alert(store)
    snapshot = ([a.model_dump() for a in store._alerts], list(store._alert_action_events))

    async def call(path: str, body: dict, *, settings_override=None, real_context=False):
        if real_context:
            monkeypatch.setattr(Settings, "registry_context_effective", property(lambda self: "REAL"))
        real_settings.cache_clear()
        reset_dependency_cache()
        app = create_app()
        app.dependency_overrides[get_repository] = lambda: store
        if settings_override is not None:
            app.dependency_overrides[get_settings_dependency] = lambda: settings_override
        headers = {"X-Dev-Role": "TECHNICIAN", "X-Dev-User-Id": am.CLERK, "X-Request-Id": str(_uuid.uuid4())}
        try:
            from httpx import ASGITransport

            async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                                   base_url="http://testserver") as client:
                response = await client.post(path, headers=headers, json=body)
        finally:
            reset_dependency_cache()
            real_settings.cache_clear()
        return response.status_code, response.json()["error"]["code"]

    calls = [(f"{R7_API}/alerts/test-evaluations", {"vehicle_id": R7_VEHICLE}),
             (f"{R7_API}/alerts/ALT-ACT-1/acknowledge", {}),
             (f"{R7_API}/alerts/ALT-ACT-1/mute", {"muted_until": _future_iso(), "reason_th": "x"})]
    sheets = real_settings().model_copy(update={"data_repository": Mode.GOOGLE_SHEETS,
                                                "registry_data_context": RegistryDataContext.TEST,
                                                "registry_test_batch_id": "MOCK-7O2B-SYNTHETIC"})
    for path, body in calls:
        assert await call(path, body, settings_override=sheets) == (501, "FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE")
    for path, body in calls:  # REAL server context: the TEST employee no longer resolves
        assert await call(path, body, real_context=True) == (403, "ACCESS_ACTOR_NOT_VERIFIED"), path
    assert ([a.model_dump() for a in store._alerts], list(store._alert_action_events)) == snapshot  # zero writes


async def _seed_open_alert(store, alert_id="ALT-ACT-1", vehicle_id=R7_VEHICLE, status=AlertStatus.ACTIVE, **extra):
    alert = Alert(alert_id=alert_id, vehicle_id=vehicle_id, alert_type="PART_LIFETIME_DUE",
                  source_type="PART_LIFETIME_DUE_KEY", source_id=R7_PART_KEY, severity=AlertSeverity.WARNING,
                  created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), alert_status=status, **extra)
    store._alerts.append(alert)
    return alert


async def _act(store, user, alert_id, action, body=None, request_id="auto"):
    return await _am().http("POST", f"{R7_API}/alerts/{alert_id}/{action}", store, user, json=body or {},
                            request_id=request_id)


def _future_iso(days=7):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.mark.asyncio
async def test_r7_u37_acknowledge_keeps_the_first_actor_and_records_the_audit(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.DRV1: _act_caps(), am.CLERK: _act_caps()})
    await _seed_open_alert(store)
    first = await _act(store, am.DRV1, "ALT-ACT-1", "acknowledge", {"reason_th": "รับทราบ"})
    assert first.status_code == 200, first.text
    assert first.json()["alert"]["alert_status"] == "ACKNOWLEDGED" and first.json()["outcome"] == "APPLIED"
    second = await _act(store, am.CLERK, "ALT-ACT-1", "acknowledge")
    assert second.status_code == 200 and second.json()["outcome"] == "NOOP_ALREADY_ACKNOWLEDGED"
    assert (await store.get_alert("ALT-ACT-1")).acknowledged_by_user_id == am.DRV1  # first actor kept
    kinds = [(e["kind"], e["actor_user_id"], e["outcome"]) for e in store._alert_action_events]
    assert kinds == [("INTENT", am.DRV1, ""), ("COMMIT", am.DRV1, "APPLIED"),
                     ("INTENT", am.CLERK, ""), ("COMMIT", am.CLERK, "NOOP_ALREADY_ACKNOWLEDGED")]
    assert store._alert_action_events[1]["reason"] == "รับทราบ"


@pytest.mark.asyncio
async def test_r7_u38_mute_needs_a_reason_and_a_strictly_future_tz_aware_time(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.DRV1: _act_caps()})
    await _seed_open_alert(store)
    until = _future_iso()
    for body, code in (({"muted_until": until}, 422),  # missing reason (schema)
                       ({"muted_until": "2020-01-01T00:00:00+00:00", "reason_th": "x"}, 422),
                       ({"muted_until": "2099-01-01T00:00:00", "reason_th": "x"}, 422)):
        response = await _act(store, am.DRV1, "ALT-ACT-1", "mute", body)
        assert response.status_code == code, (body, response.text)
    ok = await _act(store, am.DRV1, "ALT-ACT-1", "mute", {"muted_until": until, "reason_th": "งานซ่อมอยู่ระหว่างทำ"})
    assert ok.status_code == 200 and ok.json()["alert"]["alert_status"] == "MUTED"
    other = await _act(store, am.DRV1, "ALT-ACT-1", "mute", {"muted_until": _future_iso(9), "reason_th": "x"})
    assert other.status_code == 422 and other.json()["error"]["code"] == "ALERT_MUTE_CONFLICTING_MUTED_UNTIL"
    to_ack = await _act(store, am.DRV1, "ALT-ACT-1", "acknowledge")
    assert to_ack.status_code == 422 and to_ack.json()["error"]["code"] == "ALERT_ACKNOWLEDGE_INVALID_TRANSITION"


@pytest.mark.asyncio
async def test_r7_u39_replay_returns_the_recorded_outcome_and_a_changed_body_is_409(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.DRV1: _act_caps()})
    await _seed_open_alert(store)
    rid = str(_uuid.uuid4())
    first = await _act(store, am.DRV1, "ALT-ACT-1", "acknowledge", {"reason_th": "a"}, request_id=rid)
    events = len(store._alert_action_events)
    replay = await _act(store, am.DRV1, "ALT-ACT-1", "acknowledge", {"reason_th": "a"}, request_id=rid)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["outcome"] == first.json()["outcome"] == "APPLIED"
    assert len(store._alert_action_events) == events  # nothing new written
    changed = await _act(store, am.DRV1, "ALT-ACT-1", "acknowledge", {"reason_th": "b"}, request_id=rid)
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "ALERT_ACTION_REQUEST_ID_REUSED"


class _FlakyAudit(MockRepository):
    """Fails the append of the named event kind `times` times (fault injection)."""

    def __init__(self, kind: str, times: int = 1) -> None:
        super().__init__(access_management_seed=True)
        self.fail_kind, self.fail_times = kind, times

    async def append_alert_action_event(self, event):
        if event.get("kind") == self.fail_kind and self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("injected audit failure")
        await super().append_alert_action_event(event)


@pytest.mark.asyncio
async def test_r7_u40_commit_audit_failure_is_never_success_and_replay_completes_it_once(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.DRV1: _act_caps(), am.CLERK: _act_caps()}, store=_FlakyAudit("COMMIT"))
    await _seed_open_alert(store)
    rid = str(_uuid.uuid4())
    failed = await _act(store, am.DRV1, "ALT-ACT-1", "acknowledge", request_id=rid)
    assert failed.status_code == 500 and failed.json()["error"]["code"] == "ALERT_ACTION_AUDIT_INCOMPLETE"
    assert failed.json()["error"]["details"]["state_changed"] is True
    changed = await store.get_alert("ALT-ACT-1")
    assert changed.alert_status == AlertStatus.ACKNOWLEDGED and changed.acknowledged_by_user_id == am.DRV1
    assert [e["kind"] for e in store._alert_action_events] == ["INTENT"]  # the partial-write trace
    # Another actor acknowledging in between never re-attributes the first acknowledgement.
    other = await _act(store, am.CLERK, "ALT-ACT-1", "acknowledge")
    assert other.json()["outcome"] == "NOOP_ALREADY_ACKNOWLEDGED"
    repaired = await _act(store, am.DRV1, "ALT-ACT-1", "acknowledge", request_id=rid)
    assert repaired.status_code == 200 and repaired.json()["recovered"] is True
    assert repaired.json()["outcome"] == "RECOVERED_ALREADY_APPLIED"
    again = await _act(store, am.DRV1, "ALT-ACT-1", "acknowledge", request_id=rid)
    assert again.json()["replayed"] is True and again.json()["outcome"] == "RECOVERED_ALREADY_APPLIED"
    mine = [e for e in store._alert_action_events if e["request_id"] == rid]
    assert [e["kind"] for e in mine] == ["INTENT", "COMMIT"]  # completed exactly once
    final = await store.get_alert("ALT-ACT-1")
    assert final.acknowledged_by_user_id == am.DRV1 and final.acknowledged_at == changed.acknowledged_at


@pytest.mark.asyncio
async def test_r7_u40_intent_audit_failure_changes_nothing(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.DRV1: _act_caps()}, store=_FlakyAudit("INTENT"))
    await _seed_open_alert(store)
    failed = await _act(store, am.DRV1, "ALT-ACT-1", "mute", {"muted_until": _future_iso(), "reason_th": "x"})
    assert failed.status_code == 500 and failed.json()["error"]["code"] == "ALERT_ACTION_AUDIT_UNAVAILABLE"
    assert (await store.get_alert("ALT-ACT-1")).alert_status == AlertStatus.ACTIVE
    assert store._alert_action_events == []


@pytest.mark.asyncio
async def test_r7_u40_mute_commit_failure_then_replay_records_once_without_a_second_transition(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.DRV1: _act_caps()}, store=_FlakyAudit("COMMIT"))
    await _seed_open_alert(store)
    rid, until = str(_uuid.uuid4()), _future_iso()
    body = {"muted_until": until, "reason_th": "รออะไหล่"}
    assert (await _act(store, am.DRV1, "ALT-ACT-1", "mute", body, request_id=rid)).status_code == 500
    muted = await store.get_alert("ALT-ACT-1")
    assert muted.alert_status == AlertStatus.MUTED
    repaired = await _act(store, am.DRV1, "ALT-ACT-1", "mute", body, request_id=rid)
    assert repaired.status_code == 200 and repaired.json()["outcome"] == "RECOVERED_ALREADY_APPLIED"
    assert [e["kind"] for e in store._alert_action_events if e["request_id"] == rid] == ["INTENT", "COMMIT"]
    assert (await store.get_alert("ALT-ACT-1")).muted_until == muted.muted_until


@pytest.mark.asyncio
async def test_r7_u41_expired_mute_is_derived_on_read_and_reconciled_only_by_an_action(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.DRV1: _act_caps()})
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    await _seed_open_alert(store, status=AlertStatus.MUTED, muted_until=past)
    read = await am.http("GET", f"{R7_API}/alerts/ALT-ACT-1", store, am.DRV1, request_id=None)
    assert read.status_code == 200 and read.json()["mute_expired"] is True and read.json()["alert_status"] == "MUTED"
    assert (await store.get_alert("ALT-ACT-1")).alert_status == AlertStatus.MUTED  # no write on GET
    acted = await _act(store, am.DRV1, "ALT-ACT-1", "acknowledge")
    assert acted.status_code == 200 and acted.json()["alert"]["alert_status"] == "ACKNOWLEDGED"


@pytest.mark.asyncio
async def test_r7_u42_actions_need_the_grant_and_a_test_vehicle_and_there_is_no_resolve_route(r7_env) -> None:
    am = _am()
    store = await _r7_store({am.DRV1: _act_caps(), am.CLERK: {"can_view": True}})
    await _seed_open_alert(store)
    await _seed_open_alert(store, alert_id="ALT-REAL-1", vehicle_id="VEH-1046")
    no_grant = await _act(store, am.CLERK, "ALT-ACT-1", "acknowledge")
    assert (no_grant.status_code, no_grant.json()["error"]["code"]) == (403, "ALERT_ACTION_NOT_AUTHORIZED")
    real = await _act(store, am.DRV1, "ALT-REAL-1", "acknowledge")
    assert (real.status_code, real.json()["error"]["code"]) == (403, "DOCUMENT_PARENT_SCOPE_UNPROVEN")
    resolve = await _act(store, am.DRV1, "ALT-ACT-1", "resolve")
    assert resolve.status_code in (404, 405)
    assert all(a.alert_status == AlertStatus.ACTIVE for a in store._alerts)


@pytest.mark.asyncio
async def test_r7_u35_legacy_mode_cannot_evaluate_or_act_and_writes_nothing(monkeypatch) -> None:
    """U-35: legacy development-role mode has no AM-verified employee and no role holds a
    TEST grant — evaluation, acknowledge and mute are refused (403) for every role."""
    from httpx import ASGITransport

    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    monkeypatch.setenv("ACCESS_MANAGEMENT_MODE", "false")
    monkeypatch.setenv("DEV_AUTH_MODE", "true")
    store = MockRepository()
    await _seed_open_alert(store, vehicle_id=R7_VEHICLE)
    for role in ("ADMIN", "MAINTENANCE_MANAGER", "TECHNICIAN"):
        for path, body in ((f"{R7_API}/alerts/test-evaluations", {"vehicle_id": R7_VEHICLE}),
                           (f"{R7_API}/alerts/ALT-ACT-1/acknowledge", {}),
                           (f"{R7_API}/alerts/ALT-ACT-1/mute", {"muted_until": _future_iso(), "reason_th": "x"})):
            get_settings.cache_clear()
            reset_dependency_cache()
            app = create_app()
            app.dependency_overrides[get_repository] = lambda: store
            async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                                   base_url="http://testserver") as c:
                response = await c.post(path, json=body, headers={"X-Dev-Role": role,
                                                                  "X-Request-Id": str(_uuid.uuid4())})
            assert response.status_code == 403, (role, path, response.text)
    reset_dependency_cache()
    get_settings.cache_clear()
    assert [a.alert_status for a in store._alerts] == [AlertStatus.ACTIVE] and store._alert_action_events == []
