"""R2 Batch R2a — shared master-reference read foundation (branch, model, part).

Test ids R2A-01..R2A-20 are batch-local PROPOSED identifiers, not owner
business codes. Repository modes: MockRepository and GoogleSheetsRepository
on the 7B2 FAKE HTTP transport (real gspread, no credentials, no network, no
live workbook). Every fixture is synthetic (SYN- ids, labelled names).
"""
from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain import authz
from app.domain.branch_write_service import BranchWriteService
from app.domain.master_reference import (
    ACTIVE,
    ACTIVE_NOT_IN_SCHEMA,
    DATA_INVALID,
    DUPLICATE_ID,
    INACTIVE,
    MASTER_KIND_BRANCH,
    MASTER_KIND_MODEL,
    MASTER_KIND_PART,
    READ_FAILED,
    REFERENCE_UNAVAILABLE,
    RESOLVED,
    SCHEMA_INVALID,
    UNKNOWN_CODE,
    MasterReference,
    MasterReferenceResolver,
)
from app.domain.part import PartMaster, TrackingMode
from app.domain.registry_service import RegistryReadService
from app.errors import ApiError
from app.repositories.base import (
    RegistryTableRead,
    RepositoryError,
    RepositorySchemaError,
    RepositoryTabReadError,
    VehicleModelSearchEntry,
)
from app.repositories.google_sheets import schemas
from app.repositories.mock import MockRepository
from tests.test_fleet_status_summary_sheets_batch7b2 import TS, FakeSheetsBackend, _repo

SYN = " (ข้อมูลสังเคราะห์สำหรับทดสอบ)"  # "synthetic test data" label on every name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Mock(MockRepository):
    """MockRepository with replaceable synthetic tables, or a read failure."""

    def __init__(self, *, branches=None, branch_columns=("branch_id", "branch_name", "is_active"),
                 models=None, parts=None, failure: RepositoryError | None = None) -> None:
        super().__init__()
        if branches is not None:
            self._branch_master = branches
        self._branch_columns = branch_columns
        if models is not None:
            self._model_entries = models
        if parts is not None:
            self._part_masters = {p.part_id: p for p in parts}
        self.failure = failure
        self.calls: list[str] = []

    async def read_branch_master_validated(self) -> RegistryTableRead:
        self.calls.append("branch")
        if self.failure:
            raise self.failure
        return self._table(self._branch_master, self._branch_columns)

    async def read_vehicle_model_search_index(self) -> list[VehicleModelSearchEntry]:
        self.calls.append("model")
        if self.failure:
            raise self.failure
        if hasattr(self, "_model_entries"):
            return list(self._model_entries)
        return await super().read_vehicle_model_search_index()

    async def read_part_master_reference(self) -> RegistryTableRead:
        self.calls.append("part")
        if self.failure:
            raise self.failure
        return await super().read_part_master_reference()


def _branch(code: str, name: str, active: str | None = "TRUE") -> dict[str, str]:
    row = {"branch_id": code, "branch_name": name}
    if active is not None:
        row["is_active"] = active
    return row


def _part(part_id: str, name: str, active: bool = True) -> PartMaster:
    return PartMaster(part_id=part_id, part_code=f"C-{part_id}", name=name, tracking_mode=TrackingMode.NONE,
                      is_active=active, created_at=TS, updated_at=TS)


BRANCHES = [
    _branch("SYN-BR-A", "สาขา A" + SYN),
    _branch("SYN-BR-B", "สาขา B" + SYN, "FALSE"),
]
MODELS = [
    VehicleModelSearchEntry(model_id="SYN-MDL-1", model_code="SYN-QY", model_name="รุ่น 1" + SYN),
    VehicleModelSearchEntry(model_id="SYN-MDL-2", model_code="SYN-XC", model_name="รุ่น 2" + SYN),
]
PARTS = [_part("SYN-PART-1", "อะไหล่ 1" + SYN), _part("SYN-PART-2", "อะไหล่ 2" + SYN, active=False)]


def _sheet(header: list[str], rows: list[dict[str, str]]) -> list[list[str]]:
    return [list(header), *([row.get(h, "") for h in header] for row in rows)]


def _model_tab(entries: list[VehicleModelSearchEntry]) -> list[list[str]]:
    header = list(schemas.VEHICLE_MODEL_SHEET.required_headers)
    rows = [{"model_id": e.model_id, "model_code": e.model_code, "model_name": e.model_name,
             "created_at": TS, "updated_at": TS} for e in entries]
    return _sheet(header, rows)


