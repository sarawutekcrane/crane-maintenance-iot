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

    dev_auth_mode: bool = True

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
    def attachment_allowed_content_types_set(self) -> frozenset[str]:
        return frozenset(
            value.strip().lower()
            for value in self.attachment_allowed_content_types.split(",")
            if value.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
