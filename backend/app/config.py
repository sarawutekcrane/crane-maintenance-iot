"""Application configuration loaded from environment variables.

Frozen in Phase 1: the set of variable names and the DATA_REPOSITORY /
FILE_STORAGE_BACKEND mode values. Later phases add new variables but must
not repurpose these names.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataRepositoryMode(str, Enum):
    MOCK = "mock"
    GOOGLE_SHEETS = "google_sheets"
    POSTGRESQL = "postgresql"


class FileStorageBackend(str, Enum):
    LOCAL = "local"


class RegistryDataContext(str, Enum):
    """Phase 7 Batch 7O2a (contract Final Rev2 §8.1, E7): which rows of the
    registry history tabs are in scope. TEST: every row is test scope; REAL:
    only rows flagged FALSE, and any TRUE/blank row fails closed."""

    TEST = "TEST"
    REAL = "REAL"


# Core Demo Fixes Delta REV06 section 11 (P0 — dev auth must fail closed):
# the independent REV05 audit found that gating dev-header actor spoofing
# on `APP_ENV == "production"` alone is insufficient — an unset, misspelled,
# or otherwise-unrecognized APP_ENV value (e.g. "staging", a typo) left
# spoofing enabled by default. `DEV_AUTH_MODE` now defaults to False (see
# `Settings.dev_auth_mode` below) and, even when explicitly set True, only
# takes effect inside one of these clearly recognized non-production
# environments — never merely "not literally production".
DEV_AUTH_ALLOWED_ENVIRONMENTS = frozenset({"development", "local", "test"})


MOCK_FIXTURE_PROFILE_UAT_R8 = "uat_r8"
# R8 PRE-UAT H1-DIRECT (Owner source approval Gate A, 2026-11-19): TEST-only hosted identity proxy.
TEST_IDENTITY_PROXY_OFF = "off"
TEST_IDENTITY_PROXY_GOOGLE_IAP = "google_iap"


class Settings(BaseSettings):
    # hide_input_in_errors (Gate A, 2026-11-19): a refused configuration never echoes setting values
    # (identity map digests, credentials paths) into the startup error / logs.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      hide_input_in_errors=True)

    app_env: str = "development"

    frontend_port: int = 5173
    backend_port: int = 8000

    data_repository: DataRepositoryMode = DataRepositoryMode.MOCK

    public_base_url: str = "http://127.0.0.1:5173"

    google_sheet_id: str = ""
    google_application_credentials: str = ""

    file_storage_backend: FileStorageBackend = FileStorageBackend.LOCAL
    local_upload_dir: str = "./data/uploads"

    # REV06 section 11: fails closed by default — dev-header actor spoofing
    # (`X-Dev-Role`/`X-Dev-User-Id`) is OFF unless explicitly turned on, and
    # even then only takes effect inside a recognized dev/test APP_ENV (see
    # `dev_auth_effective` below). Never rely on this flag alone.
    dev_auth_mode: bool = False

    log_level: str = "INFO"

    # Attachment upload validation (Phase 3 correction — see
    # inspection_service.py). These are LOCAL-DEVELOPMENT DEFAULTS ONLY,
    # not a production policy: OPEN_DECISIONS_REGISTER_EN.txt M07 (file
    # upload limits/MIME/malware-scanning policy) remains unresolved.
    # Configurable via environment variables so an explicitly-approved
    # production policy can replace these values without a code change.
    attachment_max_size_bytes: int = 10 * 1024 * 1024  # 10 MB, dev-only default
    attachment_allowed_content_types: str = "image/jpeg,image/png,image/webp,image/gif"

    # Phase 7 Batch 7O2a (contract Final Rev2 §8.1, E7). Mock mode is always
    # TEST. In google_sheets mode an unset value makes ONLY the new registry
    # endpoints answer 503 REGISTRY_DATA_CONTEXT_NOT_CONFIGURED; startup and
    # every existing route are unaffected. REAL with mock is refused below.
    # REGISTRY_TEST_BATCH_ID labels rows written in TEST (used from 7O2b on).
    registry_data_context: RegistryDataContext | None = None
    registry_test_batch_id: str = ""

    # Access Management (Owner-approved Mock implementation): when True, every
    # functional capability comes ONLY from per-employee grants recorded in the
    # access event log; the provisional development role table grants nothing
    # operational (see app.domain.access_management). Mock only and never in
    # production: the validator below refuses any other combination, so
    # production activation stays blocked until real login (M01) exists.
    access_management_mode: bool = False

    # R6 A-4 (Owner decision: ON, TEST ONLY): an in-memory, explicitly fake
    # verified IoT meter source for part lifetime counters, so Mock/TEST browser
    # acceptance can show verified numbers. Unset -> effective only for
    # DATA_REPOSITORY=mock (always the TEST context) in a recognized
    # non-production environment; True outside that combination is refused by
    # the validator below; False disables it. It never feeds R4 PM Due and holds
    # only readings a TEST caller explicitly records.
    part_test_meter_source: bool | None = None

    # R8 PRE-UAT Whole-Web Completion (Owner source approval Rev 1, 2026-11-18):
    # - MOCK_FIXTURE_PROFILE: "" (default, unchanged seed) or "uat_r8" — one isolated,
    #   deterministic synthetic TEST fixture profile (ids prefixed UAT8-) added to the
    #   in-memory Mock seed. Mock + recognized non-production APP_ENV only.
    # - PM_MASTER_TEST_PROFILE: wires a TEST-local PM Master store whose actions are
    #   authorized only by per-employee TEST grants (DEC-R4-TASK010-OPEN005-TEST-AUTH-
    #   20261106). Mock + Access Management mode + recognized non-production APP_ENV
    #   only. Off by default: the application keeps `deny_unproven_master_authority`
    #   for everyone (ADMIN and can_manage_pm included) and every PM Due read stays
    #   MASTER_NOT_ACTIVE, exactly as before.
    mock_fixture_profile: str = ""
    pm_master_test_profile: bool = False

    # R8 PRE-UAT H1-DIRECT (Owner source approval Gate A, 2026-11-19): a short-lived Cloud Run TEST
    # service behind Direct IAP. TEST_IDENTITY_PROXY=google_iap makes every request's identity come ONLY
    # from a verified IAP signed assertion mapped (by email digest) to one synthetic TEST employee
    # (app.domain.test_identity_proxy); X-Dev-* and unsigned IAP headers are never read. Off by default;
    # the validator below allows it only with the exact Mock/TEST/Access Management/uat_r8 profile.
    # TEST_SPA_DIR (proxy mode only) serves the built frontend on the same origin.
    test_identity_proxy: str = TEST_IDENTITY_PROXY_OFF
    test_iap_audience: str = ""
    test_identity_map: str = ""
    test_spa_dir: str = ""

    # R2 Batch R2f-h4 B6 Rev2 (owner final decision: Technician V2 ONLY): the
    # former TECHNICIAN_ASSIGNMENT_V2_ENABLED cutover setting is removed. Every
    # new Repair / PM work order is a TECHNICIAN_V2 job; there is no ON/OFF
    # mode and no legacy creation. A leftover environment variable of that
    # name is ignored (`extra="ignore"`) and changes nothing.

    @model_validator(mode="after")
    def _registry_context_fails_closed(self) -> "Settings":
        if (
            self.data_repository == DataRepositoryMode.MOCK
            and self.registry_data_context == RegistryDataContext.REAL
        ):
            raise ValueError(
                "REGISTRY_DATA_CONTEXT=REAL is not allowed with DATA_REPOSITORY=mock: "
                "mock data is synthetic and is always the TEST context."
            )
        if self.access_management_mode and (
            self.data_repository != DataRepositoryMode.MOCK or self.is_production
        ):
            raise ValueError(
                "ACCESS_MANAGEMENT_MODE is Mock-only: it requires DATA_REPOSITORY=mock and a non-production "
                "APP_ENV (no access-management persistence or production login exists yet)."
            )
        if self.part_test_meter_source is True and (
            self.data_repository != DataRepositoryMode.MOCK or self.is_production
            or not self.is_recognized_dev_environment
        ):
            raise ValueError(
                "PART_TEST_METER_SOURCE is TEST-only: it requires DATA_REPOSITORY=mock (always the TEST context) "
                "and a recognized non-production APP_ENV; a REAL context can never obtain fake meter readings."
            )
        if self.mock_fixture_profile not in ("", MOCK_FIXTURE_PROFILE_UAT_R8):
            raise ValueError(f"MOCK_FIXTURE_PROFILE must be empty or '{MOCK_FIXTURE_PROFILE_UAT_R8}'.")
        if self.mock_fixture_profile and (
            self.data_repository != DataRepositoryMode.MOCK or self.is_production
            or not self.is_recognized_dev_environment
        ):
            raise ValueError(
                "MOCK_FIXTURE_PROFILE is TEST-only: it requires DATA_REPOSITORY=mock and a recognized "
                "non-production APP_ENV."
            )
        if self.pm_master_test_profile and (
            self.data_repository != DataRepositoryMode.MOCK or self.is_production
            or not self.is_recognized_dev_environment or not self.access_management_mode
        ):
            raise ValueError(
                "PM_MASTER_TEST_PROFILE is TEST-only: it requires DATA_REPOSITORY=mock, ACCESS_MANAGEMENT_MODE=true "
                "and a recognized non-production APP_ENV (the application default denies every Master action)."
            )
        self._identity_proxy_fails_closed()
        return self

    def _identity_proxy_fails_closed(self) -> None:
        mode = self.test_identity_proxy.strip().lower()
        if mode not in (TEST_IDENTITY_PROXY_OFF, TEST_IDENTITY_PROXY_GOOGLE_IAP):
            raise ValueError("TEST_IDENTITY_PROXY must be 'off' or 'google_iap'.")
        if mode == TEST_IDENTITY_PROXY_OFF:
            if self.test_iap_audience or self.test_identity_map or self.test_spa_dir:
                raise ValueError(
                    "TEST_IAP_AUDIENCE / TEST_IDENTITY_MAP / TEST_SPA_DIR are used only with TEST_IDENTITY_PROXY=google_iap."
                )
            return
        from app.domain.test_identity_proxy import CLOUD_RUN_AUDIENCE_RE, parse_identity_map

        if not (
            self.app_env.strip().lower() == "test"
            and self.data_repository == DataRepositoryMode.MOCK
            and not self.dev_auth_mode
            and self.access_management_mode
            and self.mock_fixture_profile == MOCK_FIXTURE_PROFILE_UAT_R8
            and self.pm_master_test_profile
            and not self.google_sheet_id
            and not self.google_application_credentials
            and self.registry_data_context is None
        ):
            raise ValueError(
                "TEST_IDENTITY_PROXY=google_iap is TEST-only: it requires APP_ENV=test, DATA_REPOSITORY=mock, "
                "DEV_AUTH_MODE=false, ACCESS_MANAGEMENT_MODE=true, MOCK_FIXTURE_PROFILE=uat_r8, "
                "PM_MASTER_TEST_PROFILE=true and no GOOGLE_SHEET_ID, credentials or REGISTRY_DATA_CONTEXT."
            )
        if not CLOUD_RUN_AUDIENCE_RE.fullmatch(self.test_iap_audience):
            raise ValueError(
                "TEST_IAP_AUDIENCE must be the Cloud Run Direct IAP audience "
                "/projects/PROJECT_NUMBER/locations/REGION/services/SERVICE_NAME."
            )
        parse_identity_map(self.test_identity_map)

    @property
    def identity_proxy_enabled(self) -> bool:
        """True only in the validated TEST hosted mode (Direct IAP signed identity)."""
        return self.test_identity_proxy.strip().lower() == TEST_IDENTITY_PROXY_GOOGLE_IAP

    @property
    def part_test_meter_source_effective(self) -> bool:
        """R6 A-4: True only for mock (TEST) in a recognized non-production
        environment, unless explicitly disabled."""
        if self.part_test_meter_source is False:
            return False
        return (self.data_repository == DataRepositoryMode.MOCK and not self.is_production
                and self.is_recognized_dev_environment and self.registry_context_effective == "TEST")

    @property
    def registry_context_effective(self) -> str | None:
        """The registry data context in force: always "TEST" in mock mode,
        otherwise the configured value, or None when unset."""
        if self.data_repository == DataRepositoryMode.MOCK:
            return RegistryDataContext.TEST.value
        return self.registry_data_context.value if self.registry_data_context else None

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def is_recognized_dev_environment(self) -> bool:
        """True only for one of the explicitly-approved local/dev/test
        APP_ENV values (REV06 section 11) — never a stand-in for
        `not is_production`. An unset/misspelled/unknown value (including
        "staging" or any typo) is NOT recognized and therefore fails
        closed, exactly like production."""
        return self.app_env.strip().lower() in DEV_AUTH_ALLOWED_ENVIRONMENTS

    @property
    def dev_auth_effective(self) -> bool:
        """The actual, fail-closed dev-auth gate every request-handling
        code path must use instead of the raw `dev_auth_mode` flag (REV06
        section 11). `DEV_AUTH_MODE=true` alone is never sufficient — it
        only takes effect inside a recognized local/development/test
        environment; `app.main.create_app` additionally refuses to even
        start the process when `dev_auth_mode` is True outside a
        recognized environment, so this can never silently diverge from
        what actually started serving requests."""
        return self.dev_auth_mode and self.is_recognized_dev_environment

    @property
    def attachment_allowed_content_types_set(self) -> frozenset[str]:
        return frozenset(
            value.strip().lower()
            for value in self.attachment_allowed_content_types.split(",")
            if value.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
