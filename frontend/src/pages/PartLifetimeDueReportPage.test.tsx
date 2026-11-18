import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PartLifetimeDueReportPage } from './PartLifetimeDueReportPage'

// R8 (R8-09) — fleet part-lifetime-due report page. Synthetic data only.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const REPORT = {
  status_filter: null, branch_id: null, page: 1, page_size: 20, total_vehicles: 3, vehicles_evaluated: 1,
  vehicles_out_of_scope: 2,
  items: [
    { vehicle_id: 'VEH-1048', machine_no: 'TC-14', target_type: 'PART_INSTANCE', target_id: 'PINST-1', part_id: 'PART-1',
      position_code: 'POS-A', status: 'DUE', rules: [{ status: 'DUE' }] },
    { vehicle_id: 'VEH-1048', machine_no: 'TC-14', target_type: 'POSITION_LIFETIME', target_id: 'PLT-1', part_id: 'PART-2',
      position_code: null, status: 'UNKNOWN', rules: [{ status: 'UNKNOWN' }] },
    { vehicle_id: 'VEH-1048', machine_no: 'TC-14', target_type: 'POSITION_LIFETIME', target_id: 'PLT-2', part_id: 'PART-3',
      position_code: null, status: 'NO_APPLICABLE_RULE', rules: [] },
  ],
}

function installApi(response: () => Response) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost')
    calls.push(`${url.pathname.replace('/api/v1', '')}${url.search}`)
    return response()
  }))
  return calls
}

const renderAt = (path = '/reports/part-lifetime-due') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <PartLifetimeDueReportPage />
    </MemoryRouter>,
  )

afterEach(() => vi.unstubAllGlobals())

describe('PartLifetimeDueReportPage', () => {
  it('shows UNKNOWN and "no applicable rule" as their own statuses and discloses out-of-scope vehicles', async () => {
    installApi(() => json(REPORT))
    renderAt()
    expect((await screen.findAllByText('ถึงกำหนด')).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('ยังยืนยันไม่ได้ (UNKNOWN)').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('ไม่มีกฎอายุที่ใช้กับรายการนี้').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/ไม่ได้ประเมิน 2 คัน/)).toBeInTheDocument()
    expect(screen.getByText(/ไม่ได้แปลว่าไม่ถึงกำหนด/)).toBeInTheDocument()
  })

  it('filters by status through the URL', async () => {
    const user = userEvent.setup()
    const calls = installApi(() => json(REPORT))
    renderAt()
    await screen.findAllByText('ถึงกำหนด')
    await user.selectOptions(screen.getByLabelText('สถานะ'), 'DUE')
    expect(calls).toContain('/reports/part-lifetime-due?page=1&page_size=20&status=DUE')
  })

  it('a 403 shows the permission state', async () => {
    installApi(() => json({ error: { code: 'HTTP_ERROR', message: 'x', details: null, request_id: 'r' } }, 403))
    renderAt()
    expect((await screen.findAllByText(/ไม่มีสิทธิ์/)).length).toBeGreaterThanOrEqual(1)
  })
})
