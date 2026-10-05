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

export async function apiPost<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  return performRequest<T>(path, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** multipart/form-data upload (e.g. inspection evidence/reference photos).
 * The browser sets the multipart boundary itself, so no Content-Type
 * header is set here. */
export async function apiUpload<T>(path: string, formData: FormData): Promise<ApiResult<T>> {
  return performRequest<T>(path, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body: formData,
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

/**
 * Phase 7 Batch 7O2b — the raw facts of a registry mutation (Outcome
 * Classification Addendum A.3). `json` is the parsed body when it is a JSON
 * object or array, otherwise null; nothing is validated or classified here
 * (that is the registry bookkeeping's job, `registryPending.ts`).
 */
export type MutationResponse =
  | { kind: 'http'; status: number; headerRequestId: string | null; json: unknown }
  | { kind: 'transport'; error: Error }

export const MUTATION_TIMEOUT_MS = 60_000

/**
 * Used ONLY by the registry mutation callers. Sends `X-Request-Id`, never
 * throws, never retries, and returns the status, the response `X-Request-Id`
 * header and the parsed JSON — for every status, success or not. A transport
 * failure or the client timeout (60 s) is `{ kind: 'transport' }`.
 * apiGet / apiPatch / apiPost / apiUpload and performRequest are unchanged.
 */
export async function apiMutation(
  path: string,
  method: 'PATCH' | 'POST',
  body: unknown,
  options: { requestId: string; timeoutMs?: number },
): Promise<MutationResponse> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? MUTATION_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Request-Id': options.requestId,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    const text = await response.text().catch(() => '')
    let json: unknown = null
    try {
      const parsed: unknown = text ? JSON.parse(text) : null
      json = typeof parsed === 'object' ? parsed : null
    } catch {
      json = null
    }
    return { kind: 'http', status: response.status, headerRequestId: response.headers.get('X-Request-Id'), json }
  } catch (cause) {
    return { kind: 'transport', error: cause instanceof Error ? cause : new Error('Network error') }
  } finally {
    clearTimeout(timer)
  }
}