def _part_tab(parts: list[PartMaster], *, with_active: bool = True) -> list[list[str]]:
    header = [h for h in schemas.PART_MASTER_SHEET.required_headers if with_active or h != "is_active"]
    rows = [{"part_id": p.part_id, "part_code": p.part_code, "name": p.name, "tracking_mode": "NONE",
             "is_active": "TRUE" if p.is_active else "FALSE", "created_at": TS, "updated_at": TS} for p in parts]
    return _sheet(header, rows)


def _fake(*, branches=BRANCHES, branch_header=("branch_id", "branch_name", "is_active"), models=MODELS,
          parts=PARTS, part_tab=None) -> FakeSheetsBackend:
    return FakeSheetsBackend({
        "branch_master": _sheet(list(branch_header), branches),
        "model_master": _model_tab(models),
        "part_master": part_tab if part_tab is not None else _part_tab(parts),
    })


def _ref(kind: str, rid: str, state: str, label=None, active=None, reason=None) -> MasterReference:
    return MasterReference(kind, rid, state, label=label, active_state=active, unavailable_reason=reason)


def _repos(**fake_kwargs):
    """The same synthetic data in both modes (ids: 'mock', 'fake')."""
    mock = _Mock(branches=fake_kwargs.get("branches", BRANCHES), models=fake_kwargs.get("models", MODELS),
                 parts=fake_kwargs.get("parts", PARTS))
    backend = _fake(**fake_kwargs)
    return {"mock": mock, "fake": _repo(backend)}, backend


# ---------------------------------------------------------------------------
# Branch — R2A-01..R2A-06
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_01_branch_known_id_is_resolved_with_its_existing_label(mode) -> None:
    repos, backend = _repos()
    result = await MasterReferenceResolver(repos[mode]).resolve_branches(["SYN-BR-A"])
    assert result == {"SYN-BR-A": _ref(MASTER_KIND_BRANCH, "SYN-BR-A", RESOLVED, "สาขา A" + SYN, ACTIVE)}
    assert backend.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_02_branch_unknown_id_is_unknown_code(mode) -> None:
    repos, _ = _repos()
    result = await MasterReferenceResolver(repos[mode]).resolve_branches(["SYN-BR-Z"])
    assert result == {"SYN-BR-Z": _ref(MASTER_KIND_BRANCH, "SYN-BR-Z", UNKNOWN_CODE)}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (RepositoryTabReadError("branch_master", "down"), READ_FAILED),
        (RepositoryError("not configured"), READ_FAILED),
        (RepositorySchemaError("branch_master", "MISSING_HEADERS", ["branch_name"]), SCHEMA_INVALID),
    ],
)
async def test_r2a_03_branch_read_failure_is_reference_unavailable_mock(failure, reason) -> None:
    result = await MasterReferenceResolver(_Mock(failure=failure)).resolve_branches(["SYN-BR-A", "SYN-BR-Z"])
    assert result == {
        "SYN-BR-A": _ref(MASTER_KIND_BRANCH, "SYN-BR-A", REFERENCE_UNAVAILABLE, reason=reason),
        "SYN-BR-Z": _ref(MASTER_KIND_BRANCH, "SYN-BR-Z", REFERENCE_UNAVAILABLE, reason=reason),
    }


