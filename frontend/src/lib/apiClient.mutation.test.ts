import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiMutation } from './apiClient'

// Phase 7 Batch 7O2b — apiMutation exposes the raw facts the registry
// bookkeeping needs (Outcome Classification Addendum A.3, W-OC-07). It never
// throws, never retries, and leaves the other api functions unchanged (their
// existing tests run untouched).

const RID = '11111111-2222-4333-8444-555555555555'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('apiMutation', () => {
  it('sends X-Request-Id and the JSON body, and returns status, header and parsed JSON', async () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) =>
      new Response(JSON.stringify({ request_id: RID, changed: false }), {
        status: 200, headers: { 'Content-Type': 'application/json', 'X-Request-Id': RID },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const result = await apiMutation('/vehicles/V1/registration', 'PATCH', { registration_no: ' a ' }, { requestId: RID })
    expect(result).toEqual({ kind: 'http', status: 200, headerRequestId: RID, json: { request_id: RID, changed: false } })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/vehicles/V1/registration')
    expect(init.method).toBe('PATCH')
    expect(new Headers(init.headers).get('X-Request-Id')).toBe(RID)
    expect(JSON.parse(String(init.body))).toEqual({ registration_no: ' a ' })
  })

  it('returns error statuses as facts (no throw), including non-JSON bodies', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502 })))
    expect(await apiMutation('/x', 'POST', {}, { requestId: RID })).toEqual({ kind: 'http', status: 502, headerRequestId: null, json: null })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'X' } }), { status: 409 })))
    expect(await apiMutation('/x', 'POST', {}, { requestId: RID })).toMatchObject({ kind: 'http', status: 409, json: { error: { code: 'X' } } })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    expect(await apiMutation('/x', 'POST', {}, { requestId: RID })).toEqual({ kind: 'http', status: 204, headerRequestId: null, json: null })
    vi.stubGlobal('fetch', vi.fn(async () => new Response('"just a string"', { status: 200 })))
    expect(await apiMutation('/x', 'POST', {}, { requestId: RID })).toMatchObject({ kind: 'http', json: null })
  })

  it('a network error is a transport fact, and it is never retried', async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    vi.stubGlobal('fetch', fetchMock)
    const result = await apiMutation('/x', 'PATCH', {}, { requestId: RID })
    expect(result.kind).toBe('transport')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('the client timeout aborts the request and reports a transport fact', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      }),
    ))
    const result = await apiMutation('/x', 'PATCH', {}, { requestId: RID, timeoutMs: 10 })
    expect(result.kind).toBe('transport')
  })
})
