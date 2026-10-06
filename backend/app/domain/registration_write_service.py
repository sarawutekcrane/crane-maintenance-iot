"""Phase 7 Batch 7O2b — registration writes (contract Final Rev2 §3, §4.4,
§4.6, §4.7, §8.1; Outcome Classification Addendum A.1, A.4).

HISTORY-FIRST: W1 appends a vehicle_registration_history row, W2 writes the
targeted vehicle_master cells. Every coded refusal is raised BEFORE W1
(each such code is in `registry_outcomes.ZERO_WRITE_ALLOWLIST` for its
operation); after W1 the only coded outcomes are the two write-failure codes
and success. Nothing is retried, compensated, re-read or re-appended. Route
dependencies (capability, client request id, body schema) run before this
service is called; nothing here raises HTTPException.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypeVar

from fastapi import status

from app.domain.registration import (
    CHANGE_KIND_CHANGE,
    CONSISTENCY_MISMATCH,
    DATA_CONTEXT_TEST,
    MAX_REGISTRATION_LENGTH,
    REGISTRATION_HISTORY_COLUMNS,
    latest_new_pair,
    optional_text,
    pair_is_valid,
    registration_consistency,
    registration_history_revision,
    registration_key,
    text,
    validate_registration_rows,
)
from app.domain.registry_errors import data_invalid
from app.domain.registry_write_support import (  # noqa: F401  (MOCK_TEST_BATCH_ID re-exported)
    MOCK_TEST_BATCH_ID,
    error,
    registry_read,
    require_write_context,
    vehicle_read,
)
from app.domain.request_replay import (
    OP_REGISTRATION,
    OP_REGISTRATION_RECONCILE,
    ReplayLookup,
    find_replay,
    request_fingerprint,
)
from app.domain.vehicle import Vehicle
from app.domain.vehicle_registry import (
    REGISTRATION_NO_COLUMN,
    REGISTRATION_PROVINCE_COLUMN,
    RegistryField,
    STATE_NOT_RECORDED,
    STATE_RECORDED,
    VehicleRegistry,
    parse_reference_rows,
)
from app.errors import ApiError
from app.repositories.base import (
    RegistrationMasterRead,
    RegistryTableRead,
    Repository,
    RepositoryWriteError,
)

T = TypeVar("T")

Pair = tuple[str | None, str | None]

KIND_APPLY_RECORDED = "RECONCILIATION_APPLY_RECORDED"
KIND_ACCEPT_MASTER = "RECONCILIATION_ACCEPT_MASTER"
RECONCILIATION_MODES = ("APPLY_RECORDED", "ACCEPT_MASTER")
MAX_REASON_LENGTH = 500

MASTER_WRITE_WRITTEN = "WRITTEN"
MASTER_WRITE_NOT_NEEDED = "NOT_NEEDED"

# MOCK_TEST_BATCH_ID is defined in registry_write_support (re-exported here).


def _error(code: str, message: str, http_status: int, details: dict[str, object] | None = None) -> ApiError:
    return error(code, message, http_status, details)


@dataclass(frozen=True)
class ChangeRecord:
    change_id: str
    recorded_at: str
    request_id: str


@dataclass(frozen=True)
class WriteOutcome:
    """A 200 outcome. Exactly one of: changed (with `change`), a no-op
    (`changed` False), or a replay (`replayed` True)."""

    request_id: str
    changed: bool = False
    replayed: bool = False
    change: ChangeRecord | None = None
    master_write: str | None = None
    warnings: list[str] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    master_state: str | None = None
    consistency: str | None = None
    # PATCH success only: the updated vehicle built from R1 plus the applied pair.
    vehicle: Vehicle | None = None
    registry: VehicleRegistry | None = None


def _field(value: str | None) -> RegistryField:
    return RegistryField(STATE_RECORDED, value) if value is not None else RegistryField(STATE_NOT_RECORDED)


class RegistrationWriteService:
    def __init__(
        self,
        repository: Repository,
        data_context: str | None,
        test_batch_id: str,
    ) -> None:
        self._repository = repository
        self._context = data_context
        self._batch_id = test_batch_id

    # ---------------------------------------------------------------- helpers

    def _require_write_context(self) -> str:
        """§8.1 + C7 (shared rule, `registry_write_support`)."""
        return require_write_context(self._context, self._batch_id)

    @staticmethod
    async def _vehicle_read(call: Awaitable[T]) -> T:
        return await vehicle_read(call)

    @staticmethod
    async def _registry_read(call: Awaitable[T]) -> T:
        return await registry_read(call)

    async def _read_master(self, vehicle_id: str) -> RegistrationMasterRead:
        """R1 + locate + write-column check (§3.3 steps 2-3)."""
        master = await self._vehicle_read(self._repository.read_vehicle_registration_master(vehicle_id))
        if master is None:
            raise _error("VEHICLE_NOT_FOUND", f"Vehicle '{vehicle_id}' was not found", status.HTTP_404_NOT_FOUND)
        missing = [c for c in (REGISTRATION_NO_COLUMN, REGISTRATION_PROVINCE_COLUMN) if c not in master.registry_columns]
        if missing:
            raise _error(
                "VEHICLE_MASTER_SCHEMA_INVALID",
                "vehicle_master has no column for the registration pair; nothing was changed",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                {"tab": "vehicle_master", "problem": "MISSING_HEADERS", "headers": missing},
            )
        return master

    async def _read_history(self, vehicle_id: str, context: str) -> tuple[RegistryTableRead, list[Mapping[str, object]]]:
        """R2 + validation of this vehicle's rows (§7.7) and of record ids
        across the whole tab ("duplicate record ids anywhere in a tab fail
        mutations")."""
        read = await self._registry_read(self._repository.read_vehicle_registration_history_validated())
        mine = [r for r in read.rows if text(r.get("vehicle_id")) == vehicle_id]
        issues = validate_registration_rows(mine, context)
        ids = [text(r.get("change_id")) for r in read.rows if text(r.get("change_id"))]
        if len(ids) != len(set(ids)) and "CHANGE_ID_DUPLICATE" not in issues:
            issues = {**issues, "CHANGE_ID_DUPLICATE": len(ids) - len(set(ids))}
        if issues:
            raise data_invalid("vehicle_registration_history", issues)
        return read, mine

    async def _provinces(self) -> dict[str, bool]:
        """R3: province code -> is_active. An outage or an invalid master is a
        503/500, never "not found"."""
        read = await self._registry_read(self._repository.read_province_master_validated())
        entries, issues = parse_reference_rows(
            read.rows, code_column="province_code", name_column="province_name_th"
        )
        if issues:
            raise data_invalid("province_master", issues)
        return {e.code: e.is_active for e in entries}

    @staticmethod
    def _master_pair(master: RegistrationMasterRead) -> Pair:
        return master.registry.registration_no.value, master.registry.registration_province.value

    @staticmethod
    def _duplicates(master: RegistrationMasterRead, pair: Pair) -> list[str]:
        """Vehicle ids (raw) of OTHER rows of the same R1 response holding the
        same complete pair under RK1 (§4.4 uniqueness scope). Self-exclusion
        is by row, so a blank-id row still blocks; a pair without a province
        is never compared; history is not consulted."""
        number, province = pair
        if number is None or province is None:
            return []
        key = registration_key(number)
        return [
            row.vehicle_id
            for row in master.rows
            if row.row_key != master.target_row_key
            and row.registration_no.strip()
            and row.registration_province_code == province
            and registration_key(row.registration_no) == key
        ]

    @staticmethod
    def _duplicate_error(duplicates: Sequence[str]) -> ApiError:
        return _error(
            "REGISTRATION_DUPLICATE",
            "Another vehicle already holds this registration in this province; nothing was changed",
            status.HTTP_409_CONFLICT,
            {"conflict_count": len(duplicates), "conflict_vehicle_ids": [v for v in duplicates if v.strip()]},
        )

    @staticmethod
    def _province_refusal(code: str, provinces: Mapping[str, bool], master_code: str | None) -> ApiError | None:
        """The normal assignment rule: an unknown code is refused; an inactive
        code is refused unless the master already holds it."""
        if code not in provinces:
            return _error(
                "PROVINCE_NOT_FOUND",
                f"Province code '{code}' is not in province_master; nothing was changed",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"province_code": code},
            )
        if not provinces[code] and code != master_code:
            return _error(
                "PROVINCE_INACTIVE",
                f"Province code '{code}' is inactive and cannot be newly assigned; nothing was changed",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"province_code": code},
            )
        return None

    @staticmethod
    def _replay_outcome(
        hit: ReplayLookup, request_id: str, master_pair: Pair, mine: Sequence[Mapping[str, object]]
    ) -> WriteOutcome:
        if not hit.replayed:
            raise _error(
                "REQUEST_ID_REUSED",
                "This request id was already used for a different change; nothing was changed",
                status.HTTP_409_CONFLICT,
                {"request_id": request_id},
            )
        first = hit.rows[0]
        recorded = (
            optional_text(first.get("new_registration_no")),
            optional_text(first.get("new_registration_province_code")),
        )
        return WriteOutcome(
            request_id=request_id,
            replayed=True,
            record_ids=list(hit.record_ids),
            master_state="MATCHES" if recorded == master_pair else "DIFFERS",
            consistency=registration_consistency(mine, master_pair),
        )

    def _history_row(
        self,
        *,
        context: str,
        vehicle_id: str,
        kind: str,
        old: Pair,
        new: Pair,
        request_id: str,
        fingerprint: str,
        user_id: str,
        recorded_at: str,
        note: str = "",
        related: str = "",
        accepted: Sequence[str] = (),
    ) -> dict[str, str]:
        row = dict.fromkeys(REGISTRATION_HISTORY_COLUMNS, "")
        row.update(
            change_id=f"VRH-{uuid.uuid4().hex}",
            vehicle_id=vehicle_id,
            change_kind=kind,
            old_registration_no=old[0] or "",
            old_registration_province_code=old[1] or "",
            new_registration_no=new[0] or "",
            new_registration_province_code=new[1] or "",
            recorded_at=recorded_at,
            recorded_by=user_id,
            request_id=request_id,
            request_fingerprint=fingerprint,
            related_request_id=related,
            accepted_exceptions=";".join(accepted),
            note_th=note,
            is_test_data="TRUE" if context == DATA_CONTEXT_TEST else "FALSE",
            test_batch_id=self._batch_id if context == DATA_CONTEXT_TEST else "",
        )
        return row

    async def _w1(self, history: RegistryTableRead, row: dict[str, str], request_id: str) -> None:
        try:
            await self._repository.append_vehicle_registration_history(history, row)
        except RepositoryWriteError as exc:
            message = (
                "Google Sheets rejected the registration-history write; nothing was changed by this request"
                if exc.outcome == "rejected"
                else "The registration-history write outcome is unknown (the row may have been recorded); "
                "nothing was retried"
            )
            raise _error(
                "REGISTRATION_HISTORY_WRITE_FAILED",
                message,
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {"history_write_outcome": exc.outcome, "master_write": "NOT_ATTEMPTED", "request_id": request_id},
            ) from exc

    async def _w2(
        self, master: RegistrationMasterRead, pair: Pair, updated_at: datetime, change_id: str, request_id: str
    ) -> None:
        try:
            await self._repository.write_vehicle_registration_cells(master, pair[0], pair[1], updated_at)
        except RepositoryWriteError as exc:
            raise _error(
                "VEHICLE_MASTER_WRITE_FAILED",
                "The change was recorded in the registration history, but the vehicle_master update "
                + ("was rejected" if exc.outcome == "rejected" else "has an unknown outcome")
                + "; nothing was retried. Reconcile the registration to finish it.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {
                    "history_recorded": True,
                    "change_id": change_id,
                    "master_write_outcome": exc.outcome,
                    "request_id": request_id,
                },
            ) from exc

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    # ------------------------------------------------- PATCH registration §4.4

    async def change_registration(
        self, vehicle_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> WriteOutcome:
        number = body["registration_no"]
        province = body["registration_province_code"]
        assert number is None or isinstance(number, str)
        assert province is None or isinstance(province, str)
        new: Pair = (number, province)
        expected: Pair = (body["expected_registration_no"], body["expected_registration_province_code"])  # type: ignore[assignment]

        # 1. semantic validation (zero reads)
        if number is not None and not (
            0 < len(number) <= MAX_REGISTRATION_LENGTH and registration_key(number) != ""
        ):
            raise _error(
                "REGISTRATION_TEXT_INVALID",
                f"Registration text must be 1-{MAX_REGISTRATION_LENGTH} characters with at least one "
                "letter or digit",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if number is None and province is not None:
            raise _error(
                "REGISTRATION_TEXT_REQUIRED",
                "A province cannot be recorded without registration text",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        context = self._require_write_context()

        # 2-4. R1 (+ locate, columns), R2 (+ validation)
        master = await self._read_master(vehicle_id)
        own_id = master.vehicle.vehicle_id
        history, mine = await self._read_history(own_id, context)
        current = self._master_pair(master)

        # 5. replay
        fingerprint = request_fingerprint(OP_REGISTRATION, own_id, None, body)
        hit = find_replay(history.rows, request_id, fingerprint, record_id_column="change_id")
        if hit is not None:
            return self._replay_outcome(hit, request_id, current, mine)

        # 6. projection mismatch, then stale (C1: the §4.4 order)
        if registration_consistency(mine, current) == CONSISTENCY_MISMATCH:
            raise _error(
                "REGISTRATION_PROJECTION_MISMATCH",
                "The latest recorded registration differs from the vehicle record; reconcile it first",
                status.HTTP_409_CONFLICT,
            )
        if expected != current:
            raise _error(
                "VEHICLE_REGISTRY_STALE",
                "The registration was changed by someone else; reload and try again",
                status.HTTP_409_CONFLICT,
                {"current_matches_request": new == current},
            )

        # 8. duplicates (computed before the no-op return) and no-op
        duplicates = self._duplicates(master, new)
        if new == current:
            return WriteOutcome(
                request_id=request_id,
                changed=False,
                warnings=["EXISTING_DUPLICATE_PAIR"] if duplicates else [],
            )

        # 9. reference check (R3 only when a code is given)
        if province is not None:
            refusal = self._province_refusal(province, await self._provinces(), current[1])
            if refusal is not None:
                raise refusal

        # 10. conflict
        if duplicates:
            raise self._duplicate_error(duplicates)

        # 11-13. build in memory, then W1, then W2
        now = self._now()
        recorded_at = now.isoformat(timespec="microseconds")
        row = self._history_row(
            context=context, vehicle_id=own_id, kind=CHANGE_KIND_CHANGE, old=current, new=new,
            request_id=request_id, fingerprint=fingerprint, user_id=user_id, recorded_at=recorded_at,
        )
        updated_vehicle = master.vehicle.model_copy(update={"updated_at": now})
        updated_registry = VehicleRegistry(
            registration_no=_field(number),
            registration_province=_field(province),
            responsible_branch=master.registry.responsible_branch,
        )
        await self._w1(history, row, request_id)
        await self._w2(master, new, now, row["change_id"], request_id)

        # 14. respond (no re-read: R1 plus the applied pair, C8)
        return WriteOutcome(
            request_id=request_id,
            changed=True,
            change=ChangeRecord(change_id=row["change_id"], recorded_at=recorded_at, request_id=request_id),
            master_write=MASTER_WRITE_WRITTEN,
            vehicle=updated_vehicle,
            registry=updated_registry,
        )

    # ---------------------------------------------- reconciliation §4.6

    async def reconcile_registration(
        self, vehicle_id: str, body: Mapping[str, object], *, request_id: str, user_id: str
    ) -> WriteOutcome:
        mode = body.get("mode")
        reason = body.get("reason_th")
        related_raw = body.get("related_request_id")
        related = related_raw if isinstance(related_raw, str) else ""

        # 1. semantic validation (zero reads)
        if mode not in RECONCILIATION_MODES:
            raise _error(
                "RECONCILIATION_MODE_INVALID",
                "mode must be APPLY_RECORDED or ACCEPT_MASTER",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        # The whole reason rule is semantic (§4.6 step 1): a string, not blank,
        # 1-500 characters. The valid text is kept exactly as submitted.
        if not isinstance(reason, str) or not reason.strip() or not 0 < len(reason) <= MAX_REASON_LENGTH:
            raise _error(
                "REASON_REQUIRED",
                f"A reason of 1-{MAX_REASON_LENGTH} characters is required",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        context = self._require_write_context()

        # 2. reads; every history row of the vehicle validated first
        master = await self._read_master(vehicle_id)
        own_id = master.vehicle.vehicle_id
        history, mine = await self._read_history(own_id, context)
        current = self._master_pair(master)

        # 3. replay
        fingerprint = request_fingerprint(OP_REGISTRATION_RECONCILE, own_id, None, body)
        hit = find_replay(history.rows, request_id, fingerprint, record_id_column="change_id")
        if hit is not None:
            return self._replay_outcome(hit, request_id, current, mine)

        # 4. related request (audit linkage only; settles nothing)
        if related and related not in [text(r.get("request_id")) for r in mine]:
            raise _error(
                "RELATED_REQUEST_NOT_FOUND",
                "related_request_id does not name a registration request of this vehicle",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # 5. stale checks
        expected: Pair = (body.get("expected_registration_no"), body.get("expected_registration_province_code"))  # type: ignore[assignment]
        if expected != current:
            raise _error(
                "VEHICLE_REGISTRY_STALE",
                "The registration was changed by someone else; reload and try again",
                status.HTTP_409_CONFLICT,
            )
        if body.get("expected_history_revision") != registration_history_revision(mine):
            raise _error(
                "REGISTRATION_HISTORY_STALE",
                "The registration history changed since it was loaded; reload and try again",
                status.HTTP_409_CONFLICT,
            )

        # 6. nothing to reconcile
        if registration_consistency(mine, current) != CONSISTENCY_MISMATCH:
            return WriteOutcome(request_id=request_id, changed=False)

        recorded = latest_new_pair(mine)
        assert recorded is not None  # MISMATCH implies at least one row
        now = self._now()
        recorded_at = now.isoformat(timespec="microseconds")

        if mode == "ACCEPT_MASTER":
            # 8. the master pair is accepted as it is (W1 only)
            if not pair_is_valid(*current):
                raise _error(
                    "MASTER_PAIR_INVALID",
                    "The vehicle record's registration does not satisfy the registration rules and cannot be "
                    "accepted; use APPLY_RECORDED or an approved manual correction",
                    status.HTTP_409_CONFLICT,
                )
            accepted: list[str] = []
            if current[1] is not None:
                provinces = await self._provinces()
                if current[1] not in provinces:
                    accepted.append("REFERENCE_UNKNOWN_ACCEPTED")
                elif not provinces[current[1]]:
                    accepted.append("REFERENCE_INACTIVE_ACCEPTED")
            if self._duplicates(master, current):
                accepted.append("EXISTING_DUPLICATE_PAIR")
            row = self._history_row(
                context=context, vehicle_id=own_id, kind=KIND_ACCEPT_MASTER, old=recorded, new=current,
                request_id=request_id, fingerprint=fingerprint, user_id=user_id, recorded_at=recorded_at,
                note=reason, related=related, accepted=accepted,
            )
            await self._w1(history, row, request_id)
            return WriteOutcome(
                request_id=request_id,
                changed=True,
                change=ChangeRecord(change_id=row["change_id"], recorded_at=recorded_at, request_id=request_id),
                master_write=MASTER_WRITE_NOT_NEEDED,
                warnings=accepted,
            )

        # 7. APPLY_RECORDED: the normal assignment rules, then W1 + W2
        if recorded[1] is not None:
            refusal = self._province_refusal(recorded[1], await self._provinces(), current[1])
            if refusal is not None:
                raise refusal
        duplicates = self._duplicates(master, recorded)
        if duplicates:
            raise self._duplicate_error(duplicates)
        row = self._history_row(
            context=context, vehicle_id=own_id, kind=KIND_APPLY_RECORDED, old=current, new=recorded,
            request_id=request_id, fingerprint=fingerprint, user_id=user_id, recorded_at=recorded_at,
            note=reason, related=related,
        )
        await self._w1(history, row, request_id)
        await self._w2(master, recorded, now, row["change_id"], request_id)
        return WriteOutcome(
            request_id=request_id,
            changed=True,
            change=ChangeRecord(change_id=row["change_id"], recorded_at=recorded_at, request_id=request_id),
            master_write=MASTER_WRITE_WRITTEN,
        )
