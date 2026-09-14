"""Application configuration loaded from environment variables.

Frozen in Phase 1: the set of variable names and the DATA_REPOSITORY /
FILE_STORAGE_BACKEND mode values. Later phases add new variables but must
not repurpose these names.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DataRepositoryMode(str, Enum):
    MOCK = "mock"
    GOOGLE_SHEETS = "google_sheets"
    POSTGRESQL = "postgresql"


class FileStorageBackend(str, Enum):
    LOCAL = "local"


# Core Demo Fixes Delta REV06 section 11 (P0 — dev auth must fail closed):
# the independent REV05 audit found that gating dev-header actor spoofing
# on `APP_ENV == "production"` alone is insufficient — an unset, misspelled,
# or otherwise-unrecognized APP_ENV value (e.g. "staging", a typo) left
# spoofing enabled by default. `DEV_AUTH_MODE` now defaults to False (see
# `Settings.dev_auth_mode` below) and, even when explicitly set True, only
# takes effect inside one of these clearly recognized non-production
# environments — never merely "not literally production".
DEV_AUTH_ALLOWED_ENVIRONMENTS = frozenset({"development", "local", "test"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
