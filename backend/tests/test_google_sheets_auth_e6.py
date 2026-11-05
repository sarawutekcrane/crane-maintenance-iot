"""R4 E-6: Google Sheets credential selection (service-account key file, or
Application Default Credentials when no key file is configured).

Offline only: google-auth and gspread entry points are replaced with fakes
(or, for one case, a locally generated throwaway key that is never sent
anywhere). No live Google API, workbook or credential is used."""
from __future__ import annotations

import json

import google.auth
import gspread
import pytest
from google.auth.exceptions import DefaultCredentialsError
from google.oauth2 import service_account

from app.config import DataRepositoryMode, Settings
from app.repositories.base import RepositoryError
from app.repositories.google_sheets.client import _SHEETS_SCOPES, GoogleSheetsClient
from app.repositories.google_sheets.repository import GoogleSheetsRepository

SHEET_ID = "fake-sheet-id"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def settings(key_file: str = "") -> Settings:
    return Settings(data_repository=DataRepositoryMode.GOOGLE_SHEETS, google_sheet_id=SHEET_ID,
                    google_application_credentials=key_file)


class FakeSpreadsheet:
    def worksheets(self):
        return []


class FakeGspreadClient:
    def __init__(self, credentials):
        self.credentials = credentials
        self.opened: list[str] = []

    def open_by_key(self, key):
        self.opened.append(key)
        return FakeSpreadsheet()


@pytest.fixture
def calls(monkeypatch):
    """Record every credential source and the client gspread is given."""
    log: dict = {"key_file": [], "adc": [], "authorize": []}
    sa_creds, adc_creds = object(), object()

    def from_file(path, scopes=None):
        log["key_file"].append((path, list(scopes or [])))
        return sa_creds

    def default(scopes=None, **kwargs):
        log["adc"].append(list(scopes or []))
        return adc_creds, "fake-project"

    def authorize(credentials, *args, **kwargs):
        client = FakeGspreadClient(credentials)
        log["authorize"].append(client)
        return client

    monkeypatch.setattr(service_account.Credentials, "from_service_account_file", staticmethod(from_file))
    monkeypatch.setattr(google.auth, "default", default)
    monkeypatch.setattr(gspread, "authorize", authorize)
    log["sa_creds"], log["adc_creds"] = sa_creds, adc_creds
    return log


def test_e6_scope_is_unchanged_sheets_only() -> None:
    assert list(_SHEETS_SCOPES) == SCOPES


# 1. explicit key file -> existing service-account authentication
async def test_e6_01_an_explicit_key_file_uses_service_account_auth_and_never_adc(calls) -> None:
    client = GoogleSheetsClient(settings("C:/secure/key.json"))
    assert await client.verify_connectivity() == (True, None)
    assert calls["key_file"] == [("C:/secure/key.json", SCOPES)]
    assert calls["adc"] == []
    assert calls["authorize"][0].credentials is calls["sa_creds"]


# 2 + 3. no key file -> ADC, with exactly the intended scopes
async def test_e6_02_03_no_key_file_selects_adc_with_the_sheets_scope(calls) -> None:
    client = GoogleSheetsClient(settings(""))
    assert client.is_configured  # a blank key path is not "unconfigured" any more
    assert await client.verify_connectivity() == (True, None)
    assert calls["adc"] == [SCOPES]
    assert calls["key_file"] == []
    assert calls["authorize"][0].credentials is calls["adc_creds"]


# 4. an explicit but invalid key file fails and never falls back to ADC
@pytest.mark.parametrize("content", [None, "not json", json.dumps({"type": "service_account"})])
async def test_e6_04_an_invalid_explicit_key_file_fails_without_adc_fallback(monkeypatch, tmp_path, content) -> None:
    def adc_must_not_run(*args, **kwargs):
        raise AssertionError("ADC must never be tried after an explicit key file fails")

    monkeypatch.setattr(google.auth, "default", adc_must_not_run)
    path = tmp_path / "key.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    client = GoogleSheetsClient(settings(str(path)))
    with pytest.raises(RepositoryError, match="Google Sheets authentication failed"):
        client._get_client_sync()
    ok, message = await GoogleSheetsClient(settings(str(path))).verify_connectivity()
    assert ok is False and "authentication failed" in message


# 5. ADC unavailable fails safely: clear, no secret/path echoed, no Mock fallback
async def test_e6_05_missing_adc_fails_safely_without_leaking_details(monkeypatch) -> None:
    secret_path = "/home/someone/.config/gcloud/application_default_credentials.json"

    def no_adc(*args, **kwargs):
        raise DefaultCredentialsError(f"File {secret_path} was not found; token=ya29.SECRET")

    monkeypatch.setattr(google.auth, "default", no_adc)
    client = GoogleSheetsClient(settings(""))
    with pytest.raises(RepositoryError) as caught:
        client._get_client_sync()
    message = str(caught.value)
    assert "Application Default Credentials are unavailable (DefaultCredentialsError)" in message
    assert secret_path not in message and "ya29" not in message
    assert caught.value.__cause__ is None and caught.value.__suppress_context__  # original not chained
    ok, reported = await client.verify_connectivity()
    assert ok is False and "ya29" not in reported and secret_path not in reported
    repo = GoogleSheetsRepository(settings(""))  # the Sheets repository fails closed; it is never Mock
    with pytest.raises(RepositoryError, match="Application Default Credentials are unavailable"):
        await repo.get_vehicle("VEH-1046")


# 6. both paths drive the SAME client behaviour
@pytest.mark.parametrize("key_file", ["C:/secure/key.json", ""])
async def test_e6_06_both_paths_preserve_the_sheets_client_behaviour(calls, key_file) -> None:
    client = GoogleSheetsClient(settings(key_file))
    first = client._get_client_sync()
    assert client._get_client_sync() is first  # built once and cached, as before
    assert await client.verify_connectivity() == (True, None)
    assert first.opened == [SHEET_ID]  # the same spreadsheet opened by key
    assert len(calls["authorize"]) == 1


def test_e6_a_blank_sheet_id_is_still_not_configured_on_both_paths() -> None:
    for key_file in ("C:/secure/key.json", ""):
        client = GoogleSheetsClient(Settings(google_sheet_id="", google_application_credentials=key_file))
        assert client.is_configured is False
        with pytest.raises(RepositoryError, match="not configured"):
            client._require_configured_or_raise()


def test_e6_01b_a_real_local_test_key_builds_service_account_credentials_offline(monkeypatch, tmp_path) -> None:
    """Case A with a genuine (throwaway, locally generated) key: the existing
    google-auth path builds Credentials with the Sheets scope. No network."""
    rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    path = tmp_path / "test-key.json"
    path.write_text(json.dumps({"type": "service_account", "project_id": "test", "private_key_id": "0",
                                "private_key": pem, "client_email": "test@test.iam.gserviceaccount.com",
                                "client_id": "0", "token_uri": "https://oauth2.googleapis.com/token"}),
                    encoding="utf-8")
    monkeypatch.setattr(google.auth, "default", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ADC")))
    seen = []
    monkeypatch.setattr(gspread, "authorize", lambda credentials, *a, **k: seen.append(credentials) or object())
    GoogleSheetsClient(settings(str(path)))._get_client_sync()
    assert isinstance(seen[0], service_account.Credentials)
    assert list(seen[0].scopes) == SCOPES and seen[0].service_account_email == "test@test.iam.gserviceaccount.com"
