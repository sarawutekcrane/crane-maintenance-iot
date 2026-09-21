"""Web/API Phase 6 Batch 4C — Daily Summary Reconciliation.

Proves the Batch 4C frozen contract (see
`app.domain.daily_summary_service` module docstring, restated from the
task's own frozen sections):

- pairing only within exact (vehicle_id, device_id, component_id,
  family); ENGINE never pairs with PTO, device A never pairs with device B
- D20: only TIME_SYNCED/TIME_ESTIMATED events with non-null event_time
  are used; TIME_NOT_SYNCED is excluded entirely even with a populated
  event_time; received_at never assigns summary_date
- deterministic ordering: event_time, then sequence, then received_at,
  then event_id
- state machine: OPEN-while-OPEN keeps the first open and marks the
  repeated open's date PARTIAL; CLOSE-while-CLOSED creates no duration
  and marks the close's date PARTIAL; a trailing unmatched OPEN marks its
  own date PARTIAL, never fabricating an end time
- cross-Bangkok-midnight splitting, including a full intermediate day
- D21 value/status semantics, including a legitimate zero-second interval
- full recompute on every reconcile call (delayed/out-of-order healing)
- duplicate retry heals a missing/altered-payload-immune summary
  projection using the STORED raw event, never the replay payload
- Google Sheets: one row per (summary_date, vehicle_id, component_id,
  metric_type) key, targeted update or single append, text-safe opaque
  identifiers, readiness inclusion, exact 9-header schema."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.domain.common import to_bangkok_date
from app.domain.daily_summary import DailySummary, DailySummaryDataStatus, DailySummaryMetricType
from app.domain.daily_summary_service import DailySummaryService
from app.domain.vehicle_event import TimeQuality, VehicleEvent, VehicleEventType
from app.repositories.google_sheets import GoogleSheetsRepository, schemas
from app.repositories.mock import MockRepository

from tests.test_google_sheets_real_io import FakeSpreadsheet, FakeWorksheet, _ws
from tests.test_vehicle_event_batch4a import _component_id, _create_event, _payload

_BKK = ZoneInfo("Asia/Bangkok")


def _configured_settings() -> Settings:
    return Settings(google_sheet_id="fake-sheet-id", google_application_credentials="fake.json")


def _repo_with_fake_sheets(*worksheets: FakeWorksheet) -> GoogleSheetsRepository:
    repo = GoogleSheetsRepository(_configured_settings())
    repo._client._spreadsheet = FakeSpreadsheet(list(worksheets))  # type: ignore[attr-defined]
    return repo


def _event(
    event_id: str,
    event_type: VehicleEventType,
    event_time: datetime | None,
    *,
    vehicle_id: str = "VEH-TEST",
    device_id: str = "DEV-A",
    component_id: str = "CMP-1",
    sequence: int = 1,
    received_at: datetime | None = None,
    time_quality: TimeQuality = TimeQuality.TIME_SYNCED,
) -> VehicleEvent:
    return VehicleEvent(
        event_id=event_id,
        vehicle_id=vehicle_id,
        device_id=device_id,
        component_id=component_id,
        event_type=event_type,
        event_time=event_time,
        fuel_level_value=None,
        fuel_level_unit=None,
        latitude=None,
        longitude=None,
        gps_valid=None,
        received_at=received_at or event_time or datetime(2026, 1, 1, tzinfo=timezone.utc),
        note_th=None,
        device_event_id=f"DEVEVT-{event_id}",
        sequence=sequence,
        created_offline=False,
        time_quality=time_quality,
    )


async def _reconcile(
    repo: MockRepository, vehicle_id: str, component_id: str
) -> list[DailySummary]:
    service = DailySummaryService(repo)
    await service.reconcile_vehicle_component(vehicle_id, component_id)
    return await repo.list_daily_summaries_for_vehicle(vehicle_id)


def _find(
    summaries: list[DailySummary],
    summary_date: date,
    metric_type: DailySummaryMetricType,
    component_id: str | None = None,
) -> DailySummary | None:
    return next(
        (
            s
            for s in summaries
            if s.summary_date == summary_date
            and s.metric_type == metric_type
            and (component_id is None or s.component_id == component_id)
        ),
        None,
    )


def _bkk(y, m, d, h, mi=0, s=0) -> datetime:
    return datetime(y, m, d, h, mi, s, tzinfo=_BKK)


# ---------------------------------------------------------------------------
# A. BASIC ENGINE (items 1-4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a1_engine_start_stop_same_day_complete() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0)),
            _event("EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0), sequence=2),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value == 3600.0
    assert row.data_status == DailySummaryDataStatus.COMPLETE
    assert row.unit == "s"


@pytest.mark.asyncio
async def test_a2_start_with_no_stop_partial_null() -> None:
    repo = MockRepository()
    repo._vehicle_events.append(
        _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0))
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value is None
    assert row.data_status == DailySummaryDataStatus.PARTIAL


@pytest.mark.asyncio
async def test_a3_stop_with_no_start_partial_null() -> None:
    repo = MockRepository()
    repo._vehicle_events.append(
        _event("EVT-1", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0))
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value is None
    assert row.data_status == DailySummaryDataStatus.PARTIAL


@pytest.mark.asyncio
async def test_a4_repeated_start_then_stop_first_start_wins_partial() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0), sequence=1),
            _event("EVT-2", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 30), sequence=2),
            _event("EVT-3", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0), sequence=3),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value == 3600.0  # 08:00 -> 09:00, using the FIRST start
    assert row.data_status == DailySummaryDataStatus.PARTIAL


# ---------------------------------------------------------------------------
# B. BASIC PTO (items 5-6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b5_pto_on_off_correct_duration() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.PTO_ON, _bkk(2026, 9, 10, 8, 0)),
            _event("EVT-2", VehicleEventType.PTO_OFF, _bkk(2026, 9, 10, 8, 45), sequence=2),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.PTO_RUN_DURATION)
    assert row is not None
    assert row.value == 2700.0
    assert row.data_status == DailySummaryDataStatus.COMPLETE


@pytest.mark.asyncio
async def test_b6_engine_and_pto_remain_separate_families() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0)),
            _event("EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0), sequence=2),
            _event("EVT-3", VehicleEventType.PTO_ON, _bkk(2026, 9, 10, 8, 10), sequence=3),
            _event("EVT-4", VehicleEventType.PTO_OFF, _bkk(2026, 9, 10, 8, 20), sequence=4),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    engine = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    pto = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.PTO_RUN_DURATION)
    assert engine is not None and engine.value == 3600.0
    assert pto is not None and pto.value == 600.0


# ---------------------------------------------------------------------------
# C. OUT-OF-ORDER (items 7-8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c7_c8_late_earlier_start_heals_prior_partial_to_complete() -> None:
    repo = MockRepository()
    repo._vehicle_events.append(
        _event("EVT-STOP", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0))
    )
    first_pass = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(first_pass, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value is None
    assert row.data_status == DailySummaryDataStatus.PARTIAL
    original_id = row.daily_summary_id
    original_created_at = row.created_at

    # A delayed, earlier START now arrives.
    repo._vehicle_events.append(
        _event("EVT-START", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0), sequence=1)
    )
    second_pass = await _reconcile(repo, "VEH-TEST", "CMP-1")
    healed = _find(second_pass, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert healed is not None
    assert healed.value == 3600.0
    assert healed.data_status == DailySummaryDataStatus.COMPLETE
    # Same derived row - identity/created_at preserved across recompute.
    assert healed.daily_summary_id == original_id
    assert healed.created_at == original_created_at


# ---------------------------------------------------------------------------
# D. CROSS MIDNIGHT (items 9-10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d9_interval_crossing_bangkok_midnight_splits_correctly() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 21, 23, 30)),
            _event("EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 22, 0, 30), sequence=2),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    day1 = _find(summaries, date(2026, 9, 21), DailySummaryMetricType.ENGINE_RUN_DURATION)
    day2 = _find(summaries, date(2026, 9, 22), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert day1 is not None and day1.value == 1800.0
    assert day2 is not None and day2.value == 1800.0
    assert day1.data_status == DailySummaryDataStatus.COMPLETE
    assert day2.data_status == DailySummaryDataStatus.COMPLETE


@pytest.mark.asyncio
async def test_d10_interval_spanning_full_intermediate_day() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 21, 23, 0)),
            _event("EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 23, 1, 0), sequence=2),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    day1 = _find(summaries, date(2026, 9, 21), DailySummaryMetricType.ENGINE_RUN_DURATION)
    day2 = _find(summaries, date(2026, 9, 22), DailySummaryMetricType.ENGINE_RUN_DURATION)
    day3 = _find(summaries, date(2026, 9, 23), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert day1 is not None and day1.value == 3600.0
    assert day2 is not None and day2.value == 86400.0
    assert day3 is not None and day3.value == 3600.0


# ---------------------------------------------------------------------------
# E. MULTI-DEVICE (items 11-12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e11_two_device_streams_paired_independently_then_aggregated() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-A1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0),
                device_id="DEV-A",
            ),
            _event(
                "EVT-A2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0),
                device_id="DEV-A", sequence=2,
            ),
            _event(
                "EVT-B1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 10, 0),
                device_id="DEV-B",
            ),
            _event(
                "EVT-B2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 10, 30),
                device_id="DEV-B", sequence=2,
            ),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value == 5400.0  # 3600 + 1800
    assert row.data_status == DailySummaryDataStatus.COMPLETE


@pytest.mark.asyncio
async def test_e12_device_a_start_never_pairs_with_device_b_stop() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-A1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0),
                device_id="DEV-A",
            ),
            _event(
                "EVT-B1", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0),
                device_id="DEV-B",
            ),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    # If cross-device pairing wrongly occurred this would be
    # COMPLETE/3600. Both streams instead have their own unmatched
    # anomaly and zero provable duration.
    assert row.value is None
    assert row.data_status == DailySummaryDataStatus.PARTIAL


# ---------------------------------------------------------------------------
# F. MULTI-COMPONENT (item 13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f13_different_components_never_aggregate_together() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-C1-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0),
                component_id="CMP-1",
            ),
            _event(
                "EVT-C1-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0),
                component_id="CMP-1", sequence=2,
            ),
            _event(
                "EVT-C2-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0),
                component_id="CMP-2",
            ),
            _event(
                "EVT-C2-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 8, 15),
                component_id="CMP-2", sequence=2,
            ),
        ]
    )
    summaries_c1 = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row_c1 = _find(
        summaries_c1, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION, "CMP-1"
    )
    assert row_c1 is not None
    assert row_c1.value == 3600.0
    assert row_c1.component_id == "CMP-1"

    summaries_c2 = await _reconcile(repo, "VEH-TEST", "CMP-2")
    row_c2 = _find(
        summaries_c2, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION, "CMP-2"
    )
    assert row_c2 is not None
    assert row_c2.value == 900.0
    assert row_c2.component_id == "CMP-2"


# ---------------------------------------------------------------------------
# G. TIME QUALITY - D20 (items 14-18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g14_time_synced_included() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0),
                time_quality=TimeQuality.TIME_SYNCED,
            ),
            _event(
                "EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0), sequence=2,
                time_quality=TimeQuality.TIME_SYNCED,
            ),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None and row.value == 3600.0


@pytest.mark.asyncio
async def test_g15_time_estimated_included() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0),
                time_quality=TimeQuality.TIME_ESTIMATED,
            ),
            _event(
                "EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0), sequence=2,
                time_quality=TimeQuality.TIME_ESTIMATED,
            ),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None and row.value == 3600.0


@pytest.mark.asyncio
async def test_g16_time_not_synced_null_event_time_ignored_entirely() -> None:
    repo = MockRepository()
    repo._vehicle_events.append(
        _event(
            "EVT-1", VehicleEventType.ENGINE_START, None,
            time_quality=TimeQuality.TIME_NOT_SYNCED,
            received_at=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),
        )
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    assert summaries == []


@pytest.mark.asyncio
async def test_g17_time_not_synced_with_event_time_also_ignored_entirely() -> None:
    repo = MockRepository()
    repo._vehicle_events.append(
        _event(
            "EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0),
            time_quality=TimeQuality.TIME_NOT_SYNCED,
        )
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    # Not even treated as an anomaly - fully excluded from D20.
    assert summaries == []


@pytest.mark.asyncio
async def test_g18_received_at_never_assigns_summary_date() -> None:
    """event_time lands on 2026-09-10 Bangkok; received_at is
    deliberately a different Bangkok date. The summary must land on
    event_time's date only."""
    event_time = _bkk(2026, 9, 10, 23, 0)
    received_at_far_away = _bkk(2026, 9, 15, 3, 0).astimezone(timezone.utc)
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-1", VehicleEventType.ENGINE_START, event_time,
                received_at=received_at_far_away,
            ),
            _event(
                "EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 23, 30), sequence=2,
                received_at=received_at_far_away,
            ),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    assert _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION) is not None
    assert _find(summaries, date(2026, 9, 15), DailySummaryMetricType.ENGINE_RUN_DURATION) is None


