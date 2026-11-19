import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { useTestGrantControlVisible } from '../lib/masterRecords'
import { EquipmentBranchAssignPanel, MasterCreatePanel, MasterRecordForm, PersonnelDepartmentMovePanel } from './MasterRecordForm'

// R8 PRE-UAT (workstream A) — TEST master record form and the panels for routes that had no UI.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function installApi(caps: string[], post?: (path: string) => Response) {
  const posts: { path: string; method: string; body: Record<string, unknown>; requestId: string | null }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
    if (path === '/me') return json({ user_id: 'USR-1', roles: [], capabilities: caps, is_dev_auth: true })
    if (path === '/equipment/EQP-0002/branch-history') return json({ history_revision: 'EBH1-0', current: { branch_id: null } })
    if (path === '/branches') return json({ items: [{ branch_id: 'BR-RAYONG', branch_name: 'ระยอง' }] })
    if (path === '/personnel/PER-1/department-history') return json({ current_department_id: 'DEPT-A' })
    if (path === '/departments') return json({ items: [{ department_id: 'DEPT-B', department_name_th: 'แผนกบี' }] })
    if (init.method === 'POST' || init.method === 'PATCH') {
      posts.push({ path, method: init.method, body: JSON.parse(String(init.body)), requestId: new Headers(init.headers).get('X-Request-Id') })
      return post ? post(path) : json({ entity: 'X', record_id: 'VEH-TEST-5001', action: 'CREATE', replayed: false, event_id: 'E', values: {} })
    }
    throw new Error(`Unexpected fetch: ${path}`)
  }))
  return posts
}

const wrap = (ui: React.ReactNode) => render(<MemoryRouter><CapabilitiesProvider>{ui}</CapabilitiesProvider></MemoryRouter>)

afterEach(() => vi.unstubAllGlobals())

