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
})