@pytest.mark.asyncio
async def test_r2a_03_branch_read_failure_is_reference_unavailable_fake() -> None:
    backend = _fake()
    backend.fail_values_get = True
    result = await MasterReferenceResolver(_repo(backend)).resolve_branches(["SYN-BR-A"])
    assert result["SYN-BR-A"] == _ref(MASTER_KIND_BRANCH, "SYN-BR-A", REFERENCE_UNAVAILABLE, reason=READ_FAILED)
    missing_tab = FakeSheetsBackend({})
    result = await MasterReferenceResolver(_repo(missing_tab)).resolve_branches(["SYN-BR-A"])
    assert result["SYN-BR-A"] == _ref(MASTER_KIND_BRANCH, "SYN-BR-A", REFERENCE_UNAVAILABLE, reason=SCHEMA_INVALID)
    missing_header = FakeSheetsBackend({"branch_master": _sheet(["branch_id"], BRANCHES)})
    result = await MasterReferenceResolver(_repo(missing_header)).resolve_branches(["SYN-BR-A"])
    assert result["SYN-BR-A"].unavailable_reason == SCHEMA_INVALID
    assert backend.writes == missing_tab.writes == missing_header.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_04_branch_without_is_active_column_stays_resolved_and_not_inactive(mode) -> None:
    rows = [_branch("SYN-BR-A", "สาขา A" + SYN, None), _branch("SYN-BR-B", "สาขา B" + SYN, None)]
    repo = (_Mock(branches=rows, branch_columns=("branch_id", "branch_name")) if mode == "mock"
            else _repo(_fake(branches=rows, branch_header=("branch_id", "branch_name"))))
    result = await MasterReferenceResolver(repo).resolve_branches(["SYN-BR-A", "SYN-BR-B"])
    for rid, name in (("SYN-BR-A", "สาขา A"), ("SYN-BR-B", "สาขา B")):
        assert result[rid] == _ref(MASTER_KIND_BRANCH, rid, RESOLVED, name + SYN, ACTIVE_NOT_IN_SCHEMA)
        assert result[rid].active_state != INACTIVE


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_05_inactive_branch_is_still_resolved_with_inactive_metadata(mode) -> None:
    repos, _ = _repos()
    result = await MasterReferenceResolver(repos[mode]).resolve_branches(["SYN-BR-B"])
    assert result["SYN-BR-B"] == _ref(MASTER_KIND_BRANCH, "SYN-BR-B", RESOLVED, "สาขา B" + SYN, INACTIVE)


# R2A-06: every branch_master shape the accepted R1 readers distinguish.
BRANCH_CASES = {
    "active-and-inactive": (BRANCHES, ("branch_id", "branch_name", "is_active")),
    "no-active-column": ([_branch("SYN-BR-A", "A" + SYN, None), _branch("SYN-BR-B", "B" + SYN, None)],
                         ("branch_id", "branch_name")),
    "numeric-looking-codes": ([_branch("007", "ศูนย์เจ็ด" + SYN), _branch("0012", "x" + SYN, "FALSE")],
                              ("branch_id", "branch_name", "is_active")),
    "duplicate-code": ([_branch("SYN-BR-A", "A" + SYN), _branch("SYN-BR-A", "A2" + SYN)],
                       ("branch_id", "branch_name", "is_active")),
    "blank-code": ([_branch("", "A" + SYN), _branch("SYN-BR-B", "B" + SYN)], ("branch_id", "branch_name", "is_active")),
    "blank-name": ([_branch("SYN-BR-A", "")], ("branch_id", "branch_name", "is_active")),
    "invalid-active-flag": ([_branch("SYN-BR-A", "A" + SYN, "yes")], ("branch_id", "branch_name", "is_active")),
    "blank-active-flag": ([_branch("SYN-BR-A", "A" + SYN, "")], ("branch_id", "branch_name", "is_active")),
    "empty": ([], ("branch_id", "branch_name", "is_active")),
}
PROBE_IDS = ["SYN-BR-A", "SYN-BR-B", "SYN-BR-Z", "007", "7", "0012", "", " SYN-BR-A"]


async def _r1_list(repo) -> list | ApiError:
    try:
        return await RegistryReadService(repo, "TEST").list_branches()
    except ApiError as exc:
        return exc


async def _r1_destination(repo, branch_id: str) -> str:
    """The accepted R1 7O2c destination check, as an outcome code."""
    try:
        await BranchWriteService(repo, "TEST", "SYN-BATCH")._check_destination(branch_id)
    except ApiError as exc:
        return exc.code
    return "OK"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
@pytest.mark.parametrize("case", list(BRANCH_CASES))
async def test_r2a_06_branch_resolution_is_equivalent_to_accepted_r1(case, mode) -> None:
    rows, columns = BRANCH_CASES[case]
    repo = (_Mock(branches=rows, branch_columns=columns) if mode == "mock"
            else _repo(_fake(branches=rows, branch_header=columns)))
    result = await MasterReferenceResolver(repo).resolve_branches(PROBE_IDS)
    r1 = await _r1_list(repo)
    for rid in PROBE_IDS:
        ref = result[rid]
        destination = await _r1_destination(repo, rid)
        if isinstance(r1, ApiError):  # R1: BRANCH_MASTER_DATA_INVALID (whole tab)
            assert r1.code == "BRANCH_MASTER_DATA_INVALID"
            assert destination == "BRANCH_MASTER_DATA_INVALID"
            assert ref == _ref(MASTER_KIND_BRANCH, rid, REFERENCE_UNAVAILABLE, reason=DATA_INVALID)
            continue
        entry = next((e for e in r1 if e.code == rid), None)
        if entry is None:  # R1 list lacks the code; the R1 write refuses it
            assert destination == "BRANCH_NOT_FOUND"
            assert ref == _ref(MASTER_KIND_BRANCH, rid, UNKNOWN_CODE)
            continue
        assert ref.state == RESOLVED and ref.label == entry.name
        # R1 is_active False <=> INACTIVE; R1 True <=> ACTIVE, or NOT_IN_SCHEMA
        # when the optional column is absent (R1: every branch active).
        assert (ref.active_state == INACTIVE) == (not entry.is_active)
        assert ref.active_state in ((ACTIVE, ACTIVE_NOT_IN_SCHEMA) if entry.is_active else (INACTIVE,))
        assert destination == ("OK" if entry.is_active else "BRANCH_INACTIVE")


