"""Phase 7 Batch 7K2 — equipment text preservation (mock / service / API).

Approved 7K1 corrected contract with DEC-K1(b), K2(b), K3(a) (prefixes
"=", "+", "-", "@", "'"), K4(a)-K8(a), K9(b), K10(a). Planned tests K01-K10.

`SpyRepository` (a MockRepository) records every repository WRITE call (any
coroutine method named create_/update_/close_/change_/assign_/mark_/add_/
upsert_/delete_/append_/record_/approve_/set_), makes the LEGACY
`get_equipment` fail loudly so any caller still using it is detected, and
can hold extra equipment records such as "0012". `SpyStorage` counts
storage.save calls. All fixtures are synthetic.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.asset import AssetType
from app.domain.asset_lookup import require_asset_exists, require_asset_for_new_work
from app.domain.common import PageParams
from app.domain.equipment import (
    Equipment,
    EquipmentCategory,
    EquipmentOperationalStatus,
)
from app.domain.equipment_errors import (
    data_invalid_error,
    equipment_lookup_error,
    equipment_write_error,
    require_equipment_id_usable_for_new_work,
)
from app.domain.equipment_rules import (
    HAZARD_PREFIXES,
    equipment_history_row_issue,
    equipment_row_issue,
    known_text_hazard,
)
from app.domain.equipment_service import EquipmentService
from app.errors import ApiError
from app.repositories.base import (
    RepositoryError,
    RepositoryIdentityAmbiguousError,
    RepositoryRecordInvalidError,
    RepositorySchemaError,
    RepositoryTabReadError,
    RepositoryWriteError,
)
from app.repositories.mock.repository import MockRepository
from app.storage.base import StorageProvider, StoredFile

WRITE_PREFIXES = ("create_", "update_", "close_", "change_", "assign_", "mark_", "add_", "upsert_",
                  "delete_", "append_", "record_", "approve_", "set_")
TS = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)


def _equipment(eid: str, *, code: str = "EC-X", name: str = "เครื่องทดสอบ",
               status: EquipmentOperationalStatus = EquipmentOperationalStatus.READY,
               category: EquipmentCategory = EquipmentCategory.LATHE, serial: str | None = None) -> Equipment:
    return Equipment(equipment_id=eid, equipment_code=code, name=name, category=category, serial_number=serial,
                     location=None, operational_status=status, created_at=TS, updated_at=TS)


class SpyRepository(MockRepository):
    def __init__(self, extra: list[Equipment] = ()) -> None:
        super().__init__()
        for item in extra:
            self._equipment[item.equipment_id] = item
        self.writes: list[str] = []
        self.validated_lookups: list[str] = []
        self.vehicle_lookups: list[str] = []
        self.allow_legacy_get_equipment = False
        for name, _ in inspect.getmembers(MockRepository, inspect.iscoroutinefunction):
            if name.startswith(WRITE_PREFIXES) and not name.endswith("_validated"):
                setattr(self, name, self._recorder(name, getattr(self, name)))

    def _recorder(self, name, method):
        async def wrapper(*args, **kwargs):
            self.writes.append(name)
            return await method(*args, **kwargs)
        return wrapper

    async def get_equipment(self, equipment_id):  # type: ignore[override]
        if not self.allow_legacy_get_equipment:
            raise AssertionError("legacy get_equipment must not be used by 7K2 paths")
        return await super().get_equipment(equipment_id)

    async def get_equipment_validated(self, equipment_id):  # type: ignore[override]
        self.validated_lookups.append(equipment_id)
        if not equipment_id.strip():
            return None
        item = self._equipment.get(equipment_id)
        return item.model_copy(deep=True) if item else None

    async def change_equipment_status_validated(self, equipment_id, status, reason, changed_by):  # type: ignore[override]
        # The actual mutation is the wrapped inner change_equipment_status call.
        self.allow_legacy_get_equipment = True
        try:
            return await super().change_equipment_status_validated(equipment_id, status, reason, changed_by)
        finally:
            self.allow_legacy_get_equipment = False

    async def get_vehicle(self, vehicle_id):  # type: ignore[override]
        self.vehicle_lookups.append(vehicle_id)
        return await super().get_vehicle(vehicle_id)


class SpyStorage(StorageProvider):
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}
        self.save_calls = 0

    async def save(self, filename: str, content_type: str, data: bytes) -> StoredFile:
        self.save_calls += 1
        ref = f"spy/{len(self.saved) + 1}-{filename}"
        self.saved[ref] = data
        return StoredFile(storage_ref=ref, filename=filename, content_type=content_type, size_bytes=len(data))

    async def read(self, storage_ref: str) -> bytes:
        return self.saved[storage_ref]

    async def delete(self, storage_ref: str) -> None:
        self.saved.pop(storage_ref, None)

    async def exists(self, storage_ref: str) -> bool:
        return storage_ref in self.saved


async def _client(repo, storage: StorageProvider | None = None):
    from app.config import get_settings
    from app.dependencies import get_repository, get_storage_provider, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_storage_provider] = lambda: storage or SpyStorage()
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver")


async def _new_instance(client) -> str:
    r = await client.post("/api/v1/part-instances", json={"part_id": "PART-0005", "prior_usage": {"quality": "UNKNOWN"}})
    assert r.status_code == 200, r.text
    return r.json()["instance"]["part_instance_id"]


# --- Mutating requests (the eight guarded sites) for one equipment id --------------------------

def _mutations(eid: str, instance_for_install: str, installed_instance: str):
    return {
        "D1b pm work order": ("POST", "/api/v1/pm/work-orders",
                              {"json": {"asset_type": "EQUIPMENT", "asset_id": eid, "pm_plan_id": "PMP-0001"}}),
        "D1c repair": ("POST", "/api/v1/repairs",
                       {"json": {"asset_type": "EQUIPMENT", "asset_id": eid, "source_type": "MANUAL", "symptom": "x"}}),
        "D1d install": ("POST", f"/api/v1/part-instances/{instance_for_install}/install",
                        {"json": {"asset_type": "EQUIPMENT", "asset_id": eid}}),
        "D1e transfer target": ("POST", f"/api/v1/part-instances/{installed_instance}/transfer",
                                {"json": {"target_asset_type": "EQUIPMENT", "target_asset_id": eid}}),
        "D1g material request": ("POST", "/api/v1/material-requests",
                                 {"json": {"source_type": "REPAIR", "source_work_order_id": "RPR-X",
                                           "asset_type": "EQUIPMENT", "asset_id": eid,
                                           "lines": [{"part_description": "x"}]}}),
        "D1h position lifetime": ("POST", "/api/v1/position-lifetime",
                                  {"json": {"asset_type": "EQUIPMENT", "asset_id": eid, "position_code": "P1",
                                            "prior_usage": {"quality": "UNKNOWN"}}}),
        "D2 inspection": ("POST", "/api/v1/inspections",
                          {"json": {"asset_type": "EQUIPMENT", "asset_id": eid,
                                    "items": [{"item_id": "ANY", "result": "PASS"}]}}),
        "D3u attachment upload": ("POST", "/api/v1/attachments",
                                  {"data": {"purpose": "INSPECTION_EVIDENCE", "source_type": "INSPECTION_EQUIPMENT",
                                            "source_id": eid},
                                   "files": {"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")}}),
    }


def _reads(eid: str):
    return {
        "R2 detail": f"/api/v1/equipment/{eid}",
        "R4 history": f"/api/v1/equipment/{eid}/status-history",
        "D1a pm plan status": f"/api/v1/pm/plans/status?asset_type=EQUIPMENT&asset_id={eid}",
        "D1f machine state": f"/api/v1/machine-state/current?asset_type=EQUIPMENT&asset_id={eid}",
        "D1i position lifetime": f"/api/v1/position-lifetime?asset_type=EQUIPMENT&asset_id={eid}",
        "D3l attachments by source": f"/api/v1/attachments/by-source/INSPECTION_EQUIPMENT/{eid}",
    }


async def _installed_on(client, eid: str) -> str:
    instance = await _new_instance(client)
    r = await client.post(f"/api/v1/part-instances/{instance}/install", json={"asset_type": "EQUIPMENT", "asset_id": eid})
    assert r.status_code == 200, r.text
    return instance


# =============================================================================================
# K01 — listed unique non-blank ids resolve through detail and history
# =============================================================================================


@pytest.mark.asyncio
async def test_k01_every_listed_unique_non_blank_id_resolves() -> None:
    """Blank and duplicate ids cannot exist in the mock (dict keys); their
    distinct outcomes (404 / 409) are KS06 over the Sheets repository."""
    repo = SpyRepository([_equipment("0012", code="0099", name="1234"), _equipment("EQ 01")])
    async with await _client(repo) as client:
        listed = (await client.get("/api/v1/equipment?page_size=200")).json()["items"]
        ids = [e["equipment_id"] for e in listed]
        assert ids == sorted(ids) and {"0012", "EQ 01", "EQP-0001"} <= set(ids)
        for eid in ids:
            detail = await client.get(f"/api/v1/equipment/{eid}")
            assert detail.status_code == 200 and detail.json()["equipment_id"] == eid
            history = await client.get(f"/api/v1/equipment/{eid}/status-history")
            assert history.status_code == 200
    assert repo.writes == []


# =============================================================================================
# K02 — 7J2 matching, category, ordering, totals and paging unchanged
# =============================================================================================


@pytest.mark.asyncio
async def test_k02_flexible_search_category_ordering_totals_and_paging_unchanged() -> None:
    service = EquipmentService(SpyRepository())

    async def ids(q=None, category=None, page=1, size=50):
        result = await service.list_equipment(q, category, PageParams(page=page, page_size=size))
        return [e.equipment_id for e in result.items], result.total_items

    assert await ids("กลึง1") == (["EQP-0001"], 1)
    assert await ids("1 กลึง") == (["EQP-0001"], 1)
    assert await ids("LATHE01") == (["EQP-0001"], 1)
    assert await ids("eqp 0002") == (["EQP-0002"], 1)
    assert await ids("--") == ([], 0)
    assert await ids(category=EquipmentCategory.WELDING) == (["EQP-0003"], 1)
    assert await ids(page=2, size=1) == (["EQP-0002"], 3)
    assert await ids(page=9, size=1) == ([], 3)


# =============================================================================================
# K03 — status change: intended response, one history entry, same-status allowed
# =============================================================================================


@pytest.mark.asyncio
async def test_k03_status_change_returns_intended_equipment_and_appends_history_once() -> None:
    repo = SpyRepository()
    async with await _client(repo) as client:
        r = await client.post("/api/v1/equipment/EQP-0001/status", json={"status": "MAINTENANCE", "reason": "0007"})
        assert r.status_code == 200 and r.json()["operational_status"] == "MAINTENANCE"
        history = (await client.get("/api/v1/equipment/EQP-0001/status-history")).json()
        assert [(h["status"], h["reason"]) for h in history] == [("MAINTENANCE", "0007")]
        same = await client.post("/api/v1/equipment/EQP-0001/status", json={"status": "MAINTENANCE"})
        assert same.status_code == 200
        assert len((await client.get("/api/v1/equipment/EQP-0001/status-history")).json()) == 2
        missing = await client.post("/api/v1/equipment/NOPE/status", json={"status": "READY"})
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "EQUIPMENT_NOT_FOUND"
    assert repo.writes.count("change_equipment_status") == 2  # the 404 wrote nothing


# =============================================================================================
# K04 — blank / whitespace ids: 404 without any repository read
# =============================================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("eid", ["", " ", "\t", "   "])
async def test_k04_blank_or_whitespace_id_is_not_found_without_a_read(eid) -> None:
    class CountingRepo(SpyRepository):
        reads = 0

        async def get_equipment_validated(self, equipment_id):  # type: ignore[override]
            if equipment_id.strip():
                CountingRepo.reads += 1
            return await super().get_equipment_validated(equipment_id)

    repo = CountingRepo()
    service = EquipmentService(repo)
    for call in (service.get_equipment(eid), service.change_status(eid, EquipmentOperationalStatus.READY, None, None),
                 service.list_status_history(eid)):
        with pytest.raises(ApiError) as info:
            await call
        assert info.value.code == "EQUIPMENT_NOT_FOUND"
    assert CountingRepo.reads == 0 and repo.writes == []


# =============================================================================================
# K05 — lookup routing; RETIRED rules; vehicle branch untouched
# =============================================================================================


@pytest.mark.asyncio
async def test_k05_all_equipment_lookup_sites_use_the_validated_lookup() -> None:
    repo = SpyRepository()  # legacy get_equipment raises if any caller still uses it
    async with await _client(repo) as client:
        for path in _reads("EQP-0001").values():
            r = await client.get(path)
            assert r.status_code == 200, (path, r.text)
        instance = await _new_instance(client)
        assert (await client.post(f"/api/v1/part-instances/{instance}/install",
                                  json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0001"})).status_code == 200
        assert (await client.post("/api/v1/repairs", json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0001",
                                                            "source_type": "MANUAL"})).status_code == 200
        up = await client.post("/api/v1/attachments", data={"purpose": "INSPECTION_EVIDENCE",
                                                             "source_type": "INSPECTION_EQUIPMENT", "source_id": "EQP-0001"},
                               files={"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")})
        assert up.status_code == 200, up.text
        vehicle = await client.get("/api/v1/pm/plans/status?asset_type=VEHICLE&asset_id=VEH-1046")
        assert vehicle.status_code == 200
    assert "EQP-0001" in repo.validated_lookups and "VEH-1046" in repo.vehicle_lookups


@pytest.mark.asyncio
async def test_k05_retired_rules_unchanged() -> None:
    retired = _equipment("EQP-R", status=EquipmentOperationalStatus.RETIRED)
    repo = SpyRepository([retired])
    storage = SpyStorage()
    async with await _client(repo, storage) as client:
        instance = await _new_instance(client)
        installed = await _installed_on(client, "EQP-0001")
        repo.writes.clear()
        for label, (method, path, kwargs) in _mutations("EQP-R", instance, installed).items():
            r = await client.request(method, path, **kwargs)
            if label == "D3u attachment upload":
                # D3 has never had a RETIRED rule (recorded difference F10; not changed).
                assert r.status_code == 200, (label, r.text)
            else:
                assert r.status_code == 422 and r.json()["error"]["code"] == "EQUIPMENT_RETIRED", (label, r.text)
        # Read-only callers: D1a/D1f/D1i keep the existing RETIRED refusal of require_asset_exists.
        assert (await client.get(_reads("EQP-R")["D1f machine state"])).json()["error"]["code"] == "EQUIPMENT_RETIRED"
        assert (await client.get(_reads("EQP-R")["R2 detail"])).status_code == 200


# =============================================================================================
# K06 — guard placement: eight mutating sites refuse "0012" before any write; reads allowed
# =============================================================================================


@pytest.mark.asyncio
async def test_k06_numeric_looking_id_is_refused_at_the_eight_mutating_sites_with_zero_writes() -> None:
    repo = SpyRepository([_equipment("0012")])
    storage = SpyStorage()
    async with await _client(repo, storage) as client:
        instance = await _new_instance(client)
        installed = await _installed_on(client, "EQP-0001")  # transfer SOURCE is ordinary
        repo.writes.clear()
        saves_before = storage.save_calls
        mutations = _mutations("0012", instance, installed)
        assert len(mutations) == 8
        for label, (method, path, kwargs) in mutations.items():
            r = await client.request(method, path, **kwargs)
            assert r.status_code == 422, (label, r.text)
            body = r.json()["error"]
            assert body["code"] == "EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK" and body["details"] == {"asset_type": "EQUIPMENT"}
            assert repo.writes == [], (label, repo.writes)  # incl. transfer removal snapshot
        assert storage.save_calls == saves_before  # attachment refused before storage.save
        # The installed instance was NOT moved off its source.
        detail = (await client.get(f"/api/v1/part-instances/{installed}")).json()
        assert detail["instance"]["status"] == "INSTALLED"


@pytest.mark.asyncio
async def test_k06_read_only_sites_and_equipment_owned_operations_accept_0012() -> None:
    repo = SpyRepository([_equipment("0012")])
    storage = SpyStorage()
    async with await _client(repo, storage) as client:
        for label, path in _reads("0012").items():
            r = await client.get(path)
            assert r.status_code == 200, (label, r.text)
        # D3f: an attachment row referencing "0012" (created outside the guarded path) still downloads.
        stored = await storage.save("x.jpg", "image/jpeg", b"\xff\xd8\xff")
        from app.domain.attachment import AttachmentPurpose
        att = await repo.create_attachment(
            purpose=AttachmentPurpose.INSPECTION_EVIDENCE, filename="x.jpg", content_type="image/jpeg",
            size_bytes=3, storage_ref=stored.storage_ref, uploaded_by="u", source_type="INSPECTION_EQUIPMENT",
            source_id="0012",
        )
        download = await client.get(f"/api/v1/attachments/{att.attachment_id}/file")
        assert download.status_code == 200, download.text  # D3f: not guarded (DEC-K10(a))
        status = await client.post("/api/v1/equipment/0012/status", json={"status": "IN_USE"})
        assert status.status_code == 200 and status.json()["equipment_id"] == "0012"
        assert (await client.get("/api/v1/equipment/12")).status_code == 404


@pytest.mark.asyncio
async def test_k06_ordinary_id_with_numeric_looking_fields_is_accepted_everywhere() -> None:
    repo = SpyRepository([_equipment("EQP-1", code="0012", name="1234", serial="0099")])
    async with await _client(repo, SpyStorage()) as client:
        instance = await _new_instance(client)
        installed = await _installed_on(client, "EQP-0001")
        # PM (seeded plan is VEHICLE-only) and inspection (synthetic item id) fail
        # later for unrelated, pre-existing reasons; the others must succeed.
        must_succeed = {"D1c repair", "D1d install", "D1e transfer target", "D1g material request",
                        "D1h position lifetime", "D3u attachment upload"}
        for label, (method, path, kwargs) in _mutations("EQP-1", instance, installed).items():
            r = await client.request(method, path, **kwargs)
            assert r.json().get("error", {}).get("code") != "EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK", (label, r.text)
            assert r.status_code != 500, (label, r.text)
            if label in must_succeed:
                assert r.status_code == 200, (label, r.text)
        listed = (await client.get("/api/v1/equipment?q=0012")).json()["items"]
        assert [(e["equipment_id"], e["equipment_code"], e["name"], e["serial_number"]) for e in listed] == [
            ("EQP-1", "0012", "1234", "0099")]


@pytest.mark.asyncio
async def test_k06_guard_is_separate_from_the_shared_lookup() -> None:
    repo = SpyRepository([_equipment("0012")])
    await require_asset_exists(repo, AssetType.EQUIPMENT, "0012")  # read-only lookup: no guard
    with pytest.raises(ApiError) as info:
        await require_asset_for_new_work(repo, AssetType.EQUIPMENT, "0012")
    assert info.value.code == "EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK"
    with pytest.raises(ApiError) as missing:
        await require_asset_for_new_work(repo, AssetType.EQUIPMENT, "9999")
    assert missing.value.code == "EQUIPMENT_NOT_FOUND"  # lookup first, then guard
    await require_asset_for_new_work(repo, AssetType.VEHICLE, "VEH-1046")  # vehicle: no guard


# =============================================================================================
# K07 — predicate table (known hazards; "not detected" is never "safe")
# =============================================================================================

HAZARDS = ["0012", "12", "1e3", "1,234", "๐๑๒", "１２", "inf", "nan", "TRUE", "false", "=A1", "+1", "-x", "@x",
           "'x", " 0012 "]
NOT_DETECTED = ["EQP-0001", "EQ 01", "0012A", "A-0012", "1_000", "2026-01-01", "5%"]


@pytest.mark.parametrize("value", HAZARDS)
def test_k07_known_hazards_are_flagged(value) -> None:
    assert known_text_hazard(value) is True
    with pytest.raises(ApiError):
        require_equipment_id_usable_for_new_work(value)


@pytest.mark.parametrize("value", NOT_DETECTED)
def test_k07_values_not_detected_are_not_flagged(value) -> None:
    """These are NOT asserted safe: e.g. "2026-01-01" and "5%" may still be
    reinterpreted by Google Sheets (date/percent) — an unresolved limit."""
    assert known_text_hazard(value) is False


def test_k07_prefix_set_is_the_approved_one() -> None:
    assert HAZARD_PREFIXES == ("=", "+", "-", "@", "'")


def test_k07_domain_rules_do_not_import_the_sheets_library() -> None:
    import app.domain.equipment_errors as errors_module
    import app.domain.equipment_rules as rules_module

    for module in (rules_module, errors_module):
        assert "gspread" not in inspect.getsource(module).replace("gspread 6.x", "")


# =============================================================================================
# K08 — envelopes for every new code
# =============================================================================================


def test_k08_lookup_and_write_envelopes() -> None:
    cases = [
        (RepositoryIdentityAmbiguousError("equipment_master", 2), 409, "EQUIPMENT_ID_AMBIGUOUS", {"match_count": 2}),
        (RepositoryRecordInvalidError("equipment_master", "UNRECOGNIZED_STATUS"), 500, "EQUIPMENT_MASTER_DATA_INVALID",
         {"issue_counts": {"UNRECOGNIZED_STATUS": 1}}),
        (RepositorySchemaError("equipment_master", "MISSING_HEADERS", ("serial_no",)), 500,
         "EQUIPMENT_MASTER_SCHEMA_INVALID", {"tab": "equipment_master", "problem": "MISSING_HEADERS", "headers": ["serial_no"]}),
        (RepositorySchemaError("equipment_status_history", "TAB_MISSING"), 500, "EQUIPMENT_STATUS_HISTORY_SCHEMA_INVALID",
         {"tab": "equipment_status_history", "problem": "TAB_MISSING", "headers": []}),
        (RepositoryTabReadError("equipment_master", "x"), 503, "EQUIPMENT_MASTER_READ_FAILED", None),
        (RepositoryTabReadError("equipment_status_history", "x"), 503, "EQUIPMENT_STATUS_HISTORY_READ_FAILED", None),
        (RepositoryWriteError("equipment_master", "rejected", 400, "x"), 503, "EQUIPMENT_MASTER_WRITE_FAILED",
         {"equipment_write_outcome": "rejected"}),
        (RepositoryWriteError("equipment_master", "unknown", None, "x"), 503, "EQUIPMENT_MASTER_WRITE_FAILED",
         {"equipment_write_outcome": "unknown"}),
        (RepositoryWriteError("equipment_status_history", "rejected", 400, "x"), 503,
         "EQUIPMENT_STATUS_HISTORY_WRITE_FAILED", {"equipment_status_updated": True, "history_write_outcome": "rejected"}),
        (RepositoryWriteError("equipment_status_history", "unknown", 503, "x"), 503,
         "EQUIPMENT_STATUS_HISTORY_WRITE_FAILED", {"equipment_status_updated": True, "history_write_outcome": "unknown"}),
    ]
    for exc, status_code, code, details in cases:
        mapped = equipment_write_error(exc)
        assert (mapped.status_code, mapped.code, mapped.details) == (status_code, code, details), code
    assert equipment_lookup_error(RepositoryWriteError("equipment_master", "unknown", None, "x")) is None
    assert equipment_write_error(RepositoryTabReadError("vehicle_master", "x")) is None
    assert equipment_write_error(RepositoryError("plain")) is None
    invalid = data_invalid_error("equipment_status_history", {"UNRECOGNIZED_STATUS": 2, "BLANK_STATUS": 1})
    assert (invalid.status_code, invalid.code, invalid.details) == (
        500, "EQUIPMENT_STATUS_HISTORY_DATA_INVALID", {"issue_counts": {"BLANK_STATUS": 1, "UNRECOGNIZED_STATUS": 2}})
    with pytest.raises(ApiError) as info:
        require_equipment_id_usable_for_new_work("0012")
    assert (info.value.status_code, info.value.code, info.value.details) == (
        422, "EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK", {"asset_type": "EQUIPMENT"})


# =============================================================================================
# K09 — unexpected exceptions still reach the generic handler
# =============================================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [KeyError("boom"), RepositoryError("not tab scoped")])
async def test_k09_unexpected_errors_reach_the_generic_500(error) -> None:
    class Raising(SpyRepository):
        async def get_equipment_validated(self, equipment_id):  # type: ignore[override]
            raise error

        async def read_equipment_master(self):  # type: ignore[override]
            raise error

    async with await _client(Raising()) as client:
        for path in ("/api/v1/equipment", "/api/v1/equipment/EQP-0001", "/api/v1/repairs"):
            if path == "/api/v1/repairs":
                r = await client.post(path, json={"asset_type": "EQUIPMENT", "asset_id": "EQP-0001", "source_type": "MANUAL"})
            else:
                r = await client.get(path)
            assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR", path


# =============================================================================================
# K10 — record-gate algorithm (pure part) and mapper classification
# =============================================================================================


def test_k10_gate_precedence_and_blank_vs_unrecognized() -> None:
    ok = {"equipment_type": "LATHE", "equipment_status": "READY"}
    assert equipment_row_issue(ok) is None
    assert equipment_row_issue({**ok, "equipment_type": "Lathe", "equipment_status": "Ready"}) == "UNRECOGNIZED_CATEGORY"
    assert equipment_row_issue({**ok, "equipment_type": "", "equipment_status": ""}) == "BLANK_CATEGORY"
    assert equipment_row_issue({**ok, "equipment_type": "   "}) == "BLANK_CATEGORY"
    assert equipment_row_issue({**ok, "equipment_type": " LATHE"}) == "UNRECOGNIZED_CATEGORY"
    assert equipment_row_issue({**ok, "equipment_status": " "}) == "BLANK_STATUS"
    for bad in ("Ready", " READY", "1", "WORKING"):
        assert equipment_row_issue({**ok, "equipment_status": bad}) == "UNRECOGNIZED_STATUS"
    assert equipment_row_issue({**ok, "equipment_status": 1}) == "UNRECOGNIZED_STATUS"
    assert equipment_history_row_issue({"status_code": ""}) == "BLANK_STATUS"
    assert equipment_history_row_issue({"status_code": "ready"}) == "UNRECOGNIZED_STATUS"
    assert equipment_history_row_issue({"status_code": "RETIRED"}) is None


@pytest.mark.parametrize("raised, expected", [
    (ValueError("v"), "UNMAPPABLE_ROW"), (TypeError("t"), "UNMAPPABLE_ROW"), ("validation", "UNMAPPABLE_ROW"),
    (KeyError("k"), KeyError), (RuntimeError("r"), RuntimeError),
])
def test_k10_only_value_and_type_errors_become_unmappable(raised, expected, monkeypatch) -> None:
    from pydantic import ValidationError

    from app.config import Settings
    from app.repositories.google_sheets import GoogleSheetsRepository

    repo = GoogleSheetsRepository(Settings(google_sheet_id="", google_application_credentials=""))

    def mapper(record):
        if raised == "validation":
            Equipment.model_validate({})  # raises pydantic ValidationError (a ValueError)
        raise raised

    monkeypatch.setattr(repo, "_equipment_from_row", mapper)
    record = {"equipment_type": "LATHE", "equipment_status": "READY"}
    if isinstance(expected, str):
        assert repo._equipment_record(record) == (expected, None)
    else:
        with pytest.raises(expected):
            repo._equipment_record(record)
    assert issubclass(ValidationError, ValueError)
