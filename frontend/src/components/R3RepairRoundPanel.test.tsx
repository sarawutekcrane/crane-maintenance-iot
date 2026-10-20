import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import type { Repair } from '../lib/types'
import { R3RepairRoundPanel } from './R3RepairRoundPanel'

// R3 §10: lead-only completion (the backend proves the lead; the page only sends
// the current set id), manager-only cancellation before recorded work, frozen
// display after completion / cancellation.

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const MANAGER = { user_id: 'USR-MGR', roles: ['MAINTENANCE_MANAGER'], capabilities: ['can_view', 'can_manage_repair', 'can_close_repair', 'can_manage_finding_repair'] }
const TECH = { user_id: 'USR-TEST-911', roles: ['TECHNICIAN'], capabilities: ['can_view'] }

function repair(overrides: Partial<Repair> = {}): Repair {
  return {
    repair_id: 'RPR-0001', asset_type: 'VEHICLE', asset_id: 'VEH-1046', source_type: 'FINDING', source_id: 'FND-0001',
    status: 'OPEN', opened_at: '2026-10-01T02:00:00Z', opened_by: 'USR-MGR', closed_at: null, closed_by: null,
    finding_id: 'FND-0001', completion_submitted_at: null, completion_submitted_by: null, completion_technician_id: null,
    completion_note: null, cancelled_at: null, cancelled_by: null, cancel_reason: null,
    ...overrides,
  } as Repair
}

function stub(me: unknown, assignmentStatus: string, onPost?: (url: string, init: RequestInit) => Response) {
  const posts: { url: string; body: unknown; requestId: string | null }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/me')) return json(me)
    if (init?.method === 'POST') {
      const headers = (init.headers ?? {}) as Record<string, string>
      posts.push({ url, body: JSON.parse(String(init.body)), requestId: headers['X-Request-Id'] ?? null })
      return onPost ? onPost(url, init) : json({}, 500)
    }
    if (url.includes('/technician-assignments')) {
      return json({ status: assignmentStatus, current: { assignment_set_id: 'SET-0001' } })
    }
    throw new Error(`Unexpected fetch ${url}`)
  }))
  return posts
}

function renderPanel(r: Repair, noRecordedWork = true, onChanged = vi.fn()) {
  render(
    <CapabilitiesProvider>
      <MemoryRouter>
        <R3RepairRoundPanel repair={r} noRecordedWork={noRecordedWork} onChanged={onChanged} />
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
  return onChanged
}

describe('R3RepairRoundPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends completion with the current set id and one X-Request-Id; the technician sees no cancel form', async () => {
    const user = userEvent.setup()
    const posts = stub(TECH, 'VALID', () => json({ repair: repair(), actions: [], parts: [] }))
    const onChanged = renderPanel(repair())
    expect(screen.getByTestId('r3-round-finding-link')).toHaveAttribute('href', '/findings/FND-0001')
    const button = screen.getByRole('button', { name: 'ส่งงานซ่อมเสร็จ' })
    await waitFor(() => expect(button).toBeEnabled())
    expect(screen.queryByTestId('r3-cancel-form')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('หมายเหตุการส่งงาน (ถ้ามี)'), 'เปลี่ยนซีลแล้ว')
    await user.click(button)
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(posts[0]).toMatchObject({ url: '/api/v1/repairs/RPR-0001/completion', body: { expected_set_id: 'SET-0001', note: 'เปลี่ยนซีลแล้ว' } })
    expect(posts[0].requestId).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('a refused completion (not the lead) shows the Thai message', async () => {
    const user = userEvent.setup()
    stub(TECH, 'VALID', () => json({ error: { code: 'REPAIR_COMPLETION_LEAD_ONLY', message: 'x', details: null } }, 403))
    renderPanel(repair())
    const button = screen.getByRole('button', { name: 'ส่งงานซ่อมเสร็จ' })
    await waitFor(() => expect(button).toBeEnabled())
    await user.click(button)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('เฉพาะช่างหลัก'))
  })

  it('completion stays disabled unless the V2 assignment is VALID, and no work is recorded before a lead (L9)', async () => {
    stub(TECH, 'NONE')
    renderPanel(repair())
    expect(await screen.findByTestId('r3-round-needs-lead')).toHaveTextContent('ต้องมอบหมายทีมช่างก่อน')
    expect(screen.getByRole('button', { name: 'ส่งงานซ่อมเสร็จ' })).toBeDisabled()
  })

  it('the manager cancels only with a reason and only before recorded work', async () => {
    const user = userEvent.setup()
    const posts = stub(MANAGER, 'NOT_ASSIGNED', () => json({ repair: repair({ status: 'CANCELLED' }), actions: [], parts: [] }))
    renderPanel(repair())
    const cancel = await screen.findByRole('button', { name: 'ยกเลิกใบงานซ่อม' })
    await user.click(cancel)
    expect(screen.getByRole('alert')).toHaveTextContent('กรุณาระบุเหตุผลในการยกเลิก')
    expect(posts).toHaveLength(0)
    await user.type(screen.getByLabelText('เหตุผลในการยกเลิกใบงาน (จำเป็น)'), 'เปิดซ้ำ')
    await user.click(cancel)
    await waitFor(() => expect(posts[0]).toMatchObject({ url: '/api/v1/repairs/RPR-0001/cancellation', body: { reason: 'เปิดซ้ำ' } }))
  })

  it('no cancel form once work is recorded', async () => {
    stub(MANAGER, 'NOT_ASSIGNED')
    renderPanel(repair(), false)
    await waitFor(() => expect(screen.getByTestId('r3-completion-form')).toBeInTheDocument())
    expect(screen.queryByTestId('r3-cancel-form')).not.toBeInTheDocument()
  })

  it('a submitted round is frozen and never claims a verified repair', () => {
    stub(MANAGER, 'VALID')
    renderPanel(repair({ completion_submitted_at: '2026-10-02T09:00:00Z', completion_technician_id: 'TEC-TEST-911' }))
    expect(screen.getByTestId('r3-completion-submitted')).toHaveTextContent('ส่งงานแล้ว รอปิดงาน')
    expect(screen.getByTestId('r3-completion-submitted')).toHaveTextContent('ไม่ใช่การยืนยันว่าแก้ไขสำเร็จ')
    expect(screen.queryByTestId('r3-completion-form')).not.toBeInTheDocument()
    expect(screen.queryByTestId('r3-cancel-form')).not.toBeInTheDocument()
  })

  it('a cancelled round shows who, when and why', () => {
    stub(MANAGER, 'VALID')
    renderPanel(repair({ status: 'CANCELLED', cancelled_at: '2026-10-01T03:00:00Z', cancelled_by: 'USR-MGR', cancel_reason: 'เปิดซ้ำ' }))
    expect(screen.getByTestId('r3-round-cancelled')).toHaveTextContent('เหตุผล: เปิดซ้ำ')
    expect(screen.queryByTestId('r3-completion-form')).not.toBeInTheDocument()
  })
})