@pytest.mark.asyncio
async def test_r2a_06_branch_read_failures_match_r1_unavailability() -> None:
    for failure in (RepositoryTabReadError("branch_master", "down"),
                    RepositorySchemaError("branch_master", "MISSING_HEADERS", ["branch_name"])):
        repo = _Mock(failure=failure)
        r1 = await _r1_list(repo)
        assert isinstance(r1, ApiError) and r1.code in ("BRANCH_MASTER_READ_FAILED", "BRANCH_MASTER_SCHEMA_INVALID")
        ref = (await MasterReferenceResolver(repo).resolve_branches(["SYN-BR-A"]))["SYN-BR-A"]
        assert ref.state == REFERENCE_UNAVAILABLE  # never UNKNOWN_CODE, never an empty list


@pytest.mark.asyncio
async def test_r2a_06_get_branches_response_is_byte_compatible() -> None:
    from app.config import get_settings
    from app.dependencies import get_repository, reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = MockRepository
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/v1/branches")
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()
    assert response.status_code == 200
    expected = (
        '{"items":[{"branch_id":"BR-BANGNA-KM6","branch_name":"บางนา กม.6","is_active":true},'
        '{"branch_id":"BR-LAEM-CHABANG","branch_name":"แหลมฉบัง","is_active":true},'
        '{"branch_id":"BR-RAYONG","branch_name":"ระยอง","is_active":true}]}'
    )
    assert response.content.decode("utf-8") == expected


# ---------------------------------------------------------------------------
# Model — R2A-07..R2A-10
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_07_model_known_id_is_resolved(mode) -> None:
    repos, backend = _repos()
    result = await MasterReferenceResolver(repos[mode]).resolve_models(["SYN-MDL-1"])
    assert result == {"SYN-MDL-1": _ref(MASTER_KIND_MODEL, "SYN-MDL-1", RESOLVED, "รุ่น 1" + SYN, ACTIVE_NOT_IN_SCHEMA)}
    assert backend.writes == []


@pytest.mark.asyncio
async def test_r2a_07_model_resolution_on_unmodified_mock_seed() -> None:
    result = await MasterReferenceResolver(MockRepository()).resolve_models(["MODEL-0001"])
    assert result["MODEL-0001"].state == RESOLVED
    assert result["MODEL-0001"].label == (await MockRepository().get_vehicle_model("MODEL-0001")).model_name


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_08_model_unknown_id_is_unknown_code(mode) -> None:
    repos, _ = _repos()
    result = await MasterReferenceResolver(repos[mode]).resolve_models(["SYN-MDL-9", "SYN-QY"])
    assert result["SYN-MDL-9"] == _ref(MASTER_KIND_MODEL, "SYN-MDL-9", UNKNOWN_CODE)
    assert result["SYN-QY"].state == UNKNOWN_CODE  # a model_code is not a model_id


@pytest.mark.asyncio
async def test_r2a_09_model_read_failure_is_reference_unavailable() -> None:
    result = await MasterReferenceResolver(_Mock(failure=RepositoryTabReadError("model_master", "down"))).resolve_models(["SYN-MDL-1"])
    assert result["SYN-MDL-1"] == _ref(MASTER_KIND_MODEL, "SYN-MDL-1", REFERENCE_UNAVAILABLE, reason=READ_FAILED)
    backend = _fake()
    backend.fail_values_get = True
    result = await MasterReferenceResolver(_repo(backend)).resolve_models(["SYN-MDL-1"])
    assert result["SYN-MDL-1"] == _ref(MASTER_KIND_MODEL, "SYN-MDL-1", REFERENCE_UNAVAILABLE, reason=READ_FAILED)
    missing = FakeSheetsBackend({})
    result = await MasterReferenceResolver(_repo(missing)).resolve_models(["SYN-MDL-1"])
    assert result["SYN-MDL-1"] == _ref(MASTER_KIND_MODEL, "SYN-MDL-1", REFERENCE_UNAVAILABLE, reason=SCHEMA_INVALID)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_10_model_never_invents_active_semantics(mode) -> None:
    repos, _ = _repos()
    result = await MasterReferenceResolver(repos[mode]).resolve_models(["SYN-MDL-1", "SYN-MDL-2"])
    assert {r.active_state for r in result.values()} == {ACTIVE_NOT_IN_SCHEMA}
    assert all(r.state == RESOLVED for r in result.values())  # not invalid because of it


