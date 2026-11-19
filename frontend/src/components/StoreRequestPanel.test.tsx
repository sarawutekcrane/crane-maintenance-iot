import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { StoreRequestPanel } from './StoreRequestPanel'

// R8 PRE-UAT (Owner Decision 1) — repair material workflow panel. Synthetic data only.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const LINE = {
  requisition_line_id: 'MRL-1', material_request_id: 'MR-1', part_id: 'PART-0001', part_description: 'ไส้กรองทดสอบ',
  unit: 'ชิ้น', requested: '2', decision: 'APPROVED', approved: '2', issued: '2', used: '0', return_declared: '0',
  return_accepted: '0', unreconciled: '2', pending_return: '0', awaiting_issue: '0', issued_part_ids: ['PART-0001'],
  issued_parts: [{ part_id: 'PART-0001', part_instance_id: '', part_code_snapshot: 'FLT-1', issued: '2', used: '0',
    return_declared: '0', return_accepted: '0', unreconciled: '2' }],
  blockers: ['ISSUED_NOT_USED_OR_RETURNED'],
}
const REC = { repair_id: 'RPR-1', state: 'UNRECONCILED', blockers: ['ISSUED_NOT_USED_OR_RETURNED'], lines: [LINE],
  events: [{ event_id: 'STE-1', event_type: 'ISSUED', part_id: 'PART-0001', quantity: '2', unit: 'ชิ้น', position_code: '',
    actor_user_id: 'USR-STORE' }], exceptions_note: 'EXCEPTION_POLICY_PENDING', scope_note: 'ไม่ใช่บัญชีสต็อกคลัง' }

function installApi(caps: string[], post?: (path: string) => Response) {
  const posts: { path: string; body: Record<string, unknown>; requestId: string | null }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
    if (path === '/me') return json({ user_id: 'USR-1', roles: [], capabilities: caps, is_dev_auth: true })
    if (path === '/repairs/RPR-1/store-reconciliation') return json(REC)
    if (init.method === 'POST') {
      posts.push({ path, body: JSON.parse(String(init.body)), requestId: new Headers(init.headers).get('X-Request-Id') })
      return post ? post(path) : json({ replayed: false, material_request_id: 'MR-1', events: [] })
    }
    throw new Error(`Unexpected fetch: ${path}`)
  }))
  return posts
}