# ---------------------------------------------------------------------------
# H. D21 (items 19-21)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h19_complete_interval_plus_unmatched_later_start() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 8, 0), sequence=1),
            _event("EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0), sequence=2),
            _event("EVT-3", VehicleEventType.ENGINE_START, _bkk(2026, 9, 10, 10, 0), sequence=3),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value == 3600.0
    assert row.data_status == DailySummaryDataStatus.PARTIAL


@pytest.mark.asyncio
async def test_h20_anomaly_with_no_complete_interval() -> None:
    repo = MockRepository()
    repo._vehicle_events.append(
        _event("EVT-1", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 10, 9, 0))
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value is None
    assert row.data_status == DailySummaryDataStatus.PARTIAL


@pytest.mark.asyncio
async def test_h21_legitimate_zero_second_interval() -> None:
    same_instant = _bkk(2026, 9, 10, 8, 0)
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, same_instant, sequence=1),
            _event("EVT-2", VehicleEventType.ENGINE_STOP, same_instant, sequence=2),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value == 0.0
    assert row.data_status == DailySummaryDataStatus.COMPLETE


# ---------------------------------------------------------------------------
# I. TIE ORDER (items 22-23)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_i22_same_event_time_respects_sequence_ordering() -> None:
    """A STOP (sequence 1) and a START (sequence 2) share the exact same
    event_time. Correct order (STOP first, per sequence) means: STOP
    while CLOSED -> anomaly, then START opens and is left unmatched at
    end -> anomaly again. Wrong order (START first) would instead pair
    them into a COMPLETE zero-duration interval - a different, wrong
    result this test would catch."""
    same_instant = _bkk(2026, 9, 10, 8, 0)
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-STOP", VehicleEventType.ENGINE_STOP, same_instant, sequence=1),
            _event("EVT-START", VehicleEventType.ENGINE_START, same_instant, sequence=2),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value is None
    assert row.data_status == DailySummaryDataStatus.PARTIAL