@pytest.mark.asyncio
async def test_r2a_10_model_extra_active_like_column_is_ignored_fake() -> None:
    """Even a stray is_active cell on model_master is not read as model state."""
    tab = _model_tab(MODELS)
    tab = [[*tab[0], "is_active"], [*tab[1], "FALSE"], [*tab[2], ""]]
    backend = FakeSheetsBackend({"model_master": tab})
    result = await MasterReferenceResolver(_repo(backend)).resolve_models(["SYN-MDL-1", "SYN-MDL-2"])
    assert [r.active_state for r in result.values()] == [ACTIVE_NOT_IN_SCHEMA, ACTIVE_NOT_IN_SCHEMA]


@pytest.mark.asyncio
async def test_r2a_model_duplicate_id_is_unavailable_not_guessed_fake() -> None:
    dup = [*MODELS, VehicleModelSearchEntry(model_id="SYN-MDL-1", model_code="SYN-DUP", model_name="ซ้ำ" + SYN)]
    result = await MasterReferenceResolver(_repo(_fake(models=dup))).resolve_models(["SYN-MDL-1", "SYN-MDL-2"])
    assert result["SYN-MDL-1"] == _ref(MASTER_KIND_MODEL, "SYN-MDL-1", REFERENCE_UNAVAILABLE, reason=DUPLICATE_ID)
    assert result["SYN-MDL-2"].state == RESOLVED  # one bad id does not hide the others


# ---------------------------------------------------------------------------
# Part — R2A-11..R2A-14
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_11_part_known_active_id(mode) -> None:
    repos, backend = _repos()
    result = await MasterReferenceResolver(repos[mode]).resolve_parts(["SYN-PART-1"])
    assert result == {"SYN-PART-1": _ref(MASTER_KIND_PART, "SYN-PART-1", RESOLVED, "อะไหล่ 1" + SYN, ACTIVE)}
    assert backend.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_12_part_known_inactive_id_is_still_resolved(mode) -> None:
    repos, _ = _repos()
    result = await MasterReferenceResolver(repos[mode]).resolve_parts(["SYN-PART-2"])
    assert result["SYN-PART-2"] == _ref(MASTER_KIND_PART, "SYN-PART-2", RESOLVED, "อะไหล่ 2" + SYN, INACTIVE)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mock", "fake"])
async def test_r2a_13_part_unknown_id(mode) -> None:
    repos, _ = _repos()
    result = await MasterReferenceResolver(repos[mode]).resolve_parts(["SYN-PART-9", "C-SYN-PART-1"])
    assert result["SYN-PART-9"] == _ref(MASTER_KIND_PART, "SYN-PART-9", UNKNOWN_CODE)
    assert result["C-SYN-PART-1"].state == UNKNOWN_CODE  # a part_code is not a part_id


@pytest.mark.asyncio
async def test_r2a_14_part_read_failure_is_reference_unavailable() -> None:
    result = await MasterReferenceResolver(_Mock(failure=RepositoryError("down"))).resolve_parts(["SYN-PART-1"])
    assert result["SYN-PART-1"] == _ref(MASTER_KIND_PART, "SYN-PART-1", REFERENCE_UNAVAILABLE, reason=READ_FAILED)
    backend = _fake()
    backend.fail_values_get = True
    result = await MasterReferenceResolver(_repo(backend)).resolve_parts(["SYN-PART-1"])
    assert result["SYN-PART-1"].unavailable_reason == READ_FAILED
    missing_tab = FakeSheetsBackend({})
    result = await MasterReferenceResolver(_repo(missing_tab)).resolve_parts(["SYN-PART-1"])
    assert result["SYN-PART-1"] == _ref(MASTER_KIND_PART, "SYN-PART-1", REFERENCE_UNAVAILABLE, reason=SCHEMA_INVALID)


