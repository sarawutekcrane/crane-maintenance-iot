import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { AccessManagementPage } from './AccessManagementPage'

/** Access Management screen — synthetic stubs only; the backend is authoritative. */

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
function apiError(code: string, status: number) {
  return json({ error: { code, message: code, details: null, request_id: 'REQ-SYN' } }, status)
}

const ROOT_ME = { personnel_id: 'PER-MGR', name: 'ผู้จัดการ', is_root: true, recovery: false, revision: 3, root_holder_personnel_id: 'PER-MGR', delegations: [], capabilities: [] }
const DELEGATION = {
  delegation_id: 'ACD-1', delegate_personnel_id: 'PER-OPM', delegate_name: 'หัวหน้าปฏิบัติการ', department_id: 'DEPT-OPS',
  department_name_th: 'ปฏิบัติการ', capabilities: ['can_report_repair'], granted_by_personnel_id: 'PER-MGR', granted_at: '2026-10-01T00:00:00Z',
  reason_th: 'มอบ', revoked: false, revoked_at: null, revoked_by_personnel_id: null, revoke_reason_th: null, effective: true,
}
const DELEGATE_ME = { ...ROOT_ME, personnel_id: 'PER-OPM', name: 'หัวหน้าปฏิบัติการ', is_root: false, delegations: [DELEGATION] }
const CATALOG = {
  categories: [
    { code: 'B', label_th: 'การแจ้งซ่อม', note_th: null, capabilities: [{ code: 'can_report_repair', label_th: 'แจ้งปัญหา/แจ้งซ่อม', effect_th: 'ส่งคำขอแจ้งซ่อม', sensitive: false }] },
    { code: 'D', label_th: 'การมอบหมายช่าง (V2)', note_th: 'ไม่มีสิทธิ์แยก', capabilities: [] },
    { code: 'G', label_th: 'บุคลากร', note_th: null, capabilities: [{ code: 'can_manage_personnel', label_th: 'จัดการสถานะบุคลากร', effect_th: 'เปิด/ปิดการใช้งาน', sensitive: true }] },
    { code: 'I', label_th: 'รายงาน', note_th: null, capabilities: [{ code: 'can_view', label_th: 'ดูข้อมูล รายงาน และประวัติ', effect_th: 'ดูข้อมูล', sensitive: false }] },
  ],
}
const DEPARTMENTS = [{ department_id: 'DEPT-OPS', department_name_th: 'ปฏิบัติการ', is_active: true, employee_count: 4, grantable: ['can_report_repair', 'can_view'] }]
function person(id: string, name: string, caps: string[], extra: Record<string, unknown> = {}) {
  return { personnel_id: id, name, position: 'พนักงานขับรถ', position_key: 'พนักงานขับรถ', active: true, is_self: false, is_root: false, exclusion: null, capabilities: caps, ...extra }
}
function roster(selfId: string | null) {
  return {
    department_id: 'DEPT-OPS', revision: 3, grantable: ['can_report_repair', 'can_view'],
    positions: [{ key: 'พนักงานขับรถ', label: 'พนักงานขับรถ' }, { key: 'หัวหน้า', label: 'หัวหน้า' }],
    employees: [
      person('PER-OPM', 'หัวหน้าปฏิบัติการ', [], {
        position: 'หัวหน้า', position_key: 'หัวหน้า', is_self: selfId === 'PER-OPM', exclusion: selfId === 'PER-OPM' ? 'SELF_NOT_EDITABLE' : null,
      }),
      person('PER-D1', 'คนขับหนึ่ง', ['can_view']),
      person('PER-D2', 'คนขับสอง', []),
      person('PER-OLD', 'ลาออก', [], { active: false, exclusion: 'INACTIVE' }),
    ],
    active_employee_count: 3, capability_counts: {},
  }
}

interface Post { url: string; body: Record<string, unknown>; requestId: string | null }

function stub(me: unknown, routes: { onPost?: (url: string, body: Record<string, unknown>) => Response; selfId?: string | null } = {}) {
  const posts: Post[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method === 'POST') {
      const headers = (init.headers ?? {}) as Record<string, string>
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      posts.push({ url, body, requestId: headers['X-Request-Id'] ?? null })
      return routes.onPost ? routes.onPost(url, body) : json({}, 500)
    }
    if (url === '/api/v1/me') return json({ user_id: 'USR', roles: [], capabilities: [] })
    if (url === '/api/v1/access/me') return typeof me === 'function' ? (me as () => Response)() : json(me)
    if (url === '/api/v1/access/catalog') return json(CATALOG)
    if (url === '/api/v1/access/departments') return json(DEPARTMENTS)
    if (url.startsWith('/api/v1/access/employees')) return json(roster(routes.selfId ?? null))
    if (url === '/api/v1/access/delegations') return json([DELEGATION])
    if (url === '/api/v1/access/root') return json({ position_th: 'ผู้จัดการแผนกซ่อมบำรุง', holder: { personnel_id: 'PER-MGR', name: 'ผู้จัดการ' }, valid: true, revision: 3, appointments: [] })
    if (url.startsWith('/api/v1/access/audit')) return json([])
    throw new Error(`unexpected ${url}`)
  }))
  return posts
}