@pytest.mark.asyncio
async def test_i23a_same_event_time_and_sequence_respects_received_at() -> None:
    same_instant = _bkk(2026, 9, 10, 8, 0)
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-STOP", VehicleEventType.ENGINE_STOP, same_instant, sequence=1,
                received_at=datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc),
            ),
            _event(
                "EVT-START", VehicleEventType.ENGINE_START, same_instant, sequence=1,
                received_at=datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value is None
    assert row.data_status == DailySummaryDataStatus.PARTIAL


@pytest.mark.asyncio
async def test_i23b_same_event_time_sequence_received_at_respects_event_id() -> None:
    same_instant = _bkk(2026, 9, 10, 8, 0)
    same_received_at = datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc)
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-0001", VehicleEventType.ENGINE_STOP, same_instant, sequence=1,
                received_at=same_received_at,
            ),
            _event(
                "EVT-0002", VehicleEventType.ENGINE_START, same_instant, sequence=1,
                received_at=same_received_at,
            ),
        ]
    )
    summaries = await _reconcile(repo, "VEH-TEST", "CMP-1")
    row = _find(summaries, date(2026, 9, 10), DailySummaryMetricType.ENGINE_RUN_DURATION)
    # EVT-0001 (STOP) sorts before EVT-0002 (START) -> STOP-while-CLOSED
    # anomaly, then START left unmatched -> anomaly. Never a paired
    # COMPLETE/0 result.
    assert row is not None
    assert row.value is None
    assert row.data_status == DailySummaryDataStatus.PARTIAL


