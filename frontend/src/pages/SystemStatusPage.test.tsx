import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SystemStatusPage } from './SystemStatusPage'

describe('SystemStatusPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/api/v1/health')) {
          return new Response(JSON.stringify({ status: 'ok', app_env: 'development' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        if (url.endsWith('/api/v1/readiness')) {
          return new Response(
            JSON.stringify({
              ready: true,
              repository_mode: 'mock',
              checks: [{ name: 'repository:mock', ready: true, reason: null }],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows loading then the resolved system status in Thai', async () => {
    render(<SystemStatusPage />)

    expect(screen.getByText('กำลังตรวจสอบสถานะระบบ...')).toBeInTheDocument()

    await waitFor(() => expect(screen.getByText('พร้อมใช้งาน')).toBeInTheDocument())
    expect(screen.getByText('mock')).toBeInTheDocument()
  })
})