function renderPage() {
  render(
    <MemoryRouter>
      <CapabilitiesProvider>
        <AccessManagementPage />
      </CapabilitiesProvider>
    </MemoryRouter>,
  )
}

async function chooseDepartment(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(await screen.findByLabelText('1. แผนก'), 'DEPT-OPS')
  await waitFor(() => expect(screen.getByLabelText('3. พนักงาน')).not.toBeDisabled())
}

describe('AccessManagementPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('outside Access Management mode it says the feature is not enabled', async () => {
    stub(() => apiError('ACCESS_MANAGEMENT_NOT_ENABLED', 409))
    renderPage()
    expect(await screen.findByText('ยังไม่เปิดใช้การจัดการสิทธิ์')).toBeInTheDocument()
  })

  it('an employee without authority sees no controls', async () => {
    stub({ ...ROOT_ME, is_root: false, personnel_id: 'PER-D1' })
    renderPage()
    expect(await screen.findByText('ไม่มีสิทธิ์เข้าถึง')).toBeInTheDocument()
    expect(screen.queryByLabelText('1. แผนก')).toBeNull()
  })

  it('department → position → employee: the position filter narrows names only, "all" keeps the whole department', async () => {
    const user = userEvent.setup()
    stub(ROOT_ME)
    renderPage()
    await chooseDepartment(user)
    await user.selectOptions(screen.getByLabelText('2. ตำแหน่ง (ตัวกรองรายชื่อ)'), 'หัวหน้า')
    const options = within(screen.getByLabelText('3. พนักงาน')).getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual(['— เลือกพนักงาน —', 'ทุกคนในแผนก (4 คน)', 'หัวหน้าปฏิบัติการ — หัวหน้า'])
    await user.selectOptions(screen.getByLabelText('3. พนักงาน'), '__ALL__')
    expect(screen.getByTestId('access-bulk-note')).toHaveTextContent('ไม่ขึ้นกับตัวกรองตำแหน่ง')
    expect(screen.getByTestId('access-bulk-excluded')).toHaveTextContent('ไม่รวม ลาออก: ไม่อยู่ในสถานะใช้งาน')
    expect(screen.getByTestId('access-sensitive-can_manage_personnel')).toHaveTextContent('ผู้จัดการแผนกซ่อมบำรุงเท่านั้น')
    expect(screen.getByTestId('access-category-D')).toHaveTextContent('ไม่มีสิทธิ์แยก')
  })

  it('bulk: mixed counts, untouched switches are not sent, preview then confirmation with one X-Request-Id', async () => {
    const user = userEvent.setup()
    const posts = stub(ROOT_ME, {
      onPost: (url) =>
        url.endsWith('/preview')
          ? json({ target_kind: 'DEPARTMENT', department_id: 'DEPT-OPS', eligible_count: 3, target_count: 3, target_personnel_ids: [], excluded: [{ personnel_id: 'PER-OLD', name: 'ลาออก', reason: 'INACTIVE' }], skipped_personnel_ids: ['PER-OLD'], per_capability: [{ capability: 'can_report_repair', action: 'GRANT', changed: 3, unchanged: 0 }], revision: 3 })
          : json({ replayed: false, batch_id: 'ACB-1', target_kind: 'DEPARTMENT', department_id: 'DEPT-OPS', eligible_count: 3, target_count: 3, target_personnel_ids: [], excluded: [], skipped_personnel_ids: [], per_capability: [{ capability: 'can_report_repair', action: 'GRANT', changed: 3, unchanged: 0 }], revision: 7 }),
    })
    renderPage()
    await chooseDepartment(user)
    await user.selectOptions(screen.getByLabelText('3. พนักงาน'), '__ALL__')
    const view = screen.getByRole('switch', { name: 'ดูข้อมูล รายงาน และประวัติ' })
    expect(view).toHaveTextContent('1 จาก 3')
    expect(view).toHaveAttribute('aria-checked', 'mixed')
    await user.click(screen.getByRole('switch', { name: 'แจ้งปัญหา/แจ้งซ่อม' }))
    await user.click(screen.getByRole('button', { name: 'ตรวจสอบก่อนบันทึก' }))
    expect(await screen.findByTestId('access-preview')).toHaveTextContent('เปลี่ยน 3 คน, ไม่เปลี่ยน 0 คน')
    expect(screen.getByTestId('access-preview-excluded')).toHaveTextContent('ไม่รวม ลาออก: ไม่อยู่ในสถานะใช้งาน')
    expect(posts[0].body).toEqual({ target: { kind: 'DEPARTMENT', department_id: 'DEPT-OPS' }, changes: { can_report_repair: true }, expected_revision: 3 })
    await user.click(screen.getByRole('button', { name: 'บันทึกการเปลี่ยนสิทธิ์' }))
    expect(screen.getByRole('alert')).toHaveTextContent('กรุณาระบุเหตุผล')
    await user.type(screen.getByLabelText('เหตุผลของการเปลี่ยนสิทธิ์ (จำเป็น)'), 'ทุกคนต้องแจ้งซ่อมได้')
    await user.click(screen.getByRole('button', { name: 'บันทึกการเปลี่ยนสิทธิ์' }))
    expect(posts).toHaveLength(1) // nothing is saved before the confirmation
    await user.click(screen.getByRole('button', { name: 'ยืนยันบันทึก' }))
    expect(await screen.findByTestId('access-saved')).toHaveTextContent('เปลี่ยนสิทธิ์ 3 รายการ กับพนักงาน 3 คน')
    expect(posts[1]).toMatchObject({ url: '/api/v1/access/grants', body: { changes: { can_report_repair: true }, reason_th: 'ทุกคนต้องแจ้งซ่อมได้', expected_revision: 3 } })
    expect(posts[1].requestId).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('a stale revision writes nothing, reloads and asks for a new preview', async () => {
    const user = userEvent.setup()
    stub(ROOT_ME, {
      onPost: (url) =>
        url.endsWith('/preview')
          ? json({ target_kind: 'EMPLOYEE', department_id: 'DEPT-OPS', eligible_count: 1, target_count: 1, target_personnel_ids: ['PER-D2'], excluded: [], skipped_personnel_ids: [], per_capability: [{ capability: 'can_view', action: 'GRANT', changed: 1, unchanged: 0 }], revision: 3 })
          : apiError('ACCESS_STALE_REVISION', 409),
    })
    renderPage()
    await chooseDepartment(user)
    await user.selectOptions(screen.getByLabelText('3. พนักงาน'), 'PER-D2')
    await user.click(screen.getByRole('switch', { name: 'ดูข้อมูล รายงาน และประวัติ' }))
    await user.click(screen.getByRole('button', { name: 'ตรวจสอบก่อนบันทึก' }))
    await user.type(await screen.findByLabelText('เหตุผลของการเปลี่ยนสิทธิ์ (จำเป็น)'), 'ให้ดูข้อมูล')
    await user.click(screen.getByRole('button', { name: 'บันทึกการเปลี่ยนสิทธิ์' }))
    await user.click(screen.getByRole('button', { name: 'ยืนยันบันทึก' }))
    expect(await screen.findByTestId('access-error')).toHaveTextContent('ACCESS_STALE_REVISION')
    expect(screen.queryByTestId('access-preview')).toBeNull()
  })

  it('a delegate cannot edit their own permissions and sees no delegation or root controls', async () => {
    const user = userEvent.setup()
    stub(DELEGATE_ME, { selfId: 'PER-OPM' })
    renderPage()
    expect(await screen.findByTestId('access-authority')).toHaveTextContent('ห้ามมอบต่อ')
    await chooseDepartment(user)
    await user.selectOptions(screen.getByLabelText('3. พนักงาน'), 'PER-OPM')
    expect(screen.getByTestId('access-self-locked')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'แจ้งปัญหา/แจ้งซ่อม' })).toBeDisabled()
    expect(screen.queryByText(/มอบอำนาจจัดการสิทธิ์ให้/)).toBeNull()
    expect(screen.queryByText('ส่งมอบตำแหน่ง')).toBeNull()
    await user.selectOptions(screen.getByLabelText('3. พนักงาน'), '__ALL__')
    expect(screen.getByTestId('access-bulk-excluded')).toHaveTextContent('ไม่รวม หัวหน้าปฏิบัติการ: ผู้รับมอบอำนาจแก้ไขสิทธิ์ของตนเองไม่ได้')
  })

  it('an individual switch turned back to its stored value is no change', async () => {
    const user = userEvent.setup()
    stub(ROOT_ME)
    renderPage()
    await chooseDepartment(user)
    await user.selectOptions(screen.getByLabelText('3. พนักงาน'), 'PER-D1')
    const view = screen.getByRole('switch', { name: 'ดูข้อมูล รายงาน และประวัติ' })
    expect(view).toHaveTextContent('เปิด')
    await user.click(view)
    expect(screen.getByText('สวิตช์ที่เปลี่ยน: 1 รายการ')).toBeInTheDocument()
    await user.click(view)
    expect(screen.getByText('สวิตช์ที่เปลี่ยน: 0 รายการ')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ตรวจสอบก่อนบันทึก' })).toBeDisabled()
  })

  it('the root holder sees delegations, the position holder and the delegation form for one employee', async () => {
    const user = userEvent.setup()
    stub(ROOT_ME)
    renderPage()
    expect(await screen.findByTestId('access-root-holder')).toHaveTextContent('ผู้จัดการ (PER-MGR)')
    expect(await screen.findByTestId('access-delegations')).toHaveTextContent('หัวหน้าปฏิบัติการ')
    await chooseDepartment(user)
    await user.selectOptions(screen.getByLabelText('3. พนักงาน'), 'PER-D1')
    expect(screen.getByText('มอบอำนาจจัดการสิทธิ์ให้ คนขับหนึ่ง')).toBeInTheDocument()
    // D7: a system-wide (sensitive) capability is never offered for delegation.
    expect(within(document.querySelector('.access-delegation-form') as HTMLElement).queryByText('จัดการสถานะบุคลากร')).toBeNull()
  })
})
