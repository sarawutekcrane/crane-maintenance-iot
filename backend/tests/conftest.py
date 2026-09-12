from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATA_REPOSITORY", "mock")
os.environ.setdefault("DEV_AUTH_MODE", "true")
os.environ.setdefault("APP_ENV", "development")


@pytest.fixture
def temp_upload_dir() -> Iterator[str]:
    path = tempfile.mkdtemp(prefix="crane-uploads-test-")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
async def client() -> Iterator[AsyncClient]:
    from app.config import get_settings
    from app.dependencies import reset_dependency_cache
    from app.main import create_app

    get_settings.cache_clear()
    reset_dependency_cache()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    reset_dependency_cache()
    get_settings.cache_clear()