PART_ROW = {"part_id": "SYN-PART-1", "part_code": "C-SYN-PART-1", "name": "อะไหล่ 1" + SYN, "is_active": "TRUE"}


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["part_id", "name", "is_active"])
async def test_r2a_14_part_missing_required_header_is_schema_invalid_fake(missing) -> None:
    """part_id, name and is_active are all required (is_active is existing
    required part metadata, unlike branch_master's optional column): a missing
    one is SCHEMA_INVALID, never RESOLVED / NOT_IN_SCHEMA."""
    header = [h for h in ("part_id", "part_code", "name", "is_active") if h != missing]
    backend = FakeSheetsBackend({"part_master": _sheet(header, [PART_ROW])})
    result = await MasterReferenceResolver(_repo(backend)).resolve_parts(["SYN-PART-1", "SYN-PART-9"])
    for rid in ("SYN-PART-1", "SYN-PART-9"):
        assert result[rid] == _ref(MASTER_KIND_PART, rid, REFERENCE_UNAVAILABLE, reason=SCHEMA_INVALID)
    assert backend.writes == []


@pytest.mark.asyncio
async def test_r2a_14_part_full_phase5_sheet_without_is_active_is_schema_invalid_fake() -> None:
    backend = _fake(part_tab=_part_tab(PARTS, with_active=False))
    result = await MasterReferenceResolver(_repo(backend)).resolve_parts(["SYN-PART-1", "SYN-PART-2"])
    assert {r.unavailable_reason for r in result.values()} == {SCHEMA_INVALID}
    assert {r.state for r in result.values()} == {REFERENCE_UNAVAILABLE}


@pytest.mark.asyncio
async def test_r2a_14_part_table_without_is_active_column_is_schema_invalid_mock() -> None:
    """The domain rule does not depend on the adapter: a part read that lacks
    the is_active column is SCHEMA_INVALID, not NOT_IN_SCHEMA."""

    class _NoActive(_Mock):
        async def read_part_master_reference(self) -> RegistryTableRead:
            return self._table([{"part_id": "SYN-PART-1", "name": "อะไหล่ 1" + SYN}], ("part_id", "name"))

    result = await MasterReferenceResolver(_NoActive()).resolve_parts(["SYN-PART-1"])
    assert result["SYN-PART-1"] == _ref(MASTER_KIND_PART, "SYN-PART-1", REFERENCE_UNAVAILABLE, reason=SCHEMA_INVALID)


@pytest.mark.asyncio
async def test_r2a_part_minimal_reference_columns_resolve_true_and_false_fake() -> None:
    """Only part_id, name and is_active are needed; other Phase 5 columns are not."""
    rows = [PART_ROW, {"part_id": "SYN-PART-2", "name": "อะไหล่ 2" + SYN, "is_active": "FALSE"}]
    backend = FakeSheetsBackend({"part_master": _sheet(["part_id", "name", "is_active"], rows)})
    result = await MasterReferenceResolver(_repo(backend)).resolve_parts(["SYN-PART-1", "SYN-PART-2"])
    assert result["SYN-PART-1"] == _ref(MASTER_KIND_PART, "SYN-PART-1", RESOLVED, "อะไหล่ 1" + SYN, ACTIVE)
    assert result["SYN-PART-2"] == _ref(MASTER_KIND_PART, "SYN-PART-2", RESOLVED, "อะไหล่ 2" + SYN, INACTIVE)


@pytest.mark.asyncio
async def test_r2a_part_active_metadata_edge_cases_fake() -> None:
    """A blank or odd flag is never read as active or inactive (DATA_INVALID
    for that part only); a duplicate id is not guessed."""
    header = ["part_id", "name", "is_active"]
    odd = _sheet(header, [
        {"part_id": "SYN-P-BLANK", "name": "ว่าง" + SYN, "is_active": ""},
        {"part_id": "SYN-P-ODD", "name": "แปลก" + SYN, "is_active": "yes"},
        {"part_id": "SYN-P-LOWER", "name": "ตัวเล็ก" + SYN, "is_active": "false"},
        {"part_id": "SYN-P-DUP", "name": "1" + SYN, "is_active": "TRUE"},
        {"part_id": "SYN-P-DUP", "name": "2" + SYN, "is_active": "TRUE"},
        {"part_id": "SYN-P-OK", "name": "ปกติ" + SYN, "is_active": "TRUE"},
    ])
    result = await MasterReferenceResolver(_repo(FakeSheetsBackend({"part_master": odd}))).resolve_parts(
        ["SYN-P-BLANK", "SYN-P-ODD", "SYN-P-LOWER", "SYN-P-DUP", "SYN-P-OK"])
    for rid in ("SYN-P-BLANK", "SYN-P-ODD", "SYN-P-LOWER"):
        assert result[rid] == _ref(MASTER_KIND_PART, rid, REFERENCE_UNAVAILABLE, reason=DATA_INVALID)
    assert result["SYN-P-DUP"].unavailable_reason == DUPLICATE_ID
    assert result["SYN-P-OK"] == _ref(MASTER_KIND_PART, "SYN-P-OK", RESOLVED, "ปกติ" + SYN, ACTIVE)


