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

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
