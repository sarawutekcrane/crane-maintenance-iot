import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { CrewAssignmentPanel } from './CrewAssignmentPanel'

// R8 early workstream — the vehicle crew panel (OD-1…OD-4). Synthetic data only.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const INTERVAL = {
  event_id: 'CRA-1', revision_no: '1', vehicle_id: 'VEH-1048', personnel_id: 'PER-TEST-911',
  personnel_name: 'ช่าง เก้าหนึ่งหนึ่ง', crew_role: 'OTHER', crew_role_note_th: 'ผู้ช่วยยก', mode: 'FULL_DAY',
  label_date: '2026-11-20', effective_start: '2026-11-19T17:00:00+00:00', effective_end: '2026-11-20T17:00:00+00:00',
  status: 'IDENTITY_UNVERIFIED',
}

function installApi(caps: string[], post?: () => Response) {
  const posts: { body: unknown; requestId: string | null }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://localhost')
    const path = url.pathname.replace('/api/v1', '')
    if (path === '/me') return json({ user_id: 'USR-1', roles: [], capabilities: caps, is_dev_auth: true })
    if (path === '/vehicles/VEH-1048/crew-assignments') return json({ vehicle_id: 'VEH-1048', intervals: [INTERVAL] })
    if (path === '/personnel') {
      return json({ items: [
        { personnel_id: 'PER-TEST-912', first_name: 'ช่าง', last_name: 'สอง', active_status: 'ACTIVE' },
        { personnel_id: 'PER-OFF', first_name: 'ไม่', last_name: 'ใช้งาน', active_status: 'INACTIVE' },
      ], page: 1, page_size: 200, total_items: 2 })
    }
    if (path === '/vehicles/VEH-1048/crew-assignment-operations' && init.method === 'POST') {
      posts.push({ body: JSON.parse(String(init.body)), requestId: new Headers(init.headers).get('X-Request-Id') })
      return post ? post() : json({ request_id: 'x', changed: true, operation_id: 'O', record_ids: ['R'], event_ids: ['E'], warnings: [] })
    }
    throw new Error(`Unexpected fetch: ${path}`)
  }))
  return posts
}

function renderPanel() {
  return render(
    <MemoryRouter>
      <CapabilitiesProvider>
        <CrewAssignmentPanel vehicleId="VEH-1048" />
      </CapabilitiesProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('CrewAssignmentPanel', () => {
  it('shows each person with their own role, note, interval and status; read-only without the TEST grant', async () => {
    installApi(['can_view'])
    renderPanel()
    expect(await screen.findByText('ช่าง เก้าหนึ่งหนึ่ง')).toBeInTheDocument()
    expect(screen.getByText(/อื่นๆ \(ผู้ช่วยยก\)/)).toBeInTheDocument()
    expect(screen.getByText(/ยืนยันตัวบุคคลไม่ได้/)).toBeInTheDocument()
    expect(screen.getByText(/24:00/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'เพิ่มทีมงาน' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'แก้ไข' })).not.toBeInTheDocument()
  })

  it('a can_assign_crane_driver holder alone still cannot write crew (OD-3 = A)', async () => {
    installApi(['can_view', 'can_assign_crane_driver'])
    renderPanel()
    await screen.findByText('ช่าง เก้าหนึ่งหนึ่ง')
    expect(screen.queryByRole('button', { name: 'เพิ่มทีมงาน' })).not.toBeInTheDocument()
  })

  it('a granted employee creates with a request id; only ACTIVE personnel are offered; OTHER needs a note', async () => {
    const user = userEvent.setup()
    const posts = installApi(['can_view', 'can_assign_crane_crew'])
    renderPanel()
    await user.click(await screen.findByRole('button', { name: 'เพิ่มทีมงาน' }))
    const select = screen.getByLabelText('บุคลากร') as HTMLSelectElement
    await waitFor(() => expect(select.options.length).toBe(2))
    expect([...select.options].map((o) => o.value)).toEqual(['', 'PER-TEST-912'])
    await user.selectOptions(select, 'PER-TEST-912')
    await user.selectOptions(screen.getByLabelText('บทบาท'), 'OTHER')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByText('บทบาท “อื่นๆ” ต้องระบุคำอธิบายบทบาท')).toBeInTheDocument()
    expect(posts).toHaveLength(0)
    await user.type(screen.getByLabelText('คำอธิบายบทบาท'), 'ผู้ช่วยผูกยึด')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    await screen.findByText('บันทึกแล้ว')
    expect(posts).toHaveLength(1)
    expect(posts[0].requestId).toMatch(/^[0-9a-f-]{36}$/)
    expect(posts[0].body).toMatchObject({ operation: 'CREATE', personnel_id: 'PER-TEST-912', crew_role: 'OTHER',
      crew_role_note_th: 'ผู้ช่วยผูกยึด', mode: 'FULL_DAY' })
  })

  it('an unknown outcome keeps the intent and the resend reuses the SAME request id (no duplicate)', async () => {
    const user = userEvent.setup()
    let attempt = 0
    const posts = installApi(['can_view', 'can_assign_crane_crew'], () => {
      attempt += 1
      return attempt === 1
        ? json({ error: { code: 'CREW_HISTORY_WRITE_FAILED', message: 'x', details: { history_write_outcome: 'unknown' } } }, 503)
        : json({ request_id: 'x', replayed: true, operation_id: 'O', record_ids: ['R'], event_ids: ['E'] })
    })
    renderPanel()
    await user.click(await screen.findByRole('button', { name: 'เพิ่มทีมงาน' }))
    await waitFor(() => expect((screen.getByLabelText('บุคลากร') as HTMLSelectElement).options.length).toBe(2))
    await user.selectOptions(screen.getByLabelText('บุคลากร'), 'PER-TEST-912')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    const resend = await screen.findByRole('button', { name: /ส่งคำขอเดิมอีกครั้ง/ })
    await user.click(resend)
    await screen.findByText('บันทึกแล้ว')
    expect(posts).toHaveLength(2)
    expect(posts[1].requestId).toBe(posts[0].requestId)
    expect(posts[1].body).toEqual(posts[0].body)
  })

  it('shows the Thai reason of a person-axis refusal', async () => {
    const user = userEvent.setup()
    installApi(['can_view', 'can_assign_crane_crew'], () =>
      json({ error: { code: 'RESOURCE_CONFLICT', message: 'x', details: { axis: 'PERSON' } } }, 409))
    renderPanel()
    await user.click(await screen.findByRole('button', { name: 'เพิ่มทีมงาน' }))
    await waitFor(() => expect((screen.getByLabelText('บุคลากร') as HTMLSelectElement).options.length).toBe(2))
    await user.selectOptions(screen.getByLabelText('บุคลากร'), 'PER-TEST-912')
    await user.click(screen.getByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByText(/ได้รับมอบหมายงานอื่นในช่วงเวลาที่ทับกันแล้ว/)).toBeInTheDocument()
  })
})
