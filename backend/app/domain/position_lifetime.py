"""POSITION_LIFETIME tracking: lifetime associated with asset+position+
rule/baseline, without requiring a unique serialized physical instance
(baseline §11, §13 "POSITION LIFETIME"; OPEN_DECISIONS_REGISTER_EN.txt G03).

POSITION CODE (G03 — "Position Code Master: TBD-BLOCKING before scalable
lifetime deployment"): `position_code` is a free-text field, never an
enum, and no seed data declares any position code as company master data.
Any example value used in tests is clearly a development/example value
(see `backend/tests/test_position_lifetime.py`), never presented as an
approved position-code vocabulary, and G03 is never marked resolved by
this module.

BASELINE (baseline §13): must not be silently guessed. A
`PositionLifetimeRecord`'s `prior_usage` follows the same KNOWN/PARTIAL/
UNKNOWN discipline as `app.domain.part_instance.PriorUsage` — `UNKNOWN`
stays `UNKNOWN`.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.domain.asset import AssetType
from app.domain.part_instance import PriorUsage


class PositionLifetimeRecord(BaseModel):
    """Lifetime tracked by asset+position, with no required serialized
    `PartInstance`. `part_id`, when set, must reference a `PartMaster`
    whose `tracking_mode` is `POSITION_LIFETIME` — never an
    `INSTANCE_TRACKED` part (that concept uses `PartInstance` instead).
    `lifetime_rule_id`, when set, must reference an existing
    `app.domain.lifetime_rule.LifetimeRule` — no due/remaining value is
    computed here (G01/G02 unresolved)."""

    position_lifetime_id: str
    asset_type: AssetType
    asset_id: str
    position_code: str
    part_id: str | None = None
    lifetime_rule_id: str | None = None
    baseline_meter_snapshot_id: str | None = None
    prior_usage: PriorUsage
    started_at: datetime
    started_by: str | None = None
    note: str | None = None


__all__ = ["PositionLifetimeRecord"]
