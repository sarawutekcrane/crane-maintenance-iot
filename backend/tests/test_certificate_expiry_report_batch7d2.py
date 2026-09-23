"""Phase 7 Batch 7D2 — certificate expiry report
(GET /api/v1/reports/certificate-expiry): pure classification and
accounting rules, effective-status parity with the existing service,
the single Bangkok clock evaluation, query validation, ordering and
paging, authorization (current dev-auth behavior only — production
authentication is NOT implemented and not claimed), zero-write checks
over the mock repository, and NEW characterization tests of the existing
per-vehicle certificate page's read-side writes (kept as a separate test
group; nothing legacy is changed to make them pass).

The Google Sheets read is covered in
test_certificate_expiry_report_sheets_batch7d2.py. All fixtures are
synthetic (SYN-* ids), not company fleet data.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain import certificate_expiry_report as rpt
from app.domain.certificate_expiry_report import (
    CertificateReportRow,
    ReportFilter,
    build_report,
    build_report_row,
    classify_bucket,
    classify_expiry,
    classify_status,
    raw_text,
    report_effective_status,
)
from app.domain.certificate_expiry_report_service import CertificateExpiryReportService
from app.domain.vehicle_certificate import CertificateStatus, VehicleCertificate
from app.domain.vehicle_certificate_service import VehicleCertificateService
from app.errors import ApiError
from app.repositories.base import RepositoryError, RepositorySchemaError
from app.repositories.google_sheets.repository import GoogleSheetsRepository
from app.repositories.mock import MockRepository

URL = "/api/v1/reports/certificate-expiry"
AS_OF = date(2026, 3, 10)
YESTERDAY = AS_OF - timedelta(days=1)
TOMORROW = AS_OF + timedelta(days=1)
CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
PARSE = GoogleSheetsRepository._parse_date

ACTIVE = CertificateStatus.ACTIVE
EXPIRED = CertificateStatus.EXPIRED
REPLACED = CertificateStatus.REPLACED

# Repository method-name prefixes that would change stored state.
_WRITE_PREFIXES = (
    "create_", "add_", "assign_", "close_", "update_", "mark_", "append_",
    "record_", "end_", "set_", "delete_", "change_", "install_", "remove_",
    "upsert_", "save_", "acknowledge_", "mute_", "resolve_", "submit_", "convert_",
)
# Legacy certificate/vehicle reads the report must never use.
_FORBIDDEN_READS = (
    "get_vehicle", "list_vehicles", "get_vehicle_certificate",
    "list_vehicle_certificates_for_vehicle", "read_vehicle_master_for_summary",
)


def _cert(
    cid: str,
    vid: str = "SYN-VEH-1",
    type_code: str | None = "SYN-TYPE-A",
    status: object = ACTIVE,
    expiry: object = None,
    replaced_by: str | None = None,
    document_no: str | None = None,
    type_name: str | None = None,
    **extra: object,
) -> VehicleCertificate:
    """Typed certificate; `model_construct` so invalid synthetic values
    (unrecognized status text, bad dates, missing created_at) can be
    stored exactly as given."""
    values: dict[str, object] = dict(
        certificate_id=cid,
        vehicle_id=vid,
        certificate_type_code=type_code,
        certificate_type_name_th=type_name,
        document_no=document_no,
        issue_date=None,
        expiry_date=expiry,
        alert_lead_days=None,
        certificate_status=status,
        replaced_by_certificate_id=replaced_by,
        storage_ref=None,
        created_by_user_id=None,
        created_at=CREATED,
        note_th=None,
    )
    values.update(extra)
    return VehicleCertificate.model_construct(**values)


class _SpyRepository(MockRepository):
    """Mock repository seeded with certificates (storage order = list
    order) that records every public coroutine call."""

    def __init__(self, certificates: list[VehicleCertificate] | None = None) -> None:
        super().__init__()
        self.calls: list[str] = []
        for c in certificates or []:
            self._vehicle_certificates.setdefault(c.vehicle_id, []).append(c)

    def __getattribute__(self, name: str):
        attr = super().__getattribute__(name)
        if not name.startswith("_") and inspect.iscoroutinefunction(attr):
            calls = super().__getattribute__("calls")

            async def wrapper(*args, **kwargs):
                calls.append(name)
                return await attr(*args, **kwargs)

            return wrapper
        return attr

    def writes(self) -> list[str]:
        return [c for c in self.calls if c.startswith(_WRITE_PREFIXES)]

    def stored(self) -> list[dict]:
        return [
            {k: getattr(c, k, None) for k in VehicleCertificate.model_fields}
            for entries in self._vehicle_certificates.values()
            for c in entries
        ]


class _FailingRepository(_SpyRepository):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self._exc = exc

    async def read_vehicle_certificates_for_report(self):
        raise self._exc


class _Clock:
    def __init__(self, today: date = AS_OF) -> None:
        self.today = today
        self.calls = 0

    def __call__(self) -> date:
        self.calls += 1
        return self.today


async def _report(repo, clock: Callable[[], date] | None = None, **kwargs):
    params = dict(mode="RANGE", expiry_from=None, expiry_to=None, effective_status=None, page=1, page_size=200)
    params.update(kwargs)
    return await CertificateExpiryReportService(repo, clock or _Clock()).get_report(**params)


async def _report_error(repo, clock=None, **kwargs) -> ApiError:
    with pytest.raises(ApiError) as info:
        await _report(repo, clock, **kwargs)
    return info.value


async def _api(repo, path: str = URL, headers: dict[str, str] | None = None, clock: Callable[[], date] | None = None):
    from app.config import get_settings
    from app.dependencies import (
        get_certificate_expiry_report_service,
        get_repository,
        reset_dependency_cache,
    )
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    if clock is not None:
        app.dependency_overrides[get_certificate_expiry_report_service] = (
            lambda: CertificateExpiryReportService(repo, clock)
        )
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers=headers or {})
    finally:
        reset_dependency_cache()
        get_settings.cache_clear()


def _ids(report) -> list[str]:
    return [i.certificate_id for i in report.items]


def _pop(report) -> dict:
    return vars(report.population)


def _assert_equations(report) -> None:
    p = report.population
    assert p.read_record_count == (
        p.in_scope_count + p.excluded_replaced_count + p.excluded_status_blank_count + p.issue_row_count
    )
    assert p.in_scope_count == p.in_scope_with_expiry_date_count + p.in_scope_without_expiry_date_count
    assert report.complete == (p.issue_row_count == 0)


# ---------------------------------------------------------------------------
# DEC 10 — value conversion and classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ("BLANK", None)),
        ("", ("BLANK", None)),
        (" ", ("UNRECOGNIZED", None)),
        ("0", ("UNRECOGNIZED", None)),
        (0, ("UNRECOGNIZED", None)),
        (0.0, ("UNRECOGNIZED", None)),
        (True, ("UNRECOGNIZED", None)),
        (False, ("UNRECOGNIZED", None)),
        ("active", ("UNRECOGNIZED", None)),
        ("Active", ("UNRECOGNIZED", None)),
        (" ACTIVE", ("UNRECOGNIZED", None)),
        ("ACTIVE ", ("UNRECOGNIZED", None)),
        ("ACTIVE\n", ("UNRECOGNIZED", None)),
        ("CANCELLED", ("UNRECOGNIZED", None)),
        ("ACTIVE", ("VALID", "ACTIVE")),
        ("EXPIRED", ("VALID", "EXPIRED")),
        ("REPLACED", ("VALID", "REPLACED")),
        (CertificateStatus.ACTIVE, ("VALID", "ACTIVE")),
        (CertificateStatus.REPLACED, ("VALID", "REPLACED")),
    ],
)
def test_classify_status(value, expected) -> None:
    assert classify_status(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ("BLANK", None)),
        ("", ("BLANK", None)),
        (" ", ("INVALID", None)),
        ("\t", ("INVALID", None)),
        (0, ("INVALID", None)),
        (0.0, ("INVALID", None)),
        ("0", ("INVALID", None)),
        (True, ("INVALID", None)),
        (False, ("INVALID", None)),
        ("TRUE", ("INVALID", None)),
        ("2026-02-30", ("INVALID", None)),
        ("15/01/2026", ("INVALID", None)),
        ("2026-01-15T00:00:00", ("INVALID", None)),
        (" 2026-01-15", ("INVALID", None)),
        (datetime(2026, 1, 15, 8, 0), ("INVALID", None)),
        ("2026-01-15", ("VALID", date(2026, 1, 15))),
        ("2028-02-29", ("VALID", date(2028, 2, 29))),
        (date(2026, 1, 15), ("VALID", date(2026, 1, 15))),
        # Accepted legacy (stdlib ISO) forms stay accepted, as by the
        # unchanged _parse_date: compact and week dates, and a compact
        # date numericised by gspread into an int.
        ("20260115", ("VALID", date(2026, 1, 15))),
        (20260115, ("VALID", date(2026, 1, 15))),
        ("2026-W03-4", ("VALID", date(2026, 1, 15))),
        ("2026W034", ("VALID", date(2026, 1, 15))),
    ],
)
def test_classify_expiry_with_the_unchanged_legacy_parser(value, expected) -> None:
    assert classify_expiry(value, PARSE) == expected


def test_legacy_parse_date_is_unchanged_and_silently_forgiving() -> None:
    # The report must not inherit this silent None: 0 / "0" / " " / bad
    # dates map to None in the legacy parser but are INVALID in the report.
    for value in (0, "", None, False):
        assert PARSE(value) is None
    for value in ("0", " ", "2026-02-30", True):
        assert PARSE(value) is None
    assert PARSE("2026-01-15") == date(2026, 1, 15)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("  SYN-1  ", "  SYN-1  "),
        ("ใบรับรองั", "ใบรับรองั"),
        ("Café", "Café"),
        ("0012", "0012"),
        (CertificateStatus.ACTIVE, "ACTIVE"),
        (True, "TRUE"),
        (False, "FALSE"),
        (0, "0"),
        (123, "123"),
        (1.5, "1.5"),
        (0.1 + 0.2, repr(0.1 + 0.2)),
        (date(2026, 1, 5), "2026-01-05"),
        (datetime(2026, 1, 5, 7, 30), "2026-01-05T07:30:00"),
        (object(), None),
        ([1], None),
        ({"a": 1}, None),
    ],
)
def test_raw_text_conversion(value, expected) -> None:
    assert raw_text(value) == expected


def test_enum_str_is_not_its_stored_value_so_enums_are_checked_first() -> None:
    assert str(CertificateStatus.ACTIVE) != "ACTIVE"
    assert raw_text(CertificateStatus.ACTIVE) == "ACTIVE"


# ---------------------------------------------------------------------------
# Row building and exclusive accounting
# ---------------------------------------------------------------------------


def _row(read_index: int = 0, **record) -> CertificateReportRow:
    base = {
        "certificate_id": f"SYN-C-{read_index}",
        "vehicle_id": "SYN-VEH-1",
        "certificate_type_code": "SYN-TYPE-A",
        "certificate_type_name_th": "",
        "document_no": "",
        "issue_date": "",
        "expiry_date": "",
        "alert_lead_days": "",
        "certificate_status": "ACTIVE",
        "replaced_by_certificate_id": "",
        "storage_ref": "",
        "created_by_user_id": "",
        "created_at": "2026-01-01T00:00:00+00:00",
        "note_th": "",
    }
    base.update(record)
    return build_report_row(
        read_index, base, GoogleSheetsRepository(_unconfigured_settings())._vehicle_certificate_from_row, PARSE, ""
    )


def _unconfigured_settings():
    from app.config import Settings

    return Settings(google_sheet_id="", google_application_credentials="")


def test_mapping_runs_on_a_copy_and_unrecognized_status_is_blanked_only_there() -> None:
    record = {"certificate_status": "Active", "certificate_id": "SYN-1", "vehicle_id": "V", "created_at": ""}
    seen: list[dict] = []

    def mapper(candidate: dict) -> VehicleCertificate:
        seen.append(candidate)
        candidate["vehicle_id"] = "MUTATED"
        return VehicleCertificate(certificate_id="SYN-1", vehicle_id="V", created_at=CREATED)

    row = build_report_row(0, record, mapper, PARSE, "")
    assert seen[0]["certificate_status"] == ""
    assert record["certificate_status"] == "Active" and record["vehicle_id"] == "V"
    assert (row.status_class, row.mapping_ok, row.status_input) == ("UNRECOGNIZED", True, "Active")


def test_mapper_invalid_date_to_none_does_not_override_expiry_classification() -> None:
    row = _row(expiry_date="2026-02-30")
    assert row.mapping_ok and row.certificate is not None and row.certificate.expiry_date is None
    assert row.expiry_class == "INVALID" and classify_bucket(row) == "ISSUE_IN_SCOPE_DEFECT"


def test_only_value_and_type_errors_are_row_defects() -> None:
    def boom(_: dict) -> VehicleCertificate:
        raise KeyError("unexpected")

    with pytest.raises(KeyError):
        build_report_row(0, {"certificate_status": "ACTIVE"}, boom, PARSE, "")


def test_unsupported_raw_value_is_a_mapping_defect_without_an_invented_id() -> None:
    row = build_report_row(
        0, {"certificate_id": object(), "certificate_status": "ACTIVE"}, lambda r: 1 / 0, PARSE, ""
    )
    assert row.certificate_id_text == "" and not row.mapping_ok and row.certificate is None


def test_bucket_precedence_and_exact_accounting() -> None:
    rows = [
        _row(0, certificate_status="Active", expiry_date="bad", alert_lead_days="x"),  # unknown + 2 more defects
        _row(1, certificate_status="REPLACED", expiry_date="bad"),  # excluded, other defect
        _row(2, certificate_status="", alert_lead_days="not-int"),  # excluded blank, unmappable
        _row(3, certificate_status="ACTIVE", expiry_date="0"),  # in-scope defect
        _row(4, certificate_status="EXPIRED", created_at=2026),  # unmappable (legacy TypeError)
        _row(5, certificate_status="ACTIVE", expiry_date=TOMORROW.isoformat()),
        _row(6, certificate_status="EXPIRED"),  # no expiry
        _row(7, certificate_status="REPLACED"),
        _row(8, certificate_status=""),
        _row(9, certificate_status=0),  # numeric zero: unknown status
    ]
    assert [classify_bucket(r) for r in rows] == [
        "ISSUE_UNKNOWN_STATUS", "EXCLUDED_REPLACED", "EXCLUDED_STATUS_BLANK",
        "ISSUE_IN_SCOPE_DEFECT", "ISSUE_IN_SCOPE_DEFECT", "IN_SCOPE", "IN_SCOPE",
        "EXCLUDED_REPLACED", "EXCLUDED_STATUS_BLANK", "ISSUE_UNKNOWN_STATUS",
    ]
    report = build_report(rows, AS_OF, _range(), 1, 50)
    assert _pop(report) == {
        "read_record_count": 10,
        "in_scope_count": 2,
        "in_scope_with_expiry_date_count": 1,
        "in_scope_without_expiry_date_count": 1,
        "excluded_replaced_count": 2,
        "excluded_status_blank_count": 2,
        "issue_row_count": 4,
        "excluded_rows_with_other_defects": 2,
        "replaced_link_observations": 2,
    }
    assert report.data_issues.issue_defect_counts == {
        "INVALID_EXPIRY_DATE": 2,
        "UNMAPPABLE_ROW": 2,
        "UNRECOGNIZED_STATUS": 2,
    }
    # Occurrences, not records: the sum exceeds issue_row_count.
    assert sum(report.data_issues.issue_defect_counts.values()) > report.population.issue_row_count
    assert report.data_issues.sample_certificate_ids == ["SYN-C-0", "SYN-C-3", "SYN-C-4", "SYN-C-9"]
    assert report.complete is False
    _assert_equations(report)


def _range(from_: date | None = None, to: date | None = None, status: str | None = None) -> ReportFilter:
    return ReportFilter("RANGE", from_, to, to or AS_OF, to is None, status)


def _missing(status: str | None = None) -> ReportFilter:
    return ReportFilter("MISSING_EXPIRY_DATE", None, None, None, False, status)


def test_all_invalid_rows_give_an_explicit_incomplete_empty_result() -> None:
    rows = [_row(i, certificate_status=s) for i, s in enumerate(["Active", "0", " ", "expired"])]
    report = build_report(rows, AS_OF, _range(), 1, 50)
    assert (report.items, report.total_items, report.complete) == ([], 0, False)
    assert report.population.issue_row_count == report.population.read_record_count == 4
    _assert_equations(report)


def test_samples_are_distinct_sorted_capped_and_blank_ids_are_counted_not_sampled() -> None:
    ids = [f"SYN-{i:02d}" for i in range(25, 0, -1)] + ["SYN-05", "", "   ", "\t"]
    rows = [_row(i, certificate_id=cid, certificate_status="bad") for i, cid in enumerate(ids)]
    di = build_report(rows, AS_OF, _range(), 1, 50).data_issues
    assert di.sample_certificate_ids == sorted({f"SYN-{i:02d}" for i in range(1, 26)})[:20]
    assert di.issue_rows_without_usable_id == 3


def test_duplicate_and_blank_ids_across_buckets_partitioned_by_read_index() -> None:
    rows = [
        _row(0, certificate_id="SYN-DUP", expiry_date=TOMORROW.isoformat()),
        _row(1, certificate_id="SYN-DUP", certificate_status="REPLACED"),  # excluded twin still counts
        _row(2, certificate_id="SYN-ISS", certificate_status="bad"),
        _row(3, certificate_id="SYN-ISS", expiry_date=TOMORROW.isoformat()),  # twin of an issue row
        _row(4, certificate_id="", expiry_date=TOMORROW.isoformat()),
        _row(5, certificate_id="  ", expiry_date=TOMORROW.isoformat()),
        _row(6, certificate_id="SYN-SAME", expiry_date=TOMORROW.isoformat()),
        _row(7, certificate_id="SYN-SAME", expiry_date=TOMORROW.isoformat()),  # identical twin kept
        _row(8, certificate_id="syn-dup", expiry_date=TOMORROW.isoformat()),  # case differs: not a duplicate
    ]
    report = build_report(rows, AS_OF, _range(to=TOMORROW), 1, 50)
    flags = {(i.certificate_id, n): i.flags for n, i in enumerate(report.items)}
    assert report.total_items == 7
    assert [i.certificate_id for i in report.items].count("SYN-SAME") == 2
    by_id = {i.certificate_id: i.flags for i in report.items}
    assert "DUPLICATE_CERTIFICATE_ID" in by_id["SYN-DUP"]
    assert "DUPLICATE_CERTIFICATE_ID" in by_id["SYN-ISS"]
    assert "DUPLICATE_CERTIFICATE_ID" in by_id["SYN-SAME"]
    assert "DUPLICATE_CERTIFICATE_ID" not in by_id["syn-dup"]
    for blank_id in ("", "  "):
        assert "BLANK_CERTIFICATE_ID" in by_id[blank_id]
        assert "DUPLICATE_CERTIFICATE_ID" not in by_id[blank_id]  # blanks are never "duplicates"
    # Rows are partitioned by read_index, never merged: 7 in-scope rows.
    assert len(flags) == 7


# ---------------------------------------------------------------------------
# DEC 9 — effective status, parity with the existing service
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stored", ["ACTIVE", "EXPIRED"])
@pytest.mark.parametrize("expiry", [YESTERDAY, AS_OF, TOMORROW, None])
@pytest.mark.asyncio
async def test_effective_status_parity_with_existing_reconciliation(stored, expiry, monkeypatch) -> None:
    import app.domain.vehicle_certificate_service as legacy

    monkeypatch.setattr(legacy, "bangkok_today", lambda: AS_OF)
    cert = VehicleCertificate(
        certificate_id="SYN-P", vehicle_id="SYN-VEH-1", certificate_status=stored,
        expiry_date=expiry, created_at=CREATED,
    )
    repo = _SpyRepository([cert])
    reconciled = await VehicleCertificateService(repo)._reconcile_expiry(cert.model_copy())
    assert report_effective_status(stored, expiry, AS_OF) == reconciled.certificate_status.value


def test_effective_status_and_position_table() -> None:
    assert report_effective_status("ACTIVE", YESTERDAY, AS_OF) == "EXPIRED"
    assert report_effective_status("ACTIVE", AS_OF, AS_OF) == "ACTIVE"
    assert report_effective_status("ACTIVE", TOMORROW, AS_OF) == "ACTIVE"
    assert report_effective_status("ACTIVE", None, AS_OF) == "ACTIVE"
    assert report_effective_status("EXPIRED", TOMORROW, AS_OF) == "EXPIRED"
    assert report_effective_status("EXPIRED", AS_OF, AS_OF) == "EXPIRED"
    assert report_effective_status("EXPIRED", None, AS_OF) == "EXPIRED"
    with pytest.raises(ValueError):
        report_effective_status("REPLACED", None, AS_OF)
    assert [rpt.expiry_position(d, AS_OF) for d in (YESTERDAY, AS_OF, TOMORROW, None)] == [
        "BEFORE_TODAY", "TODAY", "AFTER_TODAY", "NO_EXPIRY_DATE",
    ]


def test_report_execution_does_not_reference_legacy_reconciliation() -> None:
    import app.api.v1.reports as route
    import app.domain.certificate_expiry_report_service as service

    for module in (rpt, service, route):
        source = inspect.getsource(module)
        assert "_reconcile_expiry" not in source.replace("`VehicleCertificateService._reconcile_expiry`", "")
        assert "mark_vehicle_certificate" not in source
        assert "list_vehicle_certificates_for_vehicle" not in source
    assert "alert_lead_days" not in inspect.getsource(rpt.build_report)


# ---------------------------------------------------------------------------
# Flags and group observations (DEC 2)
# ---------------------------------------------------------------------------


def test_group_flags_use_all_readable_rows_and_exact_original_keys() -> None:
    rows = [
        _row(0, certificate_id="A-OLD", expiry_date=YESTERDAY.isoformat()),  # stored ACTIVE, eff EXPIRED
        _row(1, certificate_id="A-NEW", expiry_date=""),  # ACTIVE, no expiry (counts in group)
        _row(2, certificate_id="A-HIST", certificate_status="EXPIRED", expiry_date="2020-01-01"),
        _row(3, certificate_id="B-1", certificate_type_code="SYN-TYPE-B", expiry_date=TOMORROW.isoformat()),
        _row(4, certificate_id="B-2", certificate_type_code="SYN-TYPE-B", expiry_date=AS_OF.isoformat()),
        _row(5, certificate_id="B-CASE", certificate_type_code="syn-type-b", expiry_date=TOMORROW.isoformat()),
        _row(6, certificate_id="B-SPACE", certificate_type_code="SYN-TYPE-B ", expiry_date=TOMORROW.isoformat()),
        _row(7, certificate_id="N-1", certificate_type_code="", expiry_date=TOMORROW.isoformat()),
        _row(8, certificate_id="N-2", certificate_type_code="  ", expiry_date=TOMORROW.isoformat()),
        _row(9, certificate_id="N-3", certificate_type_code="  ", expiry_date=TOMORROW.isoformat()),
        _row(10, certificate_id="V-BLANK", vehicle_id=" ", expiry_date=TOMORROW.isoformat()),
        _row(11, certificate_id="V-BLANK2", vehicle_id=" ", expiry_date=TOMORROW.isoformat()),
        _row(12, certificate_id="E-TODAY", certificate_type_code="SYN-TYPE-C", certificate_status="EXPIRED", expiry_date=AS_OF.isoformat()),
        _row(13, certificate_id="L-1", certificate_type_code="SYN-TYPE-D", replaced_by_certificate_id="X", expiry_date=TOMORROW.isoformat()),
        _row(14, certificate_id="R-ACT", certificate_type_code="SYN-TYPE-C", certificate_status="REPLACED", expiry_date=TOMORROW.isoformat()),
        _row(15, certificate_id="I-ACT", certificate_type_code="SYN-TYPE-C", expiry_date="bad"),
    ]
    report = build_report(rows, AS_OF, _range(to=date(2030, 1, 1)), 1, 50)
    flags = {i.certificate_id: i.flags for i in report.items}
    assert flags["A-OLD"] == ["SAME_TYPE_ACTIVE_EXISTS", "STORED_ACTIVE_PAST_EXPIRY"]
    assert flags["A-HIST"] == ["SAME_TYPE_ACTIVE_EXISTS"]
    assert "A-NEW" not in flags  # no expiry: not in a RANGE result, but still counted in its group
    assert flags["B-1"] == ["MULTIPLE_ACTIVE_SAME_TYPE"] and flags["B-2"] == ["MULTIPLE_ACTIVE_SAME_TYPE"]
    assert flags["B-CASE"] == [] and flags["B-SPACE"] == []
    assert flags["N-1"] == flags["N-2"] == flags["N-3"] == []  # blank type code: no group
    assert flags["V-BLANK"] == ["BLANK_VEHICLE_ID"] == flags["V-BLANK2"]
    # Excluded/issue rows never create group observations.
    assert flags["E-TODAY"] == ["STORED_EXPIRED_EXPIRY_NOT_BEFORE_TODAY"]
    assert flags["L-1"] == ["LINK_PRESENT_ON_NON_REPLACED"]
    missing = build_report(rows, AS_OF, _missing(), 1, 50)
    assert [(i.certificate_id, i.flags) for i in missing.items] == [("A-NEW", [])]


def test_flags_and_disclosures_are_independent_of_filter_and_page() -> None:
    rows = [
        _row(0, certificate_id="OLD", certificate_status="EXPIRED", expiry_date="2020-01-01"),
        _row(1, certificate_id="CUR", expiry_date="2031-01-01"),
        _row(2, certificate_id="BAD", certificate_status="bad"),
    ]
    narrow = build_report(rows, AS_OF, _range(to=date(2021, 1, 1)), 1, 50)
    assert [(i.certificate_id, i.flags) for i in narrow.items] == [("OLD", ["SAME_TYPE_ACTIVE_EXISTS"])]
    full = build_report(rows, AS_OF, _range(to=date(2031, 1, 1)), 2, 1)
    assert [i.certificate_id for i in full.items] == ["CUR"] and full.total_items == 2
    only_expired = build_report(rows, AS_OF, _range(to=date(2031, 1, 1), status="EXPIRED"), 1, 50)
    assert _ids(only_expired) == ["OLD"] and only_expired.items[0].flags == ["SAME_TYPE_ACTIVE_EXISTS"]
    for r in (narrow, full, only_expired):
        assert r.population == narrow.population and r.data_issues == narrow.data_issues
        assert r.complete is False


def test_replaced_link_observations() -> None:
    rows = [
        _row(0, certificate_id="C-1"),
        _row(1, certificate_id="R-OK", certificate_status="REPLACED", replaced_by_certificate_id="C-1"),
        _row(2, certificate_id="R-BLANK", certificate_status="REPLACED", replaced_by_certificate_id=""),
        _row(3, certificate_id="R-WS", certificate_status="REPLACED", replaced_by_certificate_id="  "),
        _row(4, certificate_id="R-GONE", certificate_status="REPLACED", replaced_by_certificate_id="C-404"),
        _row(5, certificate_id="R-CASE", certificate_status="REPLACED", replaced_by_certificate_id="c-1"),
        _row(6, certificate_id="R-ISSUE", certificate_status="REPLACED", replaced_by_certificate_id="I-1"),
        _row(7, certificate_id="I-1", certificate_status="bad"),  # target exists, even as an issue row
    ]
    assert build_report(rows, AS_OF, _range(), 1, 50).population.replaced_link_observations == 4


# ---------------------------------------------------------------------------
# Mock repository read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_read_keeps_none_as_absent_and_enum_values_and_no_extra_fields() -> None:
    repo = _SpyRepository([
        VehicleCertificate(
            certificate_id="SYN-M1", vehicle_id="SYN-VEH-1", certificate_status=ACTIVE,
            expiry_date=TOMORROW, document_no="000123", storage_ref="SECRET-STORAGE-REF",
            alert_lead_days=99, note_th="SECRET-NOTE", created_at=CREATED,
        ),
    ])
    read = await repo.read_vehicle_certificates_for_report()
    row = read.rows[0]
    assert (row.type_code_text, row.type_name_text, row.replaced_by_text) == ("", "", "")
    assert row.document_no_text == "000123" and row.stored_status == "ACTIVE"
    assert "None" not in (row.type_code_text, row.type_name_text, row.replaced_by_text)
    response = await _api(repo, f"{URL}?expiry_to=2030-01-01", clock=_Clock())
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item == {
        "certificate_id": "SYN-M1",
        "vehicle_id": "SYN-VEH-1",
        "certificate_type_code": None,
        "certificate_type_name_th": None,
        "document_no": "000123",
        "expiry_date": TOMORROW.isoformat(),
        "stored_status": "ACTIVE",
        "effective_status": "ACTIVE",
        "expiry_position": "AFTER_TODAY",
        "flags": [],
    }
    for secret in ("SECRET-STORAGE-REF", "SECRET-NOTE", "alert_lead_days", "storage_ref", "99"):
        assert secret not in response.text


@pytest.mark.asyncio
async def test_mock_unmappable_and_unrecognized_values() -> None:
    repo = _SpyRepository([
        _cert("SYN-U1", status="Active"),
        _cert("SYN-U2", created_at=None),  # would fail the model
        _cert("SYN-U3", expiry="2026-02-30"),
        _cert("SYN-OK", expiry=TOMORROW),
    ])
    report = await _report(repo, expiry_to="2030-01-01")
    assert _ids(report) == ["SYN-OK"]
    assert report.population.issue_row_count == 3
    assert report.data_issues.issue_defect_counts["UNRECOGNIZED_STATUS"] == 1
    assert report.data_issues.sample_certificate_ids == ["SYN-U1", "SYN-U2", "SYN-U3"]
    _assert_equations(report)


# ---------------------------------------------------------------------------
# Clock, dates and query validation (DEC 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clock_is_evaluated_exactly_once_per_request_and_not_for_rejected_input() -> None:
    repo = _SpyRepository([_cert("SYN-1", expiry=AS_OF)])
    for kwargs in ({}, {"mode": "MISSING_EXPIRY_DATE"}, {"expiry_to": "2026-12-31"}, {"page": 99}):
        clock = _Clock()
        await _report(repo, clock, **kwargs)
        assert clock.calls == 1, kwargs
    for kwargs in (
        {"expiry_from": "2026-02-30"},
        {"expiry_to": "20260101"},
        {"mode": "MISSING_EXPIRY_DATE", "expiry_to": "2026-01-01"},
    ):
        clock = _Clock()
        await _report_error(repo, clock, **kwargs)
        assert clock.calls == 0, kwargs
    clock = _Clock()
    await _report_error(repo, clock, expiry_from="2026-12-31")
    assert clock.calls == 1
    clock = _Clock()
    await _report_error(_FailingRepository(RepositoryError("x")), clock)
    assert clock.calls == 1


@pytest.mark.asyncio
async def test_default_end_date_is_dynamic_per_request() -> None:
    repo = _SpyRepository([_cert("SYN-1", expiry=AS_OF), _cert("SYN-2", expiry=TOMORROW)])
    clock = _Clock(AS_OF)
    first = await _report(repo, clock)
    clock.today = TOMORROW
    second = await _report(repo, clock)
    assert (first.filter.expiry_to_resolved, _ids(first)) == (AS_OF, ["SYN-1"])
    assert (second.filter.expiry_to_resolved, _ids(second)) == (TOMORROW, ["SYN-1", "SYN-2"])
    assert first.filter.expiry_to_is_default and second.filter.expiry_to_is_default
    # The effective status of SYN-1 flips at the new as_of.
    assert [i.effective_status for i in second.items] == ["EXPIRED", "ACTIVE"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("utc_instant", "bangkok_date"),
    [
        (datetime(2026, 3, 9, 16, 59, 59, tzinfo=timezone.utc), date(2026, 3, 9)),
        (datetime(2026, 3, 9, 17, 0, 0, tzinfo=timezone.utc), date(2026, 3, 10)),
    ],
)
async def test_default_clock_is_bangkok_midnight(utc_instant, bangkok_date, monkeypatch) -> None:
    import app.domain.common as common

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401
            return utc_instant.astimezone(tz) if tz else utc_instant.replace(tzinfo=None)

    monkeypatch.setattr(common, "datetime", _FixedDateTime)
    repo = _SpyRepository([_cert("SYN-1", expiry=date(2026, 3, 9))])
    report = await CertificateExpiryReportService(repo).get_report(
        mode="RANGE", expiry_from=None, expiry_to=None, effective_status=None, page=1, page_size=50
    )
    assert report.as_of_date == bangkok_date
    expected = "ACTIVE" if bangkok_date == date(2026, 3, 9) else "EXPIRED"
    assert report.items[0].effective_status == expected


@pytest.mark.asyncio
async def test_inclusive_endpoints_leap_day_and_open_lower_bound() -> None:
    days = [date(2028, 2, 27), date(2028, 2, 28), date(2028, 2, 29), date(2028, 3, 1), date(2028, 3, 2)]
    repo = _SpyRepository(
        [_cert(f"SYN-{d.isoformat()}", expiry=d) for d in days] + [_cert("SYN-OLD", expiry=date(1999, 1, 1))]
    )
    report = await _report(repo, expiry_from="2028-02-28", expiry_to="2028-03-01")
    assert _ids(report) == ["SYN-2028-02-28", "SYN-2028-02-29", "SYN-2028-03-01"]
    leap = await _report(repo, expiry_from="2028-02-29", expiry_to="2028-02-29")
    assert _ids(leap) == ["SYN-2028-02-29"]
    open_lower = await _report(repo, clock=_Clock(date(2028, 2, 28)))
    assert _ids(open_lower) == ["SYN-OLD", "SYN-2028-02-27", "SYN-2028-02-28"]
    assert open_lower.filter.expiry_from is None and open_lower.filter.expiry_to_requested is None


@pytest.mark.asyncio
async def test_from_after_resolved_to_is_a_422_with_resolution_details() -> None:
    repo = _SpyRepository([_cert("SYN-1", expiry=AS_OF)])
    err = await _report_error(repo, expiry_from=TOMORROW.isoformat())
    assert (err.code, err.status_code) == ("VALIDATION_ERROR", 422)
    detail = err.details["errors"][0]
    assert detail["field"] == "expiry_from" and detail["reason"] == "AFTER_EXPIRY_TO"
    assert detail["resolved_expiry_to"] == AS_OF.isoformat() and detail["expiry_to_is_default"] is True
    explicit = (await _report_error(repo, expiry_from="2026-05-02", expiry_to="2026-05-01")).details["errors"][0]
    assert explicit["resolved_expiry_to"] == "2026-05-01" and explicit["expiry_to_is_default"] is False
    assert repo.calls == []  # rejected before any read
    ok = await _report(repo, expiry_from=AS_OF.isoformat())
    assert _ids(ok) == ["SYN-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "mode=range", "mode=MISSING", "mode=", "effective_status=active", "effective_status=REPLACED",
        "effective_status=", "page=0", "page=-1", "page=x", "page_size=0", "page_size=201",
        "expiry_from=2026-1-5", "expiry_from=2026-01-01T00:00", "expiry_from=20260101",
        "expiry_to=2026-W01-1", "expiry_to=", "expiry_from=2026-01-01%0A", "expiry_to=2027-02-29",
        "expiry_to=2026-13-01", "expiry_from=%202026-01-01",
        "mode=MISSING_EXPIRY_DATE&expiry_from=2026-01-01",
        "mode=MISSING_EXPIRY_DATE&expiry_to=2026-01-01",
        "expiry_from=2026-06-02&expiry_to=2026-06-01",
    ],
)
async def test_invalid_queries_use_the_existing_validation_envelope(query: str) -> None:
    repo = _SpyRepository([_cert("SYN-1", expiry=AS_OF)])
    response = await _api(repo, f"{URL}?{query}", clock=_Clock())
    assert response.status_code == 422, query
    body = response.json()
    assert list(body) == ["error"] and body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["request_id"]
    for leaked in ("items", "total_items", "population", "data_issues", "SYN-1"):
        assert leaked not in response.text
    assert repo.calls == [] and repo.writes() == []


@pytest.mark.asyncio
async def test_valid_boundary_queries_and_filter_echo() -> None:
    repo = _SpyRepository([_cert("SYN-1", expiry=AS_OF), _cert("SYN-2", expiry=None)])
    clock = _Clock()
    body = (await _api(repo, f"{URL}?page_size=200&expiry_to=2028-02-29&effective_status=ACTIVE", clock=clock)).json()
    assert body["filter"] == {
        "mode": "RANGE", "expiry_from": None, "expiry_to_requested": "2028-02-29",
        "expiry_to_resolved": "2028-02-29", "expiry_to_is_default": False, "effective_status": "ACTIVE",
    }
    assert body["page_size"] == 200 and body["timezone"] == "Asia/Bangkok" and body["as_of_date"] == AS_OF.isoformat()
    missing = (await _api(repo, f"{URL}?mode=MISSING_EXPIRY_DATE", clock=clock)).json()
    assert missing["filter"] == {
        "mode": "MISSING_EXPIRY_DATE", "expiry_from": None, "expiry_to_requested": None,
        "expiry_to_resolved": None, "expiry_to_is_default": False, "effective_status": None,
    }
    assert [i["certificate_id"] for i in missing["items"]] == ["SYN-2"]
    assert missing["items"][0]["expiry_position"] == "NO_EXPIRY_DATE"
    default = (await _api(repo, URL, clock=clock)).json()
    assert default["page"] == 1 and default["page_size"] == 50
    assert default["filter"]["expiry_to_resolved"] == AS_OF.isoformat() and default["filter"]["expiry_to_is_default"] is True
    assert default["data_issues"]["issue_defect_counts_are_occurrences"] is True


# ---------------------------------------------------------------------------
# Ordering and paging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ordering_is_plain_string_with_read_index_tiebreak() -> None:
    d = date(2026, 5, 1)
    certs = [
        _cert("C-2", vid="V10", expiry=d),
        _cert("C-1", vid="V2", expiry=d),
        _cert("C-9", vid="V10", type_code="T-A", expiry=date(2026, 4, 1)),
        _cert("C-1", vid="V10", expiry=d, document_no="second-twin"),
        _cert("C-1", vid="V10", expiry=d, document_no="first-twin"),
        _cert("ก-1", vid="V10", expiry=d),
        _cert("C-3", vid="V10", type_code=None, expiry=d),
    ]
    repo = _SpyRepository(certs)
    report = await _report(repo, expiry_to="2026-12-31")
    assert [(i.expiry_date.isoformat(), i.vehicle_id, i.certificate_type_code, i.certificate_id, i.document_no) for i in report.items] == [
        ("2026-04-01", "V10", "T-A", "C-9", None),
        ("2026-05-01", "V10", None, "C-3", None),  # "" < "SYN-TYPE-A"
        ("2026-05-01", "V10", "SYN-TYPE-A", "C-1", "second-twin"),  # read_index order for twins
        ("2026-05-01", "V10", "SYN-TYPE-A", "C-1", "first-twin"),
        ("2026-05-01", "V10", "SYN-TYPE-A", "C-2", None),
        ("2026-05-01", "V10", "SYN-TYPE-A", "ก-1", None),
        ("2026-05-01", "V2", "SYN-TYPE-A", "C-1", None),
    ]
    missing_repo = _SpyRepository([_cert(c.certificate_id, vid=c.vehicle_id, type_code=c.certificate_type_code) for c in certs])
    missing = await _report(missing_repo, mode="MISSING_EXPIRY_DATE")
    assert [(i.vehicle_id, i.certificate_type_code, i.certificate_id) for i in missing.items] == [
        ("V10", None, "C-3"), ("V10", "SYN-TYPE-A", "C-1"), ("V10", "SYN-TYPE-A", "C-1"),
        ("V10", "SYN-TYPE-A", "C-2"), ("V10", "SYN-TYPE-A", "ก-1"), ("V10", "T-A", "C-9"),
        ("V2", "SYN-TYPE-A", "C-1"),
    ]


@pytest.mark.asyncio
async def test_stable_paging_over_more_than_200_records_and_out_of_range() -> None:
    certs = [
        _cert(f"SYN-{i:04d}", vid=f"SYN-VEH-{i % 7}", expiry=date(2026, 1, 1) + timedelta(days=i % 40))
        for i in range(450)
    ]
    repo = _SpyRepository(certs + [_cert("SYN-BAD", status="bad")])
    pages = [await _report(repo, expiry_to="2026-12-31", page=p, page_size=200) for p in (1, 2, 3)]
    seen = [i.certificate_id for page in pages for i in page.items]
    assert [len(p.items) for p in pages] == [200, 200, 50]
    assert len(seen) == len(set(seen)) == 450
    again = [await _report(repo, expiry_to="2026-12-31", page=p, page_size=200) for p in (1, 2, 3)]
    assert [_ids(p) for p in again] == [_ids(p) for p in pages]
    assert all(p.total_items == 450 for p in pages)
    beyond = await _report(repo, expiry_to="2026-12-31", page=4, page_size=200)
    assert beyond.items == [] and beyond.total_items == 450
    assert beyond.population == pages[0].population and beyond.complete is False
    response = await _api(repo, f"{URL}?expiry_to=2026-12-31&page=9&page_size=200", clock=_Clock())
    assert response.status_code == 200 and response.json()["items"] == [] and response.json()["total_items"] == 450


# ---------------------------------------------------------------------------
# Authorization, errors and zero writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["UNKNOWN", "GUEST"])
async def test_denied_request_reads_nothing(role: str) -> None:
    repo = _SpyRepository([_cert("SYN-1", expiry=AS_OF)])
    clock = _Clock()
    response = await _api(repo, f"{URL}?expiry_from=2026-01-01", headers={"X-Dev-Role": role}, clock=clock)
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "HTTP_ERROR" and "SYN-1" not in response.text
    assert repo.calls == [] and clock.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ADMIN", "MAINTENANCE", "SUPERVISOR", "TECHNICIAN", "DRIVER"])
async def test_every_can_view_role_is_allowed(role: str) -> None:
    repo = _SpyRepository([_cert("SYN-1", expiry=AS_OF)])
    response = await _api(repo, URL, headers={"X-Dev-Role": role}, clock=_Clock())
    assert response.status_code == 200 and response.json()["total_items"] == 1


@pytest.mark.asyncio
async def test_error_envelopes_carry_no_report_data() -> None:
    cases = [
        (RepositorySchemaError("vehicle_certificate", "MISSING_HEADERS", ("expiry_date",)), 500, "VEHICLE_CERTIFICATE_SCHEMA_INVALID"),
        (RepositoryError("Google Sheets reading failed: fake.json"), 503, "VEHICLE_CERTIFICATE_READ_FAILED"),
        (RuntimeError("boom secret"), 500, "INTERNAL_ERROR"),
    ]
    for exc, status_code, code in cases:
        response = await _api(_FailingRepository(exc), URL, clock=_Clock())
        assert response.status_code == status_code
        body = response.json()
        assert list(body) == ["error"] and body["error"]["code"] == code and body["error"]["request_id"]
        for leaked in ("items", "total_items", "population", "data_issues", "complete", "fake.json", "secret", "Traceback"):
            assert leaked not in response.text
        if code == "VEHICLE_CERTIFICATE_SCHEMA_INVALID":
            assert body["error"]["details"] == {"tab": "vehicle_certificate", "problem": "MISSING_HEADERS", "headers": ["expiry_date"]}
        else:
            assert body["error"]["details"] is None


def _zero_write_scenarios() -> dict[str, tuple[Callable[[], _SpyRepository], str, dict[str, str]]]:
    mixed = lambda: _SpyRepository([  # noqa: E731
        _cert("SYN-A", expiry=YESTERDAY), _cert("SYN-B", status="bad"), _cert("SYN-R", status=REPLACED, expiry=YESTERDAY),
    ])
    return {
        "success": (mixed, f"{URL}?expiry_to=2030-01-01", {}),
        "partial": (mixed, URL, {}),
        "empty": (lambda: _SpyRepository([]), URL, {}),
        "missing_mode": (mixed, f"{URL}?mode=MISSING_EXPIRY_DATE", {}),
        "out_of_range": (mixed, f"{URL}?page=50", {}),
        "validation": (mixed, f"{URL}?expiry_from=2031-01-01", {}),
        "denied": (mixed, URL, {"X-Dev-Role": "UNKNOWN"}),
        "schema_error": (lambda: _FailingRepository(RepositorySchemaError("vehicle_certificate", "TAB_MISSING")), URL, {}),
        "read_error": (lambda: _FailingRepository(RepositoryError("x")), URL, {}),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(_zero_write_scenarios()))
async def test_report_never_writes_or_uses_legacy_reads(scenario: str) -> None:
    factory, path, headers = _zero_write_scenarios()[scenario]
    repo = factory()
    before = repo.stored()
    await _api(repo, path, headers=headers, clock=_Clock())
    assert repo.writes() == []
    assert not any(c.startswith(_FORBIDDEN_READS) for c in repo.calls)
    assert set(repo.calls) <= {"read_vehicle_certificates_for_report"}
    assert len(repo.calls) <= 1
    assert repo.stored() == before


@pytest.mark.asyncio
async def test_stale_active_rows_stay_stored_active_after_the_report() -> None:
    repo = _SpyRepository([_cert("SYN-STALE", expiry=YESTERDAY)])
    report = await _report(repo)
    assert report.items[0].stored_status == "ACTIVE" and report.items[0].effective_status == "EXPIRED"
    assert report.items[0].flags == ["STORED_ACTIVE_PAST_EXPIRY"]
    assert repo.stored()[0]["certificate_status"] == ACTIVE and repo.writes() == []


# ---------------------------------------------------------------------------
# Characterization of the EXISTING per-vehicle certificate page API (the
# report's "ดูใบรับรองของรถคันนี้" destination). Separate from the report's
# zero-write tests; nothing legacy is changed to make these pass.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_characterize_existing_vehicle_list_reconciles_stale_active_rows_with_a_write(monkeypatch) -> None:
    import app.domain.vehicle_certificate_service as legacy

    monkeypatch.setattr(legacy, "bangkok_today", lambda: AS_OF)
    repo = _SpyRepository([
        _cert("SYN-STALE", vid="VEH-1046", expiry=YESTERDAY),
        _cert("SYN-OLD-REPLACED", vid="VEH-1046", status=REPLACED, expiry=date(2020, 1, 1)),
        _cert("SYN-TODAY", vid="VEH-1046", expiry=AS_OF),
    ])
    response = await _api(repo, "/api/v1/vehicles/VEH-1046/certificates")
    assert response.status_code == 200
    statuses = {c["certificate_id"]: c["certificate_status"] for c in response.json()}
    assert statuses == {"SYN-STALE": "EXPIRED", "SYN-OLD-REPLACED": "REPLACED", "SYN-TODAY": "ACTIVE"}
    assert repo.writes() == ["mark_vehicle_certificate_expired"]  # a read-side write (existing behavior)
    stored = {row["certificate_id"]: row["certificate_status"] for row in repo.stored()}
    assert stored["SYN-STALE"] == EXPIRED and stored["SYN-OLD-REPLACED"] == REPLACED


@pytest.mark.asyncio
async def test_characterize_existing_vehicle_list_missing_vehicle_is_404_before_reconciliation() -> None:
    repo = _SpyRepository([_cert("SYN-STALE", vid="SYN-NO-SUCH-VEHICLE", expiry=date(2020, 1, 1))])
    response = await _api(repo, "/api/v1/vehicles/SYN-NO-SUCH-VEHICLE/certificates")
    assert response.status_code == 404 and response.json()["error"]["code"] == "VEHICLE_NOT_FOUND"
    assert repo.calls == ["get_vehicle"] and repo.writes() == []
    assert repo.stored()[0]["certificate_status"] == ACTIVE


@pytest.mark.asyncio
async def test_characterize_existing_certificate_routes_are_not_capability_gated() -> None:
    """Existing gap (recorded, not changed by DEC 5): the per-vehicle list
    answers — and may write — for a caller without `can_view`."""
    repo = _SpyRepository([_cert("SYN-STALE", vid="VEH-1046", expiry=date(2020, 1, 1))])
    response = await _api(repo, "/api/v1/vehicles/VEH-1046/certificates", headers={"X-Dev-Role": "UNKNOWN"})
    assert response.status_code == 200
    assert repo.writes() == ["mark_vehicle_certificate_expired"]
    report = await _api(repo, URL, headers={"X-Dev-Role": "UNKNOWN"})
    assert report.status_code == 403


# ---------------------------------------------------------------------------
# Review finding (Batch 7D2): a non-finite alert_lead_days makes the UNCHANGED
# legacy `_certificate_alert_lead_days_from_cell` raise OverflowError. At the
# report's row-mapping boundary that is a row mapping defect (DEC 4), never a
# whole-report failure. Other exception types still propagate.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), 1e309, "inf", "-inf", "1e309"])
def test_legacy_alert_lead_days_helper_raises_overflow_unchanged(value) -> None:
    with pytest.raises(OverflowError):
        GoogleSheetsRepository._certificate_alert_lead_days_from_cell(value)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), 1e309, "inf", "-inf", "1e309"])
@pytest.mark.parametrize(
    ("status", "bucket"),
    [
        ("ACTIVE", "ISSUE_IN_SCOPE_DEFECT"),
        ("EXPIRED", "ISSUE_IN_SCOPE_DEFECT"),
        ("REPLACED", "EXCLUDED_REPLACED"),
        ("", "EXCLUDED_STATUS_BLANK"),
        ("Active", "ISSUE_UNKNOWN_STATUS"),
    ],
)
def test_overflowing_alert_lead_days_is_a_row_mapping_defect(value, status, bucket) -> None:
    row = _row(0, certificate_id="0042", certificate_status=status, alert_lead_days=value,
               expiry_date=TOMORROW.isoformat())
    assert (row.mapping_ok, row.certificate) == (False, None)
    assert row.certificate_id_text == "0042"
    assert classify_bucket(row) == bucket
    expected = ["UNMAPPABLE_ROW"] if status != "Active" else ["UNRECOGNIZED_STATUS", "UNMAPPABLE_ROW"]
    assert rpt.row_defects(row) == expected


@pytest.mark.parametrize("exc", [RuntimeError("fault"), KeyError("fault"), AttributeError("fault"), ZeroDivisionError()])
def test_non_row_value_mapper_failures_still_propagate(exc) -> None:
    def mapper(_: dict) -> VehicleCertificate:
        raise exc

    with pytest.raises(type(exc)):
        build_report_row(0, {"certificate_id": "SYN-1", "certificate_status": "REPLACED"}, mapper, PARSE, "")
