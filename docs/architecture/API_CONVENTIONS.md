# API Conventions (Frozen — Phase 1)

These conventions are frozen after Phase 1 acceptance. Later phases must
extend them, not silently change them (see `docs/claude-prompts/web-api/00_README_EXECUTION_ORDER_EN.txt`,
"PHASE FREEZE RULE").

## Versioning

All Web/business API routes are served under:

```
/api/v1/
```

Device (ESP32) ingestion routes are logically separate from Web-user
routes and will get their own prefix when introduced (Phase 8), so the
final device contract can be aligned with the firmware project without
touching Web-facing routes.

## Error envelope

Every non-2xx JSON response uses this shape:

```json
{
  "error": {
    "code": "SOME_STABLE_CODE",
    "message": "human readable message",
    "details": { "...optional structured info": "..." },
    "request_id": "uuid-attached-to-this-request"
  }
}
```

- `code` is a stable, machine-readable identifier (e.g. `NOT_FOUND`,
  `VALIDATION_ERROR`, `INTERNAL_ERROR`). Frontend code may branch on it.
- `message` is safe to log; it is not guaranteed to be Thai — the frontend
  is responsible for mapping known codes to Thai user-facing text and
  falling back to a generic Thai message for unknown codes.
- `request_id` matches the `X-Request-Id` response header and should be
  shown to users when they report a problem.

## Pagination

Page-based, 1-indexed:

Request: `?page=1&page_size=20`

Response:

```json
{
  "items": [...],
  "page": 1,
  "page_size": 20,
  "total_items": 137
}
```

## Search / filter

Phase 1 defines the convention only (no searchable domain endpoints yet):
a free-text `q` query parameter plus explicit typed filter fields per
endpoint. No generic query DSL.

## Date / time

All timestamps are ISO-8601 strings in UTC (e.g. `2026-09-12T07:00:00Z`).
Backend stores/returns UTC; the frontend converts to local display time.
Domain events additionally distinguish `event_timestamp` (when it
happened) from `received_at` (when the backend ingested it) starting with
the phase that introduces IoT events.

## Stable IDs

IDs are opaque, backend/repository-assigned strings, prefixed by entity
type (e.g. `VEH-1046`, `DEV-0001`). They never change once assigned and
never derive from Google Sheets row position.

## Request / user context

Every request is assigned a `request_id` (returned via the `X-Request-Id`
header and embedded in error envelopes). `DEV_AUTH_MODE=true` attaches a
fixed development user (`dev-user`, role `ADMIN`) to every request so
downstream code can already depend on a `RequestContext` existing before
real authentication is implemented in the hardening phase.

## Repository / Storage abstraction

Web and domain/service code depend only on:

- `Repository` (`backend/app/repositories/base.py`)
- `StorageProvider` (`backend/app/storage/base.py`)

Concrete implementations (`MockRepository`, `GoogleSheetsRepository`,
`LocalFileStorageProvider`) are selected once, in
`backend/app/dependencies.py`, based on `DATA_REPOSITORY` /
`FILE_STORAGE_BACKEND`. No other module should import a concrete
implementation directly.

```
Thai Web Application
    -> Backend API (/api/v1)
    -> Domain / Service Layer
    -> Repository Interface
    -> MockRepository | GoogleSheetsRepository (prototype) | PostgreSQLRepository (future production)
```

Replacing Google Sheets with PostgreSQL later means adding a new
`Repository` implementation and switching `DATA_REPOSITORY=postgresql` —
it must not require rewriting Web workflows, domain/service logic, or API
routes.