@pytest.mark.asyncio
async def test_r2a_part_reference_read_is_one_request_and_not_a_core_schema() -> None:
    backend = _fake()
    await MasterReferenceResolver(_repo(backend)).resolve_parts(["SYN-PART-1", "SYN-PART-2", "SYN-PART-9"])
    assert backend.values_reads("part_master") == 1 and backend.values_reads() == 1
    from app.repositories.google_sheets.repository import GoogleSheetsRepository

    assert all(s.tab_name != "part_master" for s in GoogleSheetsRepository._CORE_SCHEMAS)


# ---------------------------------------------------------------------------
# R2A-15 parity, R2A-16 no silent defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2a_15_mock_and_fake_sheets_semantics_match_for_all_kinds() -> None:
    repos, backend = _repos()
    ids = {
        "resolve_branches": ["SYN-BR-A", "SYN-BR-B", "SYN-BR-Z", ""],
        "resolve_models": ["SYN-MDL-1", "SYN-MDL-2", "SYN-MDL-9", ""],
        "resolve_parts": ["SYN-PART-1", "SYN-PART-2", "SYN-PART-9", ""],
    }
    for method, probe in ids.items():
        mock = await getattr(MasterReferenceResolver(repos["mock"]), method)(probe)
        fake = await getattr(MasterReferenceResolver(repos["fake"]), method)(probe)
        assert mock == fake, method
    assert backend.writes == []


@pytest.mark.asyncio
async def test_r2a_16_unknown_missing_and_error_never_become_empty_zero_or_default() -> None:
    probe = ["", " ", "0", "SYN-PART-9", "SYN-PART-1", "SYN-PART-1"]
    blank_id_row = FakeSheetsBackend({"part_master": _sheet(["part_id", "name", "is_active"], [
        {"part_id": "", "name": "ไม่มีรหัส" + SYN, "is_active": "TRUE"},
        {"part_id": "SYN-PART-1", "name": "อะไหล่ 1" + SYN, "is_active": "TRUE"},
    ])})
    result = await MasterReferenceResolver(_repo(blank_id_row)).resolve_parts(probe)
    assert list(result) == ["", " ", "0", "SYN-PART-9", "SYN-PART-1"]  # every id answered, once, in order
    for rid in ("", " ", "0", "SYN-PART-9"):  # a blank id never matches a blank-id row
        assert result[rid] == _ref(MASTER_KIND_PART, rid, UNKNOWN_CODE)
    assert result["SYN-PART-1"].state == RESOLVED
    for resolver_call in (
        MasterReferenceResolver(_Mock(failure=RepositoryError("x"))).resolve_branches,
        MasterReferenceResolver(_Mock(failure=RepositoryError("x"))).resolve_models,
        MasterReferenceResolver(_Mock(failure=RepositoryError("x"))).resolve_parts,
    ):
        out = await resolver_call(["SYN-1", "0"])
        assert list(out) == ["SYN-1", "0"]
        for ref in out.values():
            assert ref.state == REFERENCE_UNAVAILABLE and ref.unavailable_reason == READ_FAILED
            assert ref.label is None and ref.active_state is None  # no default label, never "inactive"
    empty = await MasterReferenceResolver(_Mock(branches=[], models=[], parts=[])).resolve_branches(["SYN-BR-A"])
    assert empty["SYN-BR-A"].state == UNKNOWN_CODE  # a successfully read empty master is not an outage
    assert await MasterReferenceResolver(_Mock()).resolve_parts([]) == {}


