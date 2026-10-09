import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NavBar } from '../components/NavBar'
import { CapabilitiesProvider } from '../lib/capabilities'
import { DepartmentDetailPage } from './DepartmentDetailPage'
import { DepartmentListPage } from './DepartmentListPage'

/** R2 Batch R2e — department list / detail / lifecycle UI (mock data only; the
 * live department_master tab does not exist). */

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const departments = {
  items: [
    { department_id: 'DEPT-SYN-001', department_name_th: 'แผนกหนึ่ง (สังเคราะห์)', is_active: true },
    { department_id: 'DEPT-SYN-002', department_name_th: 'แผนกสอง (สังเคราะห์)', is_active: false },
  ],
  page: 1,
  page_size: 50,
  total_items: 2,
}

function stub(me: string[], options: { list?: Response; post?: () => Response } = {}) {
  const fn = vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return jsonResponse({ user_id: 'dev-user', roles: [], capabilities: me })
    if (init?.method === 'POST') return options.post ? options.post() : jsonResponse({ changed: true })
    if (url.includes('/lifecycle-history')) {
      return jsonResponse({ entity_id: 'DEPT-SYN-002', current_state: false, latest_history_state: null,
        lifecycle_consistency: 'NO_HISTORY', events: [] })
    }
    if (url.includes('/departments/')) return jsonResponse(departments.items[1])
    return options.list ?? jsonResponse(departments)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

function renderAt(path: string) {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/departments" element={<DepartmentListPage />} />
          <Route path="/departments/:departmentId" element={<DepartmentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

describe('Department pages (R2E-52/53/59)', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('lists departments with distinct ids and keeps inactive ones visible', async () => {
    stub(['can_view'])
    renderAt('/departments')
    expect((await screen.findByText('DEPT-SYN-001')).tagName).toBe('CODE')
    expect(screen.getByText('ปิดใช้งาน')).toBeInTheDocument()
  })

  it('shows a missing department source as data unavailable, never as an empty list', async () => {
    stub(['can_view'], { list: jsonResponse({ error: { code: 'DEPARTMENT_MASTER_SCHEMA_INVALID', message: 'x' } }, 500) })
    renderAt('/departments')
    expect(await screen.findByText('ข้อมูลแผนกยังไม่พร้อมใช้งานในระบบ (ไม่ใช่รายการว่าง)')).toBeInTheDocument()
    expect(screen.queryByText('ไม่พบแผนก')).toBeNull()
  })

  it('reactivates an inactive department with a required reason and the boolean expectation', async () => {
    const fn = stub(['can_view', 'can_manage_department'])
    renderAt('/departments/DEPT-SYN-002')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'เปิดใช้งานอีกครั้ง' }))
    expect(screen.getByRole('button', { name: 'ยืนยันเปิดใช้งานอีกครั้ง' })).toBeDisabled()
    await user.type(screen.getByLabelText('เหตุผล (จำเป็น)'), 'เปิดอีกครั้ง')
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปิดใช้งานอีกครั้ง' }))
    await waitFor(() => expect(fn.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true))
    const [url, init] = fn.mock.calls.find(([, i]) => i?.method === 'POST')!
    expect(String(url)).toBe('/api/v1/departments/DEPT-SYN-002/reactivations')
    expect(JSON.parse(String(init?.body))).toEqual({ expected_is_active: false, reason_th: 'เปิดอีกครั้ง' })
  })

  it('the personnel capability alone shows no department controls', async () => {
    stub(['can_view', 'can_manage_personnel'])
    renderAt('/departments/DEPT-SYN-002')
    expect(await screen.findByText('สถานะปัจจุบัน:')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'เปิดใช้งานอีกครั้ง' })).toBeNull()
  })
})

describe('NavBar organisation masters (R2E-51/52)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('offers personnel and departments to can_view', async () => {
    stub(['can_view'])
    render(
      <CapabilitiesProvider>
        <MemoryRouter>
          <NavBar />
        </MemoryRouter>
      </CapabilitiesProvider>,
    )
    expect(await screen.findByRole('link', { name: 'บุคลากร' })).toHaveAttribute('href', '/personnel')
    expect(screen.getByRole('link', { name: 'แผนก' })).toHaveAttribute('href', '/departments')
  })
})