# ---------------------------------------------------------------------------
# J. DUPLICATE / RECOVERY (items 24-26) - full ingestion integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_j24_duplicate_retry_creates_no_second_raw_event(client: AsyncClient) -> None:
    vehicle_id = "VEH-1046"
    component_id = await _component_id(client, vehicle_id)
    payload = _payload(
        vehicle_id, component_id, device_id="DEV-4C-DUP", device_event_id="E-4C-DUP-1",
        event_type="ENGINE_START",
    )
    first = await _create_event(client, payload)
    replay = await _create_event(client, payload)
    assert replay["event_id"] == first["event_id"]

    listing = await client.get(f"/api/v1/vehicles/{vehicle_id}/events")
    matching = [
        e for e in listing.json()
        if e["device_id"] == "DEV-4C-DUP" and e["device_event_id"] == "E-4C-DUP-1"
    ]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_j25_duplicate_retry_heals_missing_summary_projection(
    client: AsyncClient,
) -> None:
    from app.dependencies import get_repository

    vehicle_id = "VEH-1047"
    component_id = await _component_id(client, vehicle_id)
    repo = get_repository()

    # Simulate a prior partial failure: raw event appended directly
    # (bypassing the service), so reconciliation never ran.
    start_time = datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc)  # 08:00 Bangkok
    stored = await repo.create_vehicle_event(
        vehicle_id=vehicle_id,
        device_id="DEV-4C-HEAL",
        component_id=component_id,
        event_type=VehicleEventType.ENGINE_START,
        event_time=start_time,
        fuel_level_value=None,
        fuel_level_unit=None,
        latitude=None,
        longitude=None,
        gps_valid=None,
        note_th=None,
        device_event_id="E-4C-HEAL-1",
        sequence=1,
        created_offline=False,
        time_quality=TimeQuality.TIME_SYNCED,
    )
    daily_summaries_before = await repo.list_daily_summaries_for_vehicle(vehicle_id)
    assert daily_summaries_before == []

    # Retry through the real API with the SAME (device_id, device_event_id).
    replay = await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-4C-HEAL", device_event_id="E-4C-HEAL-1",
            event_type="ENGINE_START", event_time="2026-09-10T01:00:00+00:00",
        ),
    )
    assert replay["event_id"] == stored.event_id

    healed = await repo.list_daily_summaries_for_vehicle(vehicle_id)
    row = _find(healed, to_bangkok_date(start_time), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert row is not None
    assert row.value is None  # only a lone START exists - PARTIAL, but the row now EXISTS
    assert row.data_status == DailySummaryDataStatus.PARTIAL


@pytest.mark.asyncio
async def test_j26_altered_duplicate_retry_uses_stored_history_not_replay(
    client: AsyncClient,
) -> None:
    vehicle_id = "VEH-1048"
    component_id = await _component_id(client, vehicle_id)

    original_payload = _payload(
        vehicle_id, component_id, device_id="DEV-4C-ALTER", device_event_id="E-4C-ALTER-1",
        event_type="ENGINE_START", event_time="2026-09-10T01:00:00+00:00",  # 08:00 Bangkok
    )
    original = await _create_event(client, original_payload)

    # Replay with an altered payload (different event_type/event_time) -
    # must be ignored; the stored ENGINE_START is what reconciliation
    # (and any future STOP) will actually see.
    altered = dict(original_payload)
    altered["event_type"] = "ENGINE_STOP"
    altered["event_time"] = "2026-09-10T00:00:00+00:00"
    replay = await _create_event(client, altered)
    assert replay["event_id"] == original["event_id"]
    assert replay["event_type"] == "ENGINE_START"

    # A genuine STOP (new device_event_id) one hour later.
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-4C-ALTER", device_event_id="E-4C-ALTER-2",
            event_type="ENGINE_STOP", event_time="2026-09-10T02:00:00+00:00", sequence=2,
        ),
    )

    response = await client.get(f"/api/v1/vehicles/{vehicle_id}/daily-summaries")
    assert response.status_code == 200, response.text
    row = next(
        (
            s for s in response.json()
            if s["metric_type"] == "ENGINE_RUN_DURATION" and s["summary_date"] == "2026-09-10"
        ),
        None,
    )
    assert row is not None
    assert row["value"] == 3600.0  # 08:00 -> 09:00 Bangkok, from the STORED start
    assert row["data_status"] == "COMPLETE"


