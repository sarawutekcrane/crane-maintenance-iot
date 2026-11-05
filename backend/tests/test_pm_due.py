"""R4 DUE-01: offline pure-function tests using invented, verified inputs.

These tests DO NOT prove real previous PM completion, true engine topology,
real meter data, E01 integration, Sheets persistence, or PostgreSQL readiness.
"""
from __future__ import annotations

from dataclasses import replace
from enum import Enum

import pytest

from app.domain.pm_due import PmDueInputs, calculate_pm_due


def engine(**overrides) -> PmDueInputs:
    values = dict(
        set_ref="SYN-VEH1|PLAN1|CARRIER|SET-A|GROUP-A",
        meter_type="ENGINE_HOUR",
        interval=600.0,
        interval_unit="HOUR",  # also accepted as 'hour'
        last_completed_meter=650.0,
        current_meter=1249.0,
        source_verified=True,
        last_completion_verified=True,
        current_meter_verified=True,
        driving_component_role="CARRIER_ENGINE",
        component_id="SYN-ENGINE-CARRIER",
        component_verified=True,
    )
    values.update(overrides)
    return PmDueInputs(**values)


def km(**overrides) -> PmDueInputs:
    values = dict(
        set_ref="SYN-VEH1|PLAN1|VEHICLE|SET-G|GROUP-G",
        meter_type="ODOMETER",
        interval=5000.0,
        interval_unit="KM",
        last_completed_meter=18200.0,
        current_meter=23199.0,
        driving_component_role="VEHICLE",
        component_id=None,
        component_verified=False,
    )
    values.update(overrides)
    return replace(engine(), **values)


@pytest.mark.parametrize("reading,status", [(1249, "NOT_DUE"), (1250, "DUE"), (1300, "DUE")])
def test_u01_hour_actual_650_plus_600(reading: float, status: str) -> None:
    result = calculate_pm_due(engine(current_meter=reading))
    assert result.status == status
    assert result.next_due == 1250.0
    assert result.is_due is (status == "DUE")
    assert result.reason is None


@pytest.mark.parametrize("reading,status", [(23199, "NOT_DUE"), (23200, "DUE")])
def test_u02_km_actual_18200_plus_5000(reading: float, status: str) -> None:
    result = calculate_pm_due(km(current_meter=reading))
    assert result.status == status
    assert result.next_due == 23200.0


def test_u03_early_and_late_use_actual_not_absolute_interval_multiple() -> None:
    assert calculate_pm_due(engine(last_completed_meter=540, current_meter=1139)).next_due == 1140
    assert calculate_pm_due(engine(last_completed_meter=780, current_meter=1380)).next_due == 1380


def test_u04_independent_sets_receive_independent_explicit_anchors() -> None:
    hour_a = calculate_pm_due(engine(last_completed_meter=650, current_meter=1200))
    group_g = calculate_pm_due(km(last_completed_meter=18200, current_meter=23200))
    hour_a_again = calculate_pm_due(engine(last_completed_meter=650, current_meter=1200))
    assert hour_a.status == "NOT_DUE"
    assert group_g.status == "DUE"
    assert hour_a == hour_a_again


@pytest.mark.parametrize("changes,reason", [
    ({"source_verified": False}, "SET_SOURCE_UNVERIFIED"),
    ({"source_verified": 1}, "SET_SOURCE_UNVERIFIED"),
    ({"set_ref": ""}, "SET_SOURCE_UNVERIFIED"),
    ({"last_completion_verified": False}, "LAST_ACTUAL_SET_COMPLETION_UNVERIFIED"),
    ({"last_completed_meter": None}, "LAST_ACTUAL_SET_COMPLETION_UNVERIFIED"),
    ({"current_meter_verified": False}, "CURRENT_METER_UNVERIFIED"),
    ({"current_meter": None}, "CURRENT_METER_UNVERIFIED"),
    ({"component_verified": False}, "PHYSICAL_ENGINE_UNVERIFIED"),
    ({"component_verified": 1}, "PHYSICAL_ENGINE_UNVERIFIED"),
    ({"component_id": None}, "PHYSICAL_ENGINE_UNVERIFIED"),
    ({"driving_component_role": None}, "PHYSICAL_ENGINE_UNVERIFIED"),
])
def test_u05_missing_verification_stays_unknown(changes: dict, reason: str) -> None:
    result = calculate_pm_due(engine(**changes))
    assert (result.status, result.next_due, result.is_due, result.reason) == (
        "UNKNOWN", None, None, reason,
    )


