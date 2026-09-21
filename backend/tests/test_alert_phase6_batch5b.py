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
    for action in ("acknowledge", "mute", "resolve", "reopen", "reconcile-mute-expiry"):
        response = await client.post(f"/api/v1/alerts/ALT-1/{action}", json={})
        assert response.status_code == 404, f"{action} unexpectedly routable: {response.status_code}"


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
