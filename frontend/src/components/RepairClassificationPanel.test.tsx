import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { RepairClassificationPanel } from './RepairClassificationPanel'

// R8 PRE-UAT (Owner Decision 2) — TEST classification panel (TEST-CANDIDATE-R1 subset). Synthetic data only.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const CATALOGUE = {
  summary: { candidates: 24, relationships: 205 },
  tree: [{ code: 'ELE', name: 'ไฟฟ้าและอิเล็กทรอนิกส์', assemblies: [{ code: 'AC', name: 'ระบบปรับอากาศ', points: [
    { code: 'P082', name: 'พัดลมแอร์', relationship: 'ELE-AC-P082', allowed_symptoms: ['S01'] }] }] }],
  symptoms: { S01: 'ไม่ทำงาน', S02: 'รั่วซึม', S03: 'แตกหัก', S04: 'สึกหรอ', S05: 'ผิดปกติ' },
  actions: { A01: 'ตรวจสอบ', A03: 'เปลี่ยน' },
  excluded: [], position_fields: { side: ['LEFT', 'RIGHT'], axle: null },
}
function view(state: string, extra: Record<string, unknown> = {}) {
  return { repair_id: 'RPR-1', state, blockers: [], draft_revision: 0, draft_rows: [], final: null, replayed: false,
    note_th: 'TEST candidate — ไม่อนุมัติสำหรับ REAL', ...extra }
}

function installApi(caps: string[], current: Record<string, unknown>, post?: (path: string, body: unknown) => Response) {
  const posts: { path: string; body: Record<string, unknown>; requestId: string | null }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
    if (path === '/me') return json({ user_id: 'USR-1', roles: [], capabilities: caps, is_dev_auth: true })
    if (path === '/repairs/RPR-1/classification') return json(current)
    if (path === '/repair-classification/catalogue') return json(CATALOGUE)
    if (init.method === 'POST') {
      const body = JSON.parse(String(init.body))
      posts.push({ path, body, requestId: new Headers(init.headers).get('X-Request-Id') })
      return post ? post(path, body) : json(current)
    }
    throw new Error(`Unexpected fetch: ${path}`)
  }))
  return posts
}

function renderPanel() {
  return render(<MemoryRouter><CapabilitiesProvider><RepairClassificationPanel repairId="RPR-1" /></CapabilitiesProvider></MemoryRouter>)
}

afterEach(() => vi.unstubAllGlobals())