# ---------------------------------------------------------------------------
# K. REPOSITORY (items 27-34)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k27_mock_upsert_creates_then_updates_same_key() -> None:
    repo = MockRepository()
    created = await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="VEH-TEST",
        component_id="CMP-1",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=100.0,
        unit="s",
        data_status=DailySummaryDataStatus.PARTIAL,
    )
    updated = await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="VEH-TEST",
        component_id="CMP-1",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=200.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    assert updated.daily_summary_id == created.daily_summary_id
    assert updated.created_at == created.created_at
    assert updated.value == 200.0
    assert updated.data_status == DailySummaryDataStatus.COMPLETE

    all_rows = await repo.list_daily_summaries_for_vehicle("VEH-TEST")
    assert len(all_rows) == 1


@pytest.mark.asyncio
async def test_k28_sheets_append_when_no_key_exists() -> None:
    ws = _ws(schemas.DAILY_SUMMARY_SHEET)
    repo = _repo_with_fake_sheets(ws)

    created = await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="VEH-9001",
        component_id="CMP-0001",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=3600.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    assert created.daily_summary_id.startswith("DSUM-")
    assert ws.append_row_calls == 1
    assert len(ws.rows) == 1


@pytest.mark.asyncio
async def test_k29_sheets_targeted_update_when_key_exists() -> None:
    ws = _ws(schemas.DAILY_SUMMARY_SHEET)
    repo = _repo_with_fake_sheets(ws)

    await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="VEH-9001",
        component_id="CMP-0001",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=3600.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    updated = await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="VEH-9001",
        component_id="CMP-0001",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=7200.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    assert updated.value == 7200.0
    # Exactly one append (the first creation); the second call targeted
    # the existing row - never a second append / full rewrite.
    assert ws.append_row_calls == 1
    assert len(ws.rows) == 1


@pytest.mark.asyncio
async def test_k30_sheets_update_preserves_id_and_created_at() -> None:
    ws = _ws(schemas.DAILY_SUMMARY_SHEET)
    repo = _repo_with_fake_sheets(ws)

    created = await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="VEH-9001",
        component_id="CMP-0001",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=3600.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    updated = await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="VEH-9001",
        component_id="CMP-0001",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=None,
        unit="s",
        data_status=DailySummaryDataStatus.PARTIAL,
    )
    assert updated.daily_summary_id == created.daily_summary_id
    assert updated.created_at == created.created_at


@pytest.mark.asyncio
async def test_k31_sheets_update_does_not_touch_unrelated_rows() -> None:
    ws = _ws(schemas.DAILY_SUMMARY_SHEET)
    repo = _repo_with_fake_sheets(ws)

    await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="VEH-A",
        component_id="CMP-A",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=100.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 11),
        vehicle_id="VEH-B",
        component_id="CMP-B",
        metric_type=DailySummaryMetricType.PTO_RUN_DURATION,
        value=200.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="VEH-A",
        component_id="CMP-A",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=999.0,
        unit="s",
        data_status=DailySummaryDataStatus.PARTIAL,
    )
    assert len(ws.rows) == 2
    veh_b_rows = await repo.list_daily_summaries_for_vehicle("VEH-B")
    assert len(veh_b_rows) == 1
    assert veh_b_rows[0].value == 200.0  # untouched by VEH-A's second upsert


@pytest.mark.asyncio
async def test_k32_numeric_looking_ids_remain_text_safe() -> None:
    ws = _ws(schemas.DAILY_SUMMARY_SHEET)
    repo = _repo_with_fake_sheets(ws)

    await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 10),
        vehicle_id="000009",
        component_id="000001",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=100.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    rows = await repo.list_daily_summaries_for_vehicle("000009")
    assert len(rows) == 1
    assert rows[0].vehicle_id == "000009"
    assert rows[0].vehicle_id != 9  # type: ignore[comparison-overlap]
    assert rows[0].component_id == "000001"
    assert rows[0].component_id != 1  # type: ignore[comparison-overlap]

    headers = schemas.DAILY_SUMMARY_SHEET.required_headers
    raw_vehicle = ws.rows[0][headers.index("vehicle_id")]
    raw_component = ws.rows[0][headers.index("component_id")]
    assert str(raw_vehicle) == "'000009"
    assert str(raw_component) == "'000001"


