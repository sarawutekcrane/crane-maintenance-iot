/**
 * Shared API client. Frozen in Phase 1 (see docs/architecture/API_CONVENTIONS.md):
 * - Web/business API is always called under `/api/v1/...` via the Vite dev proxy.
 * - Every non-2xx response is parsed into the shared error envelope shape.
 * - Callers get back a discriminated `ApiResult<T>` instead of a thrown
 *   generic error, so pages can render loading/empty/error states uniformly.
 */

export interface ApiErrorEnvelope {
  error: {
    code: string
    message: string
    details?: Record<string, unknown> | null
    request_id?: string | null
  }
}

export class ApiError extends Error {
  code: string
  details?: Record<string, unknown> | null
  requestId?: string | null
  status: number

  constructor(status: number, envelope: ApiErrorEnvelope) {
    super(envelope.error.message)
    this.name = 'ApiError'
    this.status = status
    this.code = envelope.error.code
    this.details = envelope.error.details
    this.requestId = envelope.error.request_id
  }
}

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError | Error }

const API_BASE = '/api/v1'

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  return (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof (value as { error?: unknown }).error === 'object'
  )
}

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  return performRequest<T>(path, { headers: { Accept: 'application/json' } })
}

export async function apiPatch<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  return performRequest<T>(path, {
    method: 'PATCH',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

async function performRequest<T>(path: string, init: RequestInit): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${API_BASE}${path}`, init)
    const responseBody: unknown = await response.json().catch(() => null)

    if (!response.ok) {
      if (isErrorEnvelope(responseBody)) {
        return { ok: false, error: new ApiError(response.status, responseBody) }
      }
      return {
        ok: false,
        error: new Error(`HTTP ${response.status}`),
      }
    }

    return { ok: true, data: responseBody as T }
  } catch (cause) {
    return {
      ok: false,
      error: cause instanceof Error ? cause : new Error('Network error'),
    }
  }
}
