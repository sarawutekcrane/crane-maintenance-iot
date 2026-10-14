import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App shell', () => {
  it('renders the Thai navigation and home page by default', () => {
    render(
      <BrowserRouter>
        <App />
      </BrowserRouter>,
    )

    expect(screen.getAllByText('ระบบบำรุงรักษาเครน').length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: 'ยินดีต้อนรับ' })).toBeInTheDocument()
  })

  describe('Phase 7 Batch 7B2 route', () => {
    afterEach(() => {
      vi.unstubAllGlobals()
      window.history.pushState({}, '', '/')
    })

    it('renders the fleet status dashboard at /dashboard and leaves the home page unchanged', async () => {
      const paths: string[] = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL) => {
          const path = new URL(String(input), 'http://localhost').pathname
          paths.push(path)
          const body =
            path === '/api/v1/dashboard/fleet-status'
              ? {
                  population: 'VEHICLE_MASTER_VALIDATED_RECORDS',
                  vehicle_total: 1,
                  status_counts: { WORKING: 1, READY: 0, MAINTENANCE: 0, OUT_OF_SERVICE: 0, LONG_TERM_PARKING: 0 },
                }
              : { user_id: 'dev-user', roles: ['ADMIN'], capabilities: [] }
          return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
        }),
      )
      window.history.pushState({}, '', '/dashboard')
      render(
        <BrowserRouter>
          <App />
        </BrowserRouter>,
      )

      expect(screen.getByRole('heading', { name: 'ภาพรวมกองรถ' })).toBeInTheDocument()
      expect(await screen.findByText('รถในทะเบียนทั้งหมด')).toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: 'ยินดีต้อนรับ' })).not.toBeInTheDocument()
      expect(paths.filter((p) => p === '/api/v1/dashboard/fleet-status')).toHaveLength(1)
    })
  })

  // R2 Batch R2f-h4 B5 — retired B4 /v2 bookmarks only redirect (a navigation; no request but reads).
  describe('B5 /v2 bookmark redirects', () => {
    afterEach(() => {
      vi.unstubAllGlobals()
    })

    it.each([
      ['/v2/repairs/RPR-SYN-1', '/repairs/RPR-SYN-1'],
      ['/v2/pm/work-orders/PMWO-SYN-1', '/pm/work-orders/PMWO-SYN-1'],
      ['/v2/vehicle/VEH-SYN-1/repairs/new', '/vehicle/VEH-SYN-1/repairs/new'],
      ['/v2/equipment/EQP-SYN-1/repairs/new', '/equipment/EQP-SYN-1/repairs/new'],
      ['/v2/vehicle/VEH-SYN-1/pm', '/vehicle/VEH-SYN-1/pm'],
      ['/v2/equipment/EQP-SYN-1/pm', '/equipment/EQP-SYN-1/pm'],
      ['/v2/my-work', '/my-work'],
      ['/v2/waiting-assignment', '/waiting-assignment'],
      ['/v2', '/'],
      ['/v2/anything-else', '/'],
    ])('%s → %s', async (from, to) => {
      const methods: string[] = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
          methods.push(init?.method ?? 'GET')
          return new Response(JSON.stringify({ error: { code: 'X', message: 'x' } }), { status: 500, headers: { 'Content-Type': 'application/json' } })
        }),
      )
      window.history.pushState({}, '', from)
      render(
        <BrowserRouter>
          <App />
        </BrowserRouter>,
      )
      await screen.findAllByText('ระบบบำรุงรักษาเครน')
      expect(window.location.pathname).toBe(to)
      expect(methods.every((m) => m === 'GET')).toBe(true)
      window.history.pushState({}, '', '/')
    })
  })
})