def test_k33_daily_summary_sheet_is_in_core_schemas() -> None:
    assert schemas.DAILY_SUMMARY_SHEET in GoogleSheetsRepository._CORE_SCHEMAS


def test_k34_daily_summary_sheet_declares_exact_nine_headers() -> None:
    assert schemas.DAILY_SUMMARY_SHEET.required_headers == (
        "daily_summary_id",
        "summary_date",
        "vehicle_id",
        "component_id",
        "metric_type",
        "value",
        "unit",
        "data_status",
        "created_at",
    )


# ---------------------------------------------------------------------------
# L. API (items 35-36)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l35_get_daily_summaries_deterministic_ordering(client: AsyncClient) -> None:
    vehicle_id = "VEH-1046"
    component_id = await _component_id(client, vehicle_id)

    # Two different days, same component, ENGINE family.
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORD", device_event_id="E-ORD-1",
            event_type="ENGINE_START", event_time="2026-09-10T01:00:00+00:00",
        ),
    )
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORD", device_event_id="E-ORD-2",
            event_type="ENGINE_STOP", event_time="2026-09-10T02:00:00+00:00", sequence=2,
        ),
    )
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORD", device_event_id="E-ORD-3",
            event_type="ENGINE_START", event_time="2026-09-11T01:00:00+00:00", sequence=3,
        ),
    )
    await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-ORD", device_event_id="E-ORD-4",
            event_type="ENGINE_STOP", event_time="2026-09-11T02:00:00+00:00", sequence=4,
        ),
    )

    response = await client.get(f"/api/v1/vehicles/{vehicle_id}/daily-summaries")
    assert response.status_code == 200, response.text
    rows = response.json()
    engine_rows = [r for r in rows if r["metric_type"] == "ENGINE_RUN_DURATION"]
    dates = [r["summary_date"] for r in engine_rows]
    # summary_date descending.
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_l36_unknown_vehicle_daily_summaries_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vehicles/VEH-DOES-NOT-EXIST/daily-summaries")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"


# ---------------------------------------------------------------------------
# D22 REVIEW FIX — stale derived daily_summary row removal (items 1-8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d22_1_stale_cross_day_row_removed_on_replay() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 1, 23, 0), sequence=1),
            _event("EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 3, 1, 0), sequence=2),
        ]
    )
    first_pass = await _reconcile(repo, "VEH-TEST", "CMP-1")
    assert len(first_pass) == 3
    assert _find(first_pass, date(2026, 9, 2), DailySummaryMetricType.ENGINE_RUN_DURATION) is not None

    # Late offline events split the interval - Sep 2 is no longer spanned.
    repo._vehicle_events.extend(
        [
            _event("EVT-3", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 1, 23, 30), sequence=3),
            _event("EVT-4", VehicleEventType.ENGINE_START, _bkk(2026, 9, 3, 0, 30), sequence=4),
        ]
    )
    second_pass = await _reconcile(repo, "VEH-TEST", "CMP-1")
    day1 = _find(second_pass, date(2026, 9, 1), DailySummaryMetricType.ENGINE_RUN_DURATION)
    day3 = _find(second_pass, date(2026, 9, 3), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert day1 is not None and day1.value == 1800.0
    assert day3 is not None and day3.value == 1800.0
    assert _find(second_pass, date(2026, 9, 2), DailySummaryMetricType.ENGINE_RUN_DURATION) is None
    assert len(second_pass) == 2

    # Raw events all remain (append-only) - 4 total, none removed.
    assert len(repo._vehicle_events) == 4


@pytest.mark.asyncio
async def test_d22_2_delete_only_exact_component() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-A1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 1, 23, 0),
                component_id="CMP-A", sequence=1,
            ),
            _event(
                "EVT-A2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 3, 1, 0),
                component_id="CMP-A", sequence=2,
            ),
            _event(
                "EVT-B1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 1, 8, 0),
                component_id="CMP-B", sequence=1,
            ),
            _event(
                "EVT-B2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 1, 9, 0),
                component_id="CMP-B", sequence=2,
            ),
        ]
    )
    await _reconcile(repo, "VEH-TEST", "CMP-A")
    b_first = await _reconcile(repo, "VEH-TEST", "CMP-B")
    b_first_rows = [r for r in b_first if r.component_id == "CMP-B"]
    assert len(b_first_rows) == 1

    # Late events split A's interval only - A's Sep 2 becomes stale.
    repo._vehicle_events.extend(
        [
            _event(
                "EVT-A3", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 1, 23, 30),
                component_id="CMP-A", sequence=3,
            ),
            _event(
                "EVT-A4", VehicleEventType.ENGINE_START, _bkk(2026, 9, 3, 0, 30),
                component_id="CMP-A", sequence=4,
            ),
        ]
    )
    await _reconcile(repo, "VEH-TEST", "CMP-A")

    all_rows = await repo.list_daily_summaries_for_vehicle("VEH-TEST")
    b_rows = [r for r in all_rows if r.component_id == "CMP-B"]
    assert len(b_rows) == 1
    assert b_rows[0].value == 3600.0  # untouched by CMP-A's reconciliation


