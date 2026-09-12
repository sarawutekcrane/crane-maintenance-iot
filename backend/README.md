# Backend — Crane Fleet Maintenance API

FastAPI + Pydantic + Uvicorn. Runs fully offline in mock mode.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DATA_REPOSITORY=mock   # or google_sheets (see below)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- OpenAPI docs: http://127.0.0.1:8000/docs
- Health: `GET /api/v1/health`
- Readiness: `GET /api/v1/readiness`

## Tests

```bash
DATA_REPOSITORY=mock DEV_AUTH_MODE=true APP_ENV=development python -m pytest
```

## Structure

```
app/
  main.py              FastAPI app factory
  config.py            Environment-based settings (frozen variable names)
  context.py           Request-id + RequestContext middleware
  errors.py            Shared error envelope + exception handlers
  dependencies.py       Composition root: picks Repository/StorageProvider
                        implementation based on config
  api/v1/               Web-facing routes, versioned under /api/v1
  domain/               Shared conventions (pagination, page params, ...)
  repositories/
    base.py             Repository interface
    mock/                In-memory implementation (no external deps)
    google_sheets/       Base adapter (connectivity/config check only;
                          domain tables are added starting Phase 2)
  storage/
    base.py             StorageProvider interface
    local.py             LocalFileStorageProvider (./data/uploads)
tests/                  pytest suite (mock mode, no network required)
```

See `docs/architecture/API_CONVENTIONS.md` for the frozen conventions this
structure implements.