describe('MasterRecordForm', () => {
  it('creates a vehicle with only schema fields and a client request id', async () => {
    const posts = installApi(['can_view', 'can_test_manage_master_records'])
    const saved = vi.fn()
    wrap(<MasterRecordForm entity="vehicles" onSaved={saved} />)
    await userEvent.type(screen.getByLabelText('หมายเลขเครื่องจักร *'), 'T/9001')
    await userEvent.type(screen.getByLabelText('รหัสรุ่น *'), 'MODEL-0002')
    await userEvent.selectOptions(screen.getByLabelText('สถานะ *'), 'READY')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(saved).toHaveBeenCalled())
    expect(posts[0]).toMatchObject({ path: '/master-records/vehicles', method: 'POST',
      body: { machine_no: 'T/9001', model_id: 'MODEL-0002', operational_status: 'READY' } })
    expect(posts[0].requestId).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('edit mode offers only editable fields and sends PATCH', async () => {
    const posts = installApi(['can_view', 'can_test_manage_master_records'],
      () => json({ entity: 'MODEL', record_id: 'MODEL-TEST-5001', action: 'UPDATE', replayed: false, event_id: 'E', values: {} }))
    wrap(<MasterRecordForm entity="models" recordId="MODEL-TEST-5001" initial={{ model_name: 'เดิม', model_code: 'C' }} onSaved={vi.fn()} />)
    expect(screen.queryByLabelText(/รหัสรุ่น \(code\)/)).not.toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('ชื่อรุ่น *'))
    await userEvent.type(screen.getByLabelText('ชื่อรุ่น *'), 'ใหม่')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toMatchObject({ path: '/master-records/models/MODEL-TEST-5001', method: 'PATCH' })
    expect(posts[0].body.model_name).toBe('ใหม่')
  })

  it('explains a duplicate refusal', async () => {
    installApi(['can_view', 'can_test_manage_master_records'],
      () => json({ error: { code: 'MASTER_RECORD_DUPLICATE', message: 'x', request_id: 'r' } }, 409))
    wrap(<MasterRecordForm entity="branches" onSaved={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('ชื่อสาขา *'), 'ซ้ำ')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByText('มีข้อมูลที่ใช้ค่านี้อยู่แล้ว ไม่ได้บันทึก')).toBeInTheDocument()
  })

  it('the create panel appears only with the TEST grant and opens the new record', async () => {
    installApi(['can_view', 'can_test_manage_master_records'])
    render(
      <MemoryRouter initialEntries={['/vehicles']}>
        <CapabilitiesProvider>
          <Routes>
            <Route path="/vehicles" element={<MasterCreatePanel entity="vehicles" detailPath={(id) => `/vehicle/${id}`} />} />
            <Route path="/vehicle/:id" element={<p>หน้าใหม่</p>} />
          </Routes>
        </CapabilitiesProvider>
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'เพิ่มรถ (TEST)' }))
    await userEvent.type(screen.getByLabelText('หมายเลขเครื่องจักร *'), 'T/1')
    await userEvent.type(screen.getByLabelText('รหัสรุ่น *'), 'M')
    await userEvent.selectOptions(screen.getByLabelText('สถานะ *'), 'READY')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByText('หน้าใหม่')).toBeInTheDocument()
  })

  it('hides the create panel without the grant', async () => {
    installApi(['can_view'])
    wrap(<MasterCreatePanel entity="vehicles" detailPath={(id) => id} />)
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryByRole('button', { name: 'เพิ่มรถ (TEST)' })).not.toBeInTheDocument()
  })

  it('assigns an equipment branch through the existing route with its expected revision', async () => {
    const posts = installApi(['can_view', 'can_transfer_equipment_branch'],
      () => json({ request_id: 'x', changed: true }))
    wrap(<EquipmentBranchAssignPanel equipmentId="EQP-0002" />)
    await screen.findByRole('option', { name: 'ระยอง' })
    await userEvent.selectOptions(screen.getByLabelText('สาขาใหม่'), 'BR-RAYONG')
    await userEvent.click(screen.getByRole('button', { name: /บันทึกสาขา/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toEqual({ to_branch_id: 'BR-RAYONG', effective: { mode: 'NOW' }, expected_current_branch_id: null,
      expected_history_revision: 'EBH1-0' })
  })

  it('moves a person to another department through the existing route', async () => {
    const posts = installApi(['can_view', 'can_move_personnel_department'], () => json({ request_id: 'x', changed: true }))
    wrap(<PersonnelDepartmentMovePanel personnelId="PER-1" />)
    await screen.findByRole('option', { name: /แผนกบี/ })
    await userEvent.selectOptions(screen.getByLabelText('แผนกใหม่'), 'DEPT-B')
    await userEvent.click(screen.getByRole('button', { name: /บันทึกการย้าย/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toEqual({ operation: 'TRANSFER', department_id: 'DEPT-B', effective: { mode: 'NOW' },
      expected_current_department_id: 'DEPT-A' })
  })

  it('cancel + reopen after a lost answer resends with the same request id (independent review)', async () => {
    let calls = 0
    const posts = installApi(['can_view', 'can_test_manage_master_records'], () => {
      calls += 1
      if (calls === 1) throw new TypeError('network down')
      return json({ entity: 'PERSONNEL', record_id: 'PER-TEST-5001', action: 'CREATE', replayed: true, event_id: 'E', values: {} })
    })
    wrap(<MasterCreatePanel entity="branches" detailPath={(id) => `/x/${id}`} />)
    await userEvent.click(await screen.findByRole('button', { name: 'เพิ่มสาขา (TEST)' }))
    await userEvent.type(screen.getByLabelText('ชื่อสาขา *'), 'สาขาเน็ตหลุด')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    await screen.findByText(/อีกครั้งได้อย่างปลอดภัย/)
    await userEvent.click(screen.getByRole('button', { name: 'ยกเลิก' }))
    await userEvent.click(screen.getByRole('button', { name: 'เพิ่มสาขา (TEST)' }))
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1].requestId).toBe(posts[0].requestId)
  })
})

describe('useTestGrantControlVisible (PG-5 P-A)', () => {
  afterEach(() => vi.unstubAllGlobals())

  function Probe() {
    return <p>{useTestGrantControlVisible('can_test_manage_parts') ? 'แสดง' : 'ซ่อน'}</p>
  }

  function mode(accessMe: Response, caps: string[]) {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
      if (path === '/me') return json({ user_id: 'U', roles: [], capabilities: caps })
      if (path === '/access/me') return accessMe.clone()
      throw new Error(path)
    }))
  }

  it.each([
    ['legacy mode (409 ACCESS_MANAGEMENT_NOT_ENABLED) keeps the control', json({ error: { code: 'ACCESS_MANAGEMENT_NOT_ENABLED', message: 'x', request_id: 'r' } }, 409), [], 'แสดง'],
    ['Access Management with the grant shows it', json({ revision: 1 }), ['can_view', 'can_test_manage_parts'], 'แสดง'],
    ['Access Management without the grant hides it', json({ revision: 1 }), ['can_view', 'can_manage_repair'], 'ซ่อน'],
    ['an unknown answer is treated as Access Management (fail-closed)', json({ error: { code: 'X', message: 'x', request_id: 'r' } }, 500), [], 'ซ่อน'],
  ])('%s', async (_name, accessMe, caps, expected) => {
    mode(accessMe, caps)
    wrap(<Probe />)
    expect(await screen.findByText(expected)).toBeInTheDocument()
  })
})