@pytest.mark.asyncio
async def test_d22_3_sheets_delete_never_touches_unrelated_metric_row() -> None:
    """D22 item 3: an unrelated/future metric row must survive a
    reconciliation-driven delete. `DailySummaryMetricType` deliberately
    cannot represent a hypothetical future metric (never broadened just
    for this test), so this is exercised at the raw fake-sheet level:
    `delete_daily_summary` identifies its target purely by exact
    `daily_summary_id` and therefore can never touch any other row,
    regardless of that other row's own metric_type content."""
    ws = _ws(schemas.DAILY_SUMMARY_SHEET)
    repo = _repo_with_fake_sheets(ws)

    managed = await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 2),
        vehicle_id="VEH-9001",
        component_id="CMP-0001",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=100.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    headers = schemas.DAILY_SUMMARY_SHEET.required_headers
    foreign_row = [
        "DSUM-FUTURE-1", "2026-09-02", "VEH-9001", "CMP-0001",
        "SOME_FUTURE_METRIC", "42", "s", "COMPLETE", "2026-01-01T00:00:00+00:00",
    ]
    assert len(foreign_row) == len(headers)
    ws.rows.append(foreign_row)
    assert len(ws.rows) == 2

    await repo.delete_daily_summary(managed.daily_summary_id)

    assert len(ws.rows) == 1
    remaining = ws.rows[0]
    assert remaining[headers.index("daily_summary_id")] == "DSUM-FUTURE-1"
    assert remaining[headers.index("metric_type")] == "SOME_FUTURE_METRIC"


@pytest.mark.asyncio
async def test_d22_4_empty_desired_result_deletes_all_managed_rows() -> None:
    repo = MockRepository()
    # Pre-existing managed rows with NO corresponding raw vehicle_event
    # history at all - a synthetic setup proving the "zero desired keys"
    # deletion path.
    await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 1),
        vehicle_id="VEH-TEST",
        component_id="CMP-1",
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=100.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 2),
        vehicle_id="VEH-TEST",
        component_id="CMP-1",
        metric_type=DailySummaryMetricType.PTO_RUN_DURATION,
        value=50.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )
    await DailySummaryService(repo).reconcile_vehicle_component("VEH-TEST", "CMP-1")

    remaining = await repo.list_daily_summaries_for_vehicle("VEH-TEST")
    assert remaining == []


@pytest.mark.asyncio
async def test_d22_5_sheets_multiple_stale_rows_deleted_without_index_corruption() -> None:
    event_ws = _ws(schemas.VEHICLE_EVENT_SHEET)
    summary_ws = _ws(schemas.DAILY_SUMMARY_SHEET)
    repo = _repo_with_fake_sheets(event_ws, summary_ws)
    service = DailySummaryService(repo)

    vehicle_id = "VEH-9001"
    component_id = "CMP-0001"

    async def _mk(event_type: VehicleEventType, event_time: datetime, sequence: int) -> None:
        await repo.create_vehicle_event(
            vehicle_id=vehicle_id,
            device_id="DEV-A",
            component_id=component_id,
            event_type=event_type,
            event_time=event_time,
            fuel_level_value=None,
            fuel_level_unit=None,
            latitude=None,
            longitude=None,
            gps_valid=None,
            note_th=None,
            device_event_id=f"DEVEVT-{sequence}",
            sequence=sequence,
            created_offline=False,
            time_quality=TimeQuality.TIME_SYNCED,
        )

    await _mk(VehicleEventType.ENGINE_START, _bkk(2026, 9, 1, 23, 0), 1)
    await _mk(VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 3, 1, 0), 2)
    await service.reconcile_vehicle_component(vehicle_id, component_id)
    assert len(summary_ws.rows) == 3  # Sep 1, Sep 2, Sep 3

    await _mk(VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 1, 23, 30), 3)
    await _mk(VehicleEventType.ENGINE_START, _bkk(2026, 9, 3, 0, 30), 4)
    await service.reconcile_vehicle_component(vehicle_id, component_id)

    assert len(summary_ws.rows) == 2
    rows = await repo.list_daily_summaries_for_vehicle(vehicle_id)
    day1 = _find(rows, date(2026, 9, 1), DailySummaryMetricType.ENGINE_RUN_DURATION)
    day3 = _find(rows, date(2026, 9, 3), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert day1 is not None and day1.value == 1800.0
    assert day3 is not None and day3.value == 1800.0
    assert _find(rows, date(2026, 9, 2), DailySummaryMetricType.ENGINE_RUN_DURATION) is None


@pytest.mark.asyncio
async def test_d22_6_desired_row_identity_preserved_alongside_stale_deletion() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 1, 23, 0), sequence=1),
            _event("EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 3, 1, 0), sequence=2),
        ]
    )
    first_pass = await _reconcile(repo, "VEH-TEST", "CMP-1")
    day1_before = _find(first_pass, date(2026, 9, 1), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert day1_before is not None

    repo._vehicle_events.extend(
        [
            _event("EVT-3", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 1, 23, 30), sequence=3),
            _event("EVT-4", VehicleEventType.ENGINE_START, _bkk(2026, 9, 3, 0, 30), sequence=4),
        ]
    )
    second_pass = await _reconcile(repo, "VEH-TEST", "CMP-1")
    day1_after = _find(second_pass, date(2026, 9, 1), DailySummaryMetricType.ENGINE_RUN_DURATION)
    assert day1_after is not None
    assert day1_after.daily_summary_id == day1_before.daily_summary_id
    assert day1_after.created_at == day1_before.created_at
    assert day1_after.value == 1800.0
    # Stale Sep 2 removed in the same pass that preserved Sep 1's identity.
    assert _find(second_pass, date(2026, 9, 2), DailySummaryMetricType.ENGINE_RUN_DURATION) is None