function renderPanel(open = true) {
  return render(
    <MemoryRouter><CapabilitiesProvider><StoreRequestPanel repairId="RPR-1" repairOpen={open} /></CapabilitiesProvider></MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('StoreRequestPanel', () => {
  it('shows per-line issued / used / returned as distinct facts and the reconciliation blockers', async () => {
    installApi(['can_view'])
    renderPanel()
    expect(await screen.findByText(/สถานะกระทบยอด: ยังไม่ครบ/)).toBeInTheDocument()
    expect(screen.getByText(/จ่ายแล้วแต่ยังไม่ยืนยันใช้\/คืน/)).toBeInTheDocument()
    expect(screen.getByText(/จ่ายแล้วไม่เท่ากับติดตั้ง/)).toBeInTheDocument()
    // Store-only steps are hidden without the TEST grants; technician steps are offered (backend checks membership).
    expect(screen.queryByRole('button', { name: 'อนุมัติ' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ยืนยันใช้จริง' })).toBeInTheDocument()
  })

  it('confirms actual use with the installed position and a request id', async () => {
    const posts = installApi(['can_view'])
    renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: 'ยืนยันใช้จริง' }))
    await userEvent.type(screen.getByLabelText(/^จำนวน \(/), '1')
    await userEvent.type(screen.getByLabelText('ตำแหน่งที่ติดตั้ง *'), 'ล้อหน้าซ้าย')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].path).toBe('/repairs/RPR-1/store-lines/MRL-1/use-confirmations')
    expect(posts[0].body).toEqual({ quantity: '1', part_id: 'PART-0001', position_code: 'ล้อหน้าซ้าย' })
    expect(posts[0].requestId).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('keeps the same request id when the answer is lost and resends safely', async () => {
    let calls = 0
    const posts = installApi(['can_view'], () => {
      calls += 1
      if (calls === 1) throw new TypeError('network down')
      return json({ replayed: true, material_request_id: 'MR-1', events: [] })
    })
    renderPanel()
    await userEvent.type(await screen.findByLabelText('รายละเอียด แถว 1'), 'ซีลทดสอบ')
    await userEvent.click(screen.getByRole('button', { name: 'ส่งคำขอเบิก' }))
    expect(await screen.findByText(/ส่งอีกครั้งได้อย่างปลอดภัย/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'ส่งคำขอเบิก' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1].requestId).toBe(posts[0].requestId)
    expect(await screen.findByText(/บันทึกไว้แล้ว \(ไม่สร้างซ้ำ\)/)).toBeInTheDocument()
  })

  it('offers approve / deny only to the TEST approver and explains a refusal', async () => {
    installApi(['can_view', 'can_test_store_approve', 'can_test_store_issue', 'can_test_store_receive_return'],
      () => json({ error: { code: 'STORE_QUANTITY_EXCEEDED', message: 'x', request_id: 'r' } }, 409))
    REC.lines = [{ ...LINE, decision: 'AWAITING', approved: '0', issued: '0', unreconciled: '0', issued_part_ids: [], issued_parts: [] }]
    renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: 'อนุมัติ' }))
    await userEvent.type(screen.getByLabelText(/^จำนวน \(/), '5')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByText('จำนวนเกินกว่าที่อนุญาตในขั้นตอนนี้')).toBeInTheDocument()
    REC.lines = [LINE]
  })

  it('hides the request form once the repair is technically closed', async () => {
    installApi(['can_view'])
    renderPanel(false)
    await screen.findByText(/สถานะกระทบยอด/)
    expect(screen.queryByRole('button', { name: 'ส่งคำขอเบิก' })).not.toBeInTheDocument()
  })

  // Independent review fixes ---------------------------------------------------------------------
  it('keeps the request id of an uncertain step across cancel and reopen (never a second write)', async () => {
    let calls = 0
    const posts = installApi(['can_view'], () => {
      calls += 1
      if (calls === 1) throw new TypeError('network down')
      return json({ replayed: true, material_request_id: 'MR-1', events: [] })
    })
    renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: 'ยืนยันใช้จริง' }))
    await userEvent.type(screen.getByLabelText(/^จำนวน \(/), '1')
    await userEvent.type(screen.getByLabelText('ตำแหน่งที่ติดตั้ง *'), 'ล้อหน้าซ้าย')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    await screen.findByText(/ส่งอีกครั้งได้อย่างปลอดภัย/)
    await userEvent.click(screen.getByRole('button', { name: 'ยกเลิก' }))
    await userEvent.click(screen.getByRole('button', { name: 'ยืนยันใช้จริง' }))
    expect(screen.getByLabelText(/^จำนวน \(/)).toHaveValue('1') // the uncertain values come back
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1].requestId).toBe(posts[0].requestId)
    expect(posts[1].body).toEqual(posts[0].body)
  })

  it('sends a decimal quantity exactly as typed', async () => {
    const posts = installApi(['can_view'])
    renderPanel()
    await userEvent.type(await screen.findByLabelText('รายละเอียด แถว 1'), 'น้ำมันทดสอบ')
    await userEvent.clear(screen.getByLabelText('จำนวน แถว 1'))
    await userEvent.type(screen.getByLabelText('จำนวน แถว 1'), '1.5')
    await userEvent.click(screen.getByRole('button', { name: 'ส่งคำขอเบิก' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect((posts[0].body.lines as { quantity: string }[])[0].quantity).toBe('1.5')
  })

  it.each([[501, 'FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE'], [403, 'PREUAT_ACTION_NOT_AUTHORIZED']])(
    'renders nothing when the feature answers %s', async (status, code) => {
      vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
        if (path === '/me') return json({ user_id: 'U', roles: [], capabilities: [] })
        return json({ error: { code, message: 'x', request_id: 'r' } }, status)
      }))
      const { container } = renderPanel()
      await new Promise((r) => setTimeout(r, 30))
      expect(container.querySelector('.store-panel')).toBeNull()
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

  it('a return names the actual part; with two issued identities nothing is preselected', async () => {
    const two = { ...LINE, issued_parts: [
      { part_id: 'PART-0001', part_instance_id: '', part_code_snapshot: 'A', issued: '1', used: '0', return_declared: '1',
        return_accepted: '0', unreconciled: '1' },
      { part_id: 'PART-0005', part_instance_id: 'PINST-9', part_code_snapshot: 'B', issued: '1', used: '0',
        return_declared: '1', return_accepted: '0', unreconciled: '1' }], issued_part_ids: ['PART-0001', 'PART-0005'],
      return_declared: '2', pending_return: '2' }
    const original = REC.lines
    REC.lines = [two]
    try {
      const posts = installApi(['can_view', 'can_test_store_receive_return'])
      renderPanel()
      await userEvent.click(await screen.findByRole('button', { name: 'รับคืนเข้าคลัง' }))
      const select = screen.getByLabelText('อะไหล่ (ตามที่จ่ายจริง) *')
      expect(select).toHaveValue('')
      await userEvent.type(screen.getByLabelText(/^จำนวน \(/), '1')
      await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
      expect(await screen.findByText('เลือกอะไหล่ตามที่จ่ายจริงก่อน (ระบบไม่เดาให้)')).toBeInTheDocument()
      expect(posts).toHaveLength(0)
      await userEvent.selectOptions(select, 'PART-0005|PINST-9')
      await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
      await waitFor(() => expect(posts).toHaveLength(1))
      expect(posts[0].body).toEqual({ quantity: '1', part_id: 'PART-0005', part_instance_id: 'PINST-9' })
    } finally {
      REC.lines = original
    }
  })
})

describe('StoreRequestPanel — ISS-01 refresh signal', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('tells the repair page after a successful write, never after a refusal', async () => {
    let refuse = true
    installApi(['can_view'], () => (refuse ? json({ error: { code: 'STORE_QUANTITY_EXCEEDED', message: 'x', request_id: 'r' } }, 409)
      : json({ replayed: false, material_request_id: 'MR-1', events: [] })))
    const changed = vi.fn()
    render(<MemoryRouter><CapabilitiesProvider><StoreRequestPanel repairId="RPR-1" repairOpen onChanged={changed} /></CapabilitiesProvider></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'ยืนยันใช้จริง' }))
    await userEvent.type(screen.getByLabelText(/^จำนวน \(/), '1')
    await userEvent.type(screen.getByLabelText('ตำแหน่งที่ติดตั้ง *'), 'ซ้าย')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    await screen.findByText(/STORE_QUANTITY_EXCEEDED|เกิน/)
    expect(changed).not.toHaveBeenCalled()
    refuse = false
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
  })
})
