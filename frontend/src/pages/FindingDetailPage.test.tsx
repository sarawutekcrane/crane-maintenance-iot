import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { FindingDetailPage } from './FindingDetailPage'
import { FindingFollowupPage } from './FindingFollowupPage'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const MANAGER = { user_id: 'USR-MGR', roles: ['MAINTENANCE_MANAGER'], capabilities: ['can_view', 'can_manage_repair', 'can_close_repair', 'can_manage_finding_repair'] }
const MAINTENANCE = { user_id: 'USR-M', roles: ['MAINTENANCE'], capabilities: ['can_view', 'can_manage_repair', 'can_close_repair'] }

function finding(overrides: Record<string, unknown> = {}) {
  return {
    finding_id: 'FND-0001', inspection_id: 'INS-0001', result_id: 'RES-0001', asset_type: 'VEHICLE', asset_id: 'VEH-1046',
    item_title: 'รายการตรวจสอบตัวอย่างที่ 1', is_critical: false, status: 'OPEN', created_at: '2026-10-01T01:00:00Z',
    item_key: 'KEY-1', end_reason: null, ended_at: null, ended_by: null, end_note: null, ended_inspection_id: null,
    ended_repair_id: null, previous_finding_id: null,
    observations: [
      { inspection_id: 'INS-0001', result_id: 'RES-0001', result: 'FAIL', remark: 'น้ำมันรั่ว', inspection_date: '2026-10-01', observed_at: '2026-10-01T01:00:00Z' },
      { inspection_id: 'INS-0002', result_id: 'RES-0009', result: 'FAIL', remark: 'ยังรั่ว', inspection_date: '2026-10-02', observed_at: '2026-10-02T01:00:00Z' },
    ],
    ...overrides,
  }
}

function stub(me: unknown, detail: unknown, onPost?: (url: string, body: unknown) => Response) {
  const posts: { url: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return json(me)
    if (init?.method === 'POST') {
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
      posts.push({ url, body })
      return onPost ? onPost(url, body) : json({}, 500)
    }
    if (url.includes('/findings/follow-up')) return json(detail)
    if (url.includes('/findings/')) return json(detail)
    throw new Error(`Unexpected fetch ${url}`)
  }))
  return posts
}

function renderAt(path: string) {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/findings/follow-up" element={<FindingFollowupPage />} />
          <Route path="/findings/:findingId" element={<FindingDetailPage />} />
          <Route path="/repairs/:repairId" element={<p>repair page</p>} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

describe('FindingDetailPage (R3)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the dated observations and lets the manager open a round from the Finding', async () => {
    const user = userEvent.setup()
    const posts = stub(MANAGER, { finding: finding(), repairs: [], followup_group: 'AWAITING_REPAIR_DECISION' },
      () => json({ repair: { repair_id: 'RPR-0009' }, actions: [], parts: [] }))
    renderAt('/findings/FND-0001')
    await waitFor(() => expect(screen.getByTestId('finding-observations')).toHaveTextContent('ยังรั่ว'))
    expect(screen.getByTestId('finding-status')).toHaveTextContent('รอพิจารณาเปิดงานซ่อม')
    await user.click(await screen.findByRole('button', { name: 'เปิดใบงานซ่อมจากรายการนี้' }))
    await waitFor(() => expect(screen.getByText('repair page')).toBeInTheDocument())
    expect(posts[0]).toMatchObject({ url: '/api/v1/repairs', body: { source_type: 'FINDING', source_id: 'FND-0001' } })
  })

  it('MAINTENANCE without the Finding authority sees no management controls', async () => {
    stub(MAINTENANCE, { finding: finding(), repairs: [], followup_group: 'AWAITING_REPAIR_DECISION' })
    renderAt('/findings/FND-0001')
    await waitFor(() => expect(screen.getByTestId('finding-observations')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'เปิดใบงานซ่อมจากรายการนี้' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ยุติการติดตาม' })).not.toBeInTheDocument()
  })

  it('termination needs a reason; an ENDED Finding never claims a verified repair', async () => {
    const user = userEvent.setup()
    const ended = finding({ status: 'ENDED', end_reason: 'MANUAL_TERMINATION', end_note: 'เลิกใช้รายการ', ended_at: '2026-10-03T01:00:00Z' })
    const posts = stub(MANAGER, { finding: finding(), repairs: [], followup_group: 'AWAITING_REPAIR_DECISION' },
      () => json({ finding: ended, repairs: [], followup_group: null }))
    renderAt('/findings/FND-0001')
    await user.click(await screen.findByRole('button', { name: 'ยุติการติดตาม' }))
    expect(screen.getByRole('alert')).toHaveTextContent('กรุณาระบุเหตุผลในการยุติการติดตาม')
    expect(posts).toHaveLength(0)
    await user.type(screen.getByLabelText('เหตุผลในการยุติการติดตาม (จำเป็น)'), 'เลิกใช้รายการ')
    await user.click(screen.getByRole('button', { name: 'ยุติการติดตาม' }))
    await waitFor(() => expect(screen.getByTestId('finding-end-reason')).toHaveTextContent('ยุติการติดตามโดยผู้มีสิทธิ์'))
    expect(screen.getByText(/ไม่ใช่การยืนยันว่าแก้ไขสำเร็จ/)).toBeInTheDocument()
    expect(posts[0].body).toEqual({ reason: 'เลิกใช้รายการ' })
  })

  it('an episode ended by the lead completion shows the Owner wording and the OPEN round awaiting closure', async () => {
    stub(MANAGER, {
      finding: finding({ status: 'ENDED', end_reason: 'TECHNICIAN_COMPLETION_SUBMITTED', ended_repair_id: 'RPR-0001' }),
      repairs: [{ repair_id: 'RPR-0001', status: 'OPEN', opened_at: '2026-10-01T02:00:00Z', closed_at: null,
                  completion_submitted_at: '2026-10-02T09:00:00Z', cancelled_at: null }],
      followup_group: null,
    })
    renderAt('/findings/FND-0001')
    await waitFor(() => expect(screen.getByTestId('finding-end-reason')).toHaveTextContent('สิ้นสุดรอบติดตาม — ช่างส่งงานซ่อมแล้ว'))
    expect(screen.getByTestId('finding-repairs')).toHaveTextContent('ส่งงานแล้ว รอปิดงาน')
    expect(screen.queryByRole('button', { name: 'เปิดใบงานซ่อมจากรายการนี้' })).not.toBeInTheDocument()
  })
})

describe('FindingFollowupPage (R3-11)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('groups active Findings into waiting-for-decision and in-repair', async () => {
    stub(MANAGER, [
      { finding: finding(), repairs: [], followup_group: 'AWAITING_REPAIR_DECISION' },
      { finding: finding({ finding_id: 'FND-0002' }),
        repairs: [{ repair_id: 'RPR-0003', status: 'OPEN', opened_at: 'x', closed_at: null, completion_submitted_at: null, cancelled_at: null }],
        followup_group: 'IN_REPAIR' },
    ])
    renderAt('/findings/follow-up')
    await waitFor(() => expect(screen.getByTestId('followup-AWAITING_REPAIR_DECISION')).toHaveTextContent('FND-0001'))
    expect(screen.getByTestId('followup-IN_REPAIR')).toHaveTextContent('FND-0002')
    expect(screen.getByTestId('followup-IN_REPAIR')).toHaveTextContent('RPR-0003')
  })
})