@pytest.mark.asyncio
async def test_r2a_resolver_is_read_only_and_reads_each_source_once() -> None:
    repo = _Mock(branches=BRANCHES, models=MODELS, parts=PARTS)
    resolver = MasterReferenceResolver(repo)
    await resolver.resolve_branches(["SYN-BR-A", "SYN-BR-B", "SYN-BR-A"])
    await resolver.resolve_models(["SYN-MDL-1", "SYN-MDL-2"])
    await resolver.resolve_parts(["SYN-PART-1", "SYN-PART-2"])
    assert repo.calls == ["branch", "model", "part"]
    backend = _fake()
    fake = MasterReferenceResolver(_repo(backend))
    await fake.resolve_branches(["SYN-BR-A"])
    await fake.resolve_models(["SYN-MDL-1"])
    assert backend.values_reads() == 2 and backend.writes == []
    assert backend.values_reads("maintenance_plan") == 0  # no PM plan read for a model reference


# ---------------------------------------------------------------------------
# R2A-17..R2A-19 inventory pins
# ---------------------------------------------------------------------------


def _spec() -> dict:
    from app.main import create_app

    return create_app().openapi()


def _routes() -> list[tuple[str, str]]:
    """(METHOD, path) of every documented operation (the R1 inventory view)."""
    return sorted((method.upper(), path) for path, ops in _spec()["paths"].items() for method in ops)


# The R2a master resources themselves (collection and item paths).
MASTER_RESOURCE = re.compile(r"^/api/v1/(branches|models|parts)(/\{[^/]+\})?$")


def test_r2a_17_no_delete_route_for_branch_model_or_part() -> None:
    """Referenced masters are deactivated, never hard-deleted: no DELETE on the
    branch/model/part resources. Other future resources are not constrained."""
    routes = _routes()
    assert [r for r in routes if r[0] == "DELETE" and MASTER_RESOURCE.match(r[1])] == []
    # The existing operations on these resources are still present.
    assert {
        ("GET", "/api/v1/branches"), ("GET", "/api/v1/models"), ("GET", "/api/v1/models/{model_id}"),
        ("GET", "/api/v1/parts"), ("GET", "/api/v1/parts/{part_id}"), ("POST", "/api/v1/parts"),
    } <= set(routes)


# The accepted R1 registry/branch operations (7O2 consolidated result §3), with
# the exact paths and methods of the accepted OpenAPI. Additional routes are
# allowed; a removed or re-methoded R1 operation fails.
R1_OPERATIONS = {
    ("GET", "/api/v1/branches"),
    ("GET", "/api/v1/provinces"),
    ("GET", "/api/v1/vehicles"),
    ("GET", "/api/v1/vehicles/{vehicle_id}"),
    ("GET", "/api/v1/vehicles/{vehicle_id}/branch-history"),
    ("GET", "/api/v1/vehicles/{vehicle_id}/registration-history"),
    ("PATCH", "/api/v1/vehicles/{vehicle_id}/registration"),
    ("POST", "/api/v1/vehicles/{vehicle_id}/registration-history/reconciliations"),
    ("POST", "/api/v1/vehicles/{vehicle_id}/branch-transfers"),
    ("POST", "/api/v1/vehicles/{vehicle_id}/branch-history/insertions"),
    ("POST", "/api/v1/vehicles/{vehicle_id}/branch-history/events/{event_id}/corrections"),
    ("POST", "/api/v1/vehicles/{vehicle_id}/branch-history/events/{event_id}/cancellations"),
    ("POST", "/api/v1/vehicles/{vehicle_id}/branch-projection/reconciliations"),
}


def test_r2a_18_accepted_r1_registry_and_branch_operations_still_exist() -> None:
    routes = set(_routes())
    assert R1_OPERATIONS - routes == set()


R1_REGISTRY_CAPABILITIES = ("can_edit_vehicle_registration", "can_transfer_vehicle_branch",
                            "can_correct_branch_history")


def test_r2a_19_r1_registry_capability_membership_is_not_widened() -> None:
    """Only the frozen R1 registry capabilities are pinned; new capabilities and
    roles may be added by later batches."""
    for capability in R1_REGISTRY_CAPABILITIES:
        assert capability in authz.ALL_CAPABILITIES
        for role in ("ADMIN", "MAINTENANCE_MANAGER"):
            assert capability in authz.ROLE_CAPABILITIES[role], (role, capability)
        for role in ("MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER"):
            assert capability not in authz.ROLE_CAPABILITIES.get(role, frozenset()), (role, capability)
        assert capability in authz.capabilities_for_roles(("MAINTENANCE_MANAGER",))
        assert capability not in authz.capabilities_for_roles(("MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER"))


# R2A-20 (existing R1 registry/branch regression) is the unchanged R1 suites
# (test_registry_*_batch7o2a, test_registration_write*_batch7o2b,
# test_branch_write*_batch7o2c, 7O2d) run green on this candidate; see the
# batch result document.