describe('RepairClassificationPanel', () => {
  it('shows the TEST label and the store blocker while reconciliation is pending', async () => {
    installApi(['can_view', 'can_test_classify_repair'], view('BLOCKED_STORE_UNRECONCILED', { blockers: ['RETURN_NOT_ACCEPTED'] }))
    renderPanel()
    expect(await screen.findByText(/รอกระทบยอดอะไหล่/)).toBeInTheDocument()
    expect(screen.getByText(/แจ้งคืนแล้วแต่คลังยังไม่รับ/)).toBeInTheDocument()
    expect(screen.getByText('TEST candidate — ไม่อนุมัติสำหรับ REAL')).toBeInTheDocument()
    expect(screen.queryByLabelText('1 ระบบหลัก')).not.toBeInTheDocument()
  })

  it('stages a row through dependent dropdowns (symptom and action separate) and finalizes', async () => {
    const staged = view('WAITING_FOR_CLASSIFICATION', { draft_revision: 1, draft_rows: [{ code: 'ELE-AC-P082', system: 'ELE',
      assembly: 'AC', point: 'P082', symptoms: ['S01'], actions: ['A03'], position: { side: 'LEFT' } }] })
    const classified = view('CLASSIFIED', { draft_revision: 1, final: { rows: staged.draft_rows } })
    const posts = installApi(['can_view', 'can_test_classify_repair'], view('WAITING_FOR_CLASSIFICATION'),
      (path) => json(path.endsWith('drafts') ? staged : classified))
    renderPanel()
    await userEvent.selectOptions(await screen.findByLabelText('1 ระบบหลัก'), 'ELE')
    await userEvent.selectOptions(screen.getByLabelText('2 ชุดอุปกรณ์'), 'AC')
    await userEvent.selectOptions(screen.getByLabelText('3 จุดที่ผิดปกติ'), 'P082')
    expect(screen.queryByLabelText(/S02 — รั่วซึม/)).not.toBeInTheDocument() // only allowed symptoms are offered
    await userEvent.click(screen.getByLabelText('S01 — ไม่ทำงาน'))
    await userEvent.click(screen.getByLabelText('A03 — เปลี่ยน'))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /ซ้าย\/ขวา/ }), 'LEFT')
    await userEvent.click(screen.getByRole('button', { name: 'เพิ่มจุดเสียในรายการ' }))
    await userEvent.click(screen.getByRole('button', { name: /บันทึกร่าง/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toEqual({ expected_revision: 0, rows: [{ system: 'ELE', assembly: 'AC', point: 'P082',
      symptoms: ['S01'], actions: ['A03'], position: { side: 'LEFT' } }] })
    await userEvent.click(await screen.findByRole('button', { name: 'ยืนยันจัดประเภท' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1]).toMatchObject({ path: '/repairs/RPR-1/classification-finalizations', body: { expected_revision: 1 } })
    expect(await screen.findByText(/จัดประเภทแล้ว/)).toBeInTheDocument()
  })

  it('explains a fail-closed rejection from the server', async () => {
    installApi(['can_view', 'can_test_classify_repair'], view('WAITING_FOR_CLASSIFICATION'),
      () => json({ error: { code: 'REPAIR_CODE_ENTRY_NOT_IN_TEST_SUBSET', message: 'x', request_id: 'r' } }, 422))
    renderPanel()
    await userEvent.selectOptions(await screen.findByLabelText('1 ระบบหลัก'), 'ELE')
    await userEvent.selectOptions(screen.getByLabelText('2 ชุดอุปกรณ์'), 'AC')
    await userEvent.selectOptions(screen.getByLabelText('3 จุดที่ผิดปกติ'), 'P082')
    await userEvent.click(screen.getByLabelText('S01 — ไม่ทำงาน'))
    await userEvent.click(screen.getByLabelText('A01 — ตรวจสอบ'))
    await userEvent.click(screen.getByRole('button', { name: 'เพิ่มจุดเสียในรายการ' }))
    await userEvent.click(screen.getByRole('button', { name: /บันทึกร่าง/ }))
    expect(await screen.findByText(/ไม่อยู่ในชุดทดสอบ/)).toBeInTheDocument()
  })

  it('is read-only without the classifier grant', async () => {
    installApi(['can_view'], view('WAITING_FOR_CLASSIFICATION'))
    renderPanel()
    expect(await screen.findByText(/รอผู้ได้รับมอบหมายจัดประเภท/)).toBeInTheDocument()
    expect(screen.queryByLabelText('1 ระบบหลัก')).not.toBeInTheDocument()
  })

  it('does not allow finalizing while rows differ from the saved draft (independent review)', async () => {
    const staged = view('WAITING_FOR_CLASSIFICATION', { draft_revision: 1, draft_rows: [{ code: 'ELE-AC-P082', system: 'ELE',
      assembly: 'AC', point: 'P082', symptoms: ['S01'], actions: ['A03'], position: {} }] })
    const posts = installApi(['can_view', 'can_test_classify_repair'], staged)
    renderPanel()
    expect(await screen.findByRole('button', { name: 'ยืนยันจัดประเภท' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'ลบ' })) // a local, unsaved change
    expect(screen.getByRole('button', { name: 'ยืนยันจัดประเภท' })).toBeDisabled()
    expect(screen.getByText(/บันทึกร่างก่อน แล้วจึงยืนยันจัดประเภท/)).toBeInTheDocument()
    expect(posts).toHaveLength(0)
  })

  it('renders nothing on a repository without the feature (501)', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
      if (path === '/me') return json({ user_id: 'U', roles: [], capabilities: [] })
      return json({ error: { code: 'FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE', message: 'x', request_id: 'r' } }, 501)
    }))
    const { container } = renderPanel()
    await new Promise((r) => setTimeout(r, 30))
    expect(container.querySelector('.classification-panel')).toBeNull()
  })
})