@pytest.mark.asyncio
async def test_d22_7_stale_summary_deletion_never_touches_raw_events() -> None:
    repo = MockRepository()
    repo._vehicle_events.extend(
        [
            _event("EVT-1", VehicleEventType.ENGINE_START, _bkk(2026, 9, 1, 23, 0), sequence=1),
            _event("EVT-2", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 3, 1, 0), sequence=2),
        ]
    )
    await _reconcile(repo, "VEH-TEST", "CMP-1")
    raw_before = [e.event_id for e in repo._vehicle_events]

    repo._vehicle_events.extend(
        [
            _event("EVT-3", VehicleEventType.ENGINE_STOP, _bkk(2026, 9, 1, 23, 30), sequence=3),
            _event("EVT-4", VehicleEventType.ENGINE_START, _bkk(2026, 9, 3, 0, 30), sequence=4),
        ]
    )
    await _reconcile(repo, "VEH-TEST", "CMP-1")  # deletes the stale Sep 2 summary row
    raw_after = [e.event_id for e in repo._vehicle_events]

    assert raw_after == raw_before + ["EVT-3", "EVT-4"]


@pytest.mark.asyncio
async def test_d22_8_retry_triggered_reconciliation_heals_stale_summary(
    client: AsyncClient,
) -> None:
    """Simulates a stale row left by a previous partial failure (both raw
    events already persisted, but reconciliation never ran to completion
    against the full picture), then proves a duplicate-retry POST both
    (a) returns the exact stored original event and (b) triggers the
    healing reconciliation that removes the stale summary row."""
    from app.dependencies import get_repository

    vehicle_id = "VEH-1046"
    component_id = await _component_id(client, vehicle_id)
    repo = get_repository()

    start_time = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)  # 23:00 Bangkok
    stop_time = datetime(2026, 9, 1, 16, 30, tzinfo=timezone.utc)  # 23:30 Bangkok
    stored_start = await repo.create_vehicle_event(
        vehicle_id=vehicle_id,
        device_id="DEV-D22-8",
        component_id=component_id,
        event_type=VehicleEventType.ENGINE_START,
        event_time=start_time,
        fuel_level_value=None,
        fuel_level_unit=None,
        latitude=None,
        longitude=None,
        gps_valid=None,
        note_th=None,
        device_event_id="E-D22-8-1",
        sequence=1,
        created_offline=False,
        time_quality=TimeQuality.TIME_SYNCED,
    )
    await repo.create_vehicle_event(
        vehicle_id=vehicle_id,
        device_id="DEV-D22-8",
        component_id=component_id,
        event_type=VehicleEventType.ENGINE_STOP,
        event_time=stop_time,
        fuel_level_value=None,
        fuel_level_unit=None,
        latitude=None,
        longitude=None,
        gps_valid=None,
        note_th=None,
        device_event_id="E-D22-8-2",
        sequence=2,
        created_offline=False,
        time_quality=TimeQuality.TIME_SYNCED,
    )
    # A stale managed row left by a prior run that never completed
    # reconciliation against this full raw picture.
    await repo.upsert_daily_summary(
        summary_date=date(2026, 9, 2),
        vehicle_id=vehicle_id,
        component_id=component_id,
        metric_type=DailySummaryMetricType.ENGINE_RUN_DURATION,
        value=86400.0,
        unit="s",
        data_status=DailySummaryDataStatus.COMPLETE,
    )

    replay = await _create_event(
        client,
        _payload(
            vehicle_id, component_id, device_id="DEV-D22-8", device_event_id="E-D22-8-1",
            event_type="ENGINE_START", event_time="2026-09-01T16:00:00+00:00",
        ),
    )
    assert replay["event_id"] == stored_start.event_id

    rows = await repo.list_daily_summaries_for_vehicle(vehicle_id)
    stale = [
        r for r in rows
        if r.component_id == component_id and r.summary_date == date(2026, 9, 2)
    ]
    assert stale == []
    healed = _find(rows, date(2026, 9, 1), DailySummaryMetricType.ENGINE_RUN_DURATION, component_id)
    assert healed is not None
    assert healed.value == 1800.0
    assert healed.data_status == DailySummaryDataStatus.COMPLETE
