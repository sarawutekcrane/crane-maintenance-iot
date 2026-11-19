import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { PartSetEditor } from './PartSetEditor'

// PG-5 P-A: the parts controls follow useTestGrantControlVisible (tested in MasterRecordForm.test.tsx);
// here it is controlled directly (true = legacy development mode / a grant holder in Access Management).
const visibility = vi.hoisted(() => ({ value: true }))
vi.mock('../lib/masterRecords', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/masterRecords')>()),
  useTestGrantControlVisible: () => visibility.value,
}))


// R8 PRE-UAT (workstream F) — the part-set editor over the existing routes. Synthetic data.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => vi.unstubAllGlobals())

describe('PartSetEditor', () => {
  it('creates a set, a revision with REQUIRED / ALTERNATIVE items and an applicability, each with a request id', async () => {
    const posts: { path: string; body: Record<string, unknown>; requestId: string | null }[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
      if (path === '/me') return json({ user_id: 'U', roles: [], capabilities: ['can_view'], is_dev_auth: true })
      if (path === '/part-sets/PS-1/active-revision') return json({ revision: { revision_id: 'R', revision_number: 1, effective_date: '2026-12-01' },
        items: [{ part_id: 'PART-0001', requirement: 'REQUIRED', quantity: 1, unit: 'ชิ้น' }] })
      if (init.method === 'POST') {
        posts.push({ path, body: JSON.parse(String(init.body)), requestId: new Headers(init.headers).get('X-Request-Id') })
        return json(path === '/part-sets' ? { part_set_id: 'PS-1' } : {})
      }
      throw new Error(`Unexpected fetch: ${path}`)
    }))
    render(<MemoryRouter><CapabilitiesProvider><PartSetEditor partId="PART-0001" /></CapabilitiesProvider></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('รหัสชุด'), 'SET-T')
    await userEvent.type(screen.getByLabelText('ชื่อชุด'), 'ชุดทดสอบ')
    await userEvent.click(screen.getByRole('button', { name: 'สร้างชุดอะไหล่' }))
    expect(await screen.findByText(/สร้างชุดอะไหล่แล้ว: PS-1/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'เพิ่มรายการ' }))
    await userEvent.type(screen.getByLabelText('รหัสอะไหล่ แถว 2'), 'PART-0002')
    await userEvent.selectOptions(screen.getByLabelText('ความจำเป็น แถว 2'), 'ALTERNATIVE')
    await userEvent.type(screen.getByLabelText('ทดแทนแถวที่ (เริ่ม 0) แถว 2'), '0')
    await userEvent.type(screen.getByLabelText('วันที่มีผล'), '2026-12-01')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึกฉบับปรับปรุง' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1].body).toEqual({ effective_date: '2026-12-01', items: [
      { part_id: 'PART-0001', requirement: 'REQUIRED', quantity: 1, unit: 'ชิ้น' },
      { part_id: 'PART-0002', requirement: 'OPTIONAL', quantity: 1, unit: 'ชิ้น' }].map((i, n) => n === 1
      ? { ...i, requirement: 'ALTERNATIVE', alternative_for_index: 0 } : i) })
    expect(await screen.findByText(/ฉบับที่ 1 มีผล 2026-12-01/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('รหัสรุ่น'), 'MODEL-0002')
    await userEvent.type(screen.getByLabelText('มีผลตั้งแต่'), '2026-12-01')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึกรุ่นที่ใช้ได้' }))
    await waitFor(() => expect(posts).toHaveLength(3))
    expect(posts[2]).toMatchObject({ path: '/part-sets/PS-1/applicability', body: { model_id: 'MODEL-0002', effective_from: '2026-12-01' } })
    expect(new Set(posts.map((p) => p.requestId)).size).toBe(3)
  })
})

describe('PartSetEditor — PG-5 visibility', () => {
  afterEach(() => { visibility.value = true; vi.unstubAllGlobals() })

  it('renders nothing for an Access Management user without can_test_manage_parts', async () => {
    visibility.value = false
    vi.stubGlobal('fetch', vi.fn(async () => json({ user_id: 'U', roles: [], capabilities: ['can_view'] })))
    const { container } = render(<MemoryRouter><CapabilitiesProvider><PartSetEditor partId="PART-0001" /></CapabilitiesProvider></MemoryRouter>)
    expect(container.querySelector('.part-set-editor')).toBeNull()
  })
})

describe('PartSetEditor — honest outcome after a lost answer (no server replay on create)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('never promises a safe resend for creating a set', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
      if (path === '/me') return json({ user_id: 'U', roles: [], capabilities: ['can_view'] })
      if (init.method === 'POST') throw new TypeError('network down')
      throw new Error(path)
    }))
    render(<MemoryRouter><CapabilitiesProvider><PartSetEditor partId="PART-0001" /></CapabilitiesProvider></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('รหัสชุด'), 'SET-X')
    await userEvent.type(screen.getByLabelText('ชื่อชุด'), 'ชุด')
    await userEvent.click(screen.getByRole('button', { name: 'สร้างชุดอะไหล่' }))
    expect(await screen.findByText(/ไม่มีการกันบันทึกซ้ำ/)).toBeInTheDocument()
    expect(screen.queryByText(/ส่งอีกครั้งได้อย่างปลอดภัย/)).not.toBeInTheDocument()
  })
})