@pytest.mark.parametrize("trigger", ["PTO_HOUR", "CALENDAR", None, "UNRECOGNIZED"])
def test_u06_unapproved_existing_pm_meter_is_not_due(trigger: str | None) -> None:
    result = calculate_pm_due(engine(meter_type=trigger))
    assert (result.status, result.reason) == ("UNKNOWN", "PM_METER_NOT_APPROVED")


def test_u07_verified_carrier_or_crane_engine_only() -> None:
    assert calculate_pm_due(engine()).next_due == 1250
    assert calculate_pm_due(engine(driving_component_role="CRANE_ENGINE",
                                   component_id="SYN-VERIFIED-CRANE-ENGINE")).next_due == 1250
    assert calculate_pm_due(engine(driving_component_role="CRANE_ENGINE", component_verified=False)).status == "UNKNOWN"
    assert calculate_pm_due(engine(driving_component_role="PTO", component_id="SYN-PTO")).status == "UNKNOWN"


@pytest.mark.parametrize("changes,reason", [
    ({"interval": 0}, "INTERVAL_INVALID"),
    ({"interval": -50}, "INTERVAL_INVALID"),
    ({"interval": float("nan")}, "INTERVAL_INVALID"),
    ({"interval": float("inf")}, "INTERVAL_INVALID"),
    ({"interval": True}, "INTERVAL_INVALID"),
    ({"interval": 10 ** 400}, "INTERVAL_INVALID"),
    ({"interval_unit": "KM"}, "INTERVAL_UNIT_MISMATCH"),
    ({"last_completed_meter": -1}, "LAST_ACTUAL_SET_COMPLETION_UNVERIFIED"),
    ({"current_meter": float("inf")}, "CURRENT_METER_UNVERIFIED"),
    ({"current_meter": 649}, "COUNTER_DECREASE_UNRESOLVED"),
    ({"last_completed_meter": 1e308, "interval": 1e308, "current_meter": 1e308}, "NEXT_DUE_OVERFLOW"),
])
def test_u08_invalid_or_contradictory_inputs_fail_closed(changes: dict, reason: str) -> None:
    result = calculate_pm_due(engine(**changes))
    assert (result.status, result.next_due, result.reason) == ("UNKNOWN", None, reason)


def test_u09_a_genuinely_verified_zero_is_not_missing() -> None:
    decision = calculate_pm_due(engine(last_completed_meter=0, current_meter=0, interval=600))
    assert (decision.status, decision.next_due) == ("NOT_DUE", 600)
    assert calculate_pm_due(engine(last_completed_meter=0, current_meter=600)).status == "DUE"


@pytest.mark.parametrize("changes,reason", [
    ({"component_id": "SYN-CARRIER"}, "ODOMETER_MUST_BE_VEHICLE_LEVEL"),
    ({"driving_component_role": "CARRIER_ENGINE"}, "ODOMETER_MUST_BE_VEHICLE_LEVEL"),
    ({"interval_unit": "HOUR"}, "INTERVAL_UNIT_MISMATCH"),
])
def test_u10_vehicle_odometer_is_not_an_engine_meter(changes: dict, reason: str) -> None:
    result = calculate_pm_due(km(**changes))
    assert (result.status, result.reason) == ("UNKNOWN", reason)


class ExistingStrEnumLike(str, Enum):
    ENGINE_HOUR = "ENGINE_HOUR"
    CARRIER_ENGINE = "CARRIER_ENGINE"


def test_existing_str_enum_values_work_without_reimporting_pm_business_models() -> None:
    decision = calculate_pm_due(engine(
        meter_type=ExistingStrEnumLike.ENGINE_HOUR,
        driving_component_role=ExistingStrEnumLike.CARRIER_ENGINE,
    ))
    assert (decision.status, decision.next_due) == ("NOT_DUE", 1250)
