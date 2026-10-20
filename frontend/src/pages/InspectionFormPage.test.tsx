import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InspectionFormPage } from './InspectionFormPage'

// R3 (deliberate test migration, docs/project-governance/r3-implementation-contract.md
// §4–§6): the form now loads `GET /inspections/form` (today's due items for this
// asset), offers the four R3 results, requires a remark for both abnormal results
// (photo optional) and sends one X-Request-Id per submission intent. The former
// Phase 3 cases (active checklist per asset type, per-item remark flags) are superseded.

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function item(n: number, frequency: 'DAILY' | 'EVERY_7_DAYS') {
  return {
    item_id: `ITM-V-000${n}`,
    revision_id: 'REV-0001',
    sequence: n,
    title: `รายการตรวจสอบตัวอย่างที่ ${n}`,
    inspection_point: null,
    method: null,
    standard: null,
    instruction: null,
    frequency,
    required_photo_on_fail: true,
    required_remark_on_fail: false,
    is_critical: false,
    reference_image: null,
    item_key: `KEY-ITM-V-000${n}`,
  }
}

const formBody = {
  asset_type: 'VEHICLE',
  asset_id: 'VEH-1046',
  inspection_date: '2026-10-01',
  checklist: {
    checklist_id: 'CHK-0001',
    asset_type: 'VEHICLE',
    code: 'VEHICLE-PLACEHOLDER',
    name: 'รายการตรวจเช็คยานพาหนะ (ข้อมูลตัวอย่างชั่วคราวสำหรับพัฒนา/ทดสอบระบบ)',
  },
  revision: {
    revision_id: 'REV-0001',
    checklist_id: 'CHK-0001',
    revision_number: 1,
    effective_date: '2026-01-01',
    created_at: '2026-01-15T08:00:00Z',
  },
  items: [
    { item: item(1, 'DAILY'), due_reason: 'DAILY', last_result_date: null },
    { item: item(4, 'EVERY_7_DAYS'), due_reason: 'FIRST_WEEKLY', last_result_date: null },
  ],
  submitted_inspection_id: null,
}

const vehicleDetailBody = {
  vehicle: {
    vehicle_id: 'VEH-1046',
    machine_no: 'TC-12',
    model_id: 'MODEL-0001',
    serial_number: 'ZL-2021-0456',
    operational_status: 'WORKING',
    created_at: '2026-01-15T08:00:00Z',
    updated_at: '2026-01-15T08:00:00Z',
  },
  model: null,
  components: [],
}

const createdBody = {
  header: {
    inspection_id: 'INS-0001',
    asset_type: 'VEHICLE',
    asset_id: 'VEH-1046',
    checklist_id: 'CHK-0001',
    revision_id: 'REV-0001',
    revision_number: 1,
    submitted_at: '2026-10-01T00:00:00Z',
    inspector_user_id: 'dev-user',
    overall_remark: null,
  },
  items: [],
  findings: [],
}

type Call = { method: string; url: string; body?: unknown; requestId: string | null }

function stub(responses: { form?: unknown; formStatus?: number; post?: () => Response | Promise<Response> } = {}) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      const headers = (init?.headers ?? {}) as Record<string, string>
      calls.push({
        method,
        url,
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
        requestId: headers['X-Request-Id'] ?? null,
      })
      if (url.includes('/inspections/form')) return jsonResponse(responses.form ?? formBody, responses.formStatus ?? 200)
      if (url.includes('/vehicles/VEH-1046')) return jsonResponse(vehicleDetailBody)
      if (method === 'POST' && url.includes('/inspections')) {
        return responses.post ? responses.post() : jsonResponse(createdBody)
      }
      throw new Error(`Unexpected fetch: ${method} ${url}`)
    }),
  )
  return calls
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/inspect']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/inspect" element={<InspectionFormPage />} />
        <Route path="/inspections/:inspectionId" element={<p>inspection detail</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST')

describe('InspectionFormPage (R3)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("loads today's due items for this asset with the due reason and the observation note", async () => {
    const calls = stub()
    renderPage()
    await waitFor(() => expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument())
    expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 4')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /TC-12/ })).toBeInTheDocument()
    expect(screen.getAllByTestId('inspection-due-reason').map((e) => e.textContent)).toEqual([
      'รายวัน',
      'ทุก 7 วัน (ตรวจครั้งแรก)',
    ])
    expect(screen.getByTestId('inspection-observation-note')).toHaveTextContent('ไม่ใช่การรับรองความปลอดภัย')
    expect(calls[0].url).toContain('/inspections/form?asset_type=VEHICLE&asset_id=VEH-1046')
  })

  it('disables submit until every shown item has a result, then submits with an X-Request-Id', async () => {
    const user = userEvent.setup()
    const calls = stub()
    renderPage()
    await waitFor(() => expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument())
    const submit = screen.getByRole('button', { name: 'ส่งผลการตรวจ' })
    expect(submit).toBeDisabled()
    const normal = screen.getAllByRole('radio', { name: 'ปกติ' })
    await user.click(normal[0])
    expect(submit).toBeDisabled()
    await user.click(screen.getAllByRole('radio', { name: 'ไม่มีอุปกรณ์ติดตั้ง' })[1])
    expect(submit).toBeEnabled()
    await user.click(submit)
    await waitFor(() => expect(screen.getByText('inspection detail')).toBeInTheDocument())
    const [post] = posts(calls)
    expect(post.requestId).toMatch(/^[0-9a-f-]{36}$/)
    const body = post.body as { items: { item_id: string; result: string }[] }
    expect(body.items).toEqual([
      expect.objectContaining({ item_id: 'ITM-V-0001', result: 'PASS' }),
      expect.objectContaining({ item_id: 'ITM-V-0004', result: 'NOT_INSTALLED' }),
    ])
  })

  it.each(['ผิดปกติ', 'ใช้งานได้รอการแก้ไข'])(
    'R3-15: %s blocks submission until a remark is entered (photo optional)',
    async (label) => {
      const user = userEvent.setup()
      const calls = stub()
      renderPage()
      await waitFor(() => expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument())
      await user.click(screen.getAllByRole('radio', { name: label })[0])
      await user.click(screen.getAllByRole('radio', { name: 'ปกติ' })[1])
      expect(screen.getByText('รูปถ่ายหลักฐาน (ถ้ามี)')).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: 'ส่งผลการตรวจ' }))
      expect(screen.getByText('กรุณาระบุหมายเหตุเมื่อผลตรวจผิดปกติหรือใช้งานได้รอการแก้ไข')).toBeInTheDocument()
      expect(posts(calls)).toHaveLength(0)
      await user.type(screen.getByLabelText('หมายเหตุ (จำเป็น)'), 'น้ำมันรั่ว')
      await user.click(screen.getByRole('button', { name: 'ส่งผลการตรวจ' }))
      await waitFor(() => expect(posts(calls)).toHaveLength(1))
    },
  )

  it('a retry after a transport failure reuses the same request id; an edited answer starts a new intent', async () => {
    const user = userEvent.setup()
    let attempt = 0
    const calls = stub({
      post: () => {
        attempt += 1
        if (attempt <= 2) throw new Error('network down')
        return jsonResponse(createdBody)
      },
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument())
    for (const radio of screen.getAllByRole('radio', { name: 'ปกติ' })) await user.click(radio)
    await user.click(screen.getByRole('button', { name: 'ส่งผลการตรวจ' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('ระบบจะไม่บันทึกซ้ำ'))
    await user.click(screen.getByRole('button', { name: 'ส่งผลการตรวจ' }))
    await waitFor(() => expect(posts(calls)).toHaveLength(2))
    expect(posts(calls)[1].requestId).toBe(posts(calls)[0].requestId)
    await user.click(screen.getAllByRole('radio', { name: 'ไม่มีอุปกรณ์ติดตั้ง' })[0])
    await user.click(screen.getByRole('button', { name: 'ส่งผลการตรวจ' }))
    await waitFor(() => expect(posts(calls)).toHaveLength(3))
    expect(posts(calls)[2].requestId).not.toBe(posts(calls)[0].requestId)
  })

  it('shows that today is already submitted and offers no answers', async () => {
    stub({ form: { ...formBody, submitted_inspection_id: 'INS-0042' } })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('inspection-already-submitted')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'ดูผลการตรวจของวันนี้' })).toHaveAttribute('href', '/inspections/INS-0042')
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ส่งผลการตรวจ' })).toBeDisabled()
  })

  it('a competing same-day submission shows the Thai message and the existing inspection', async () => {
    const user = userEvent.setup()
    stub({
      post: () =>
        jsonResponse(
          { error: { code: 'INSPECTION_ALREADY_SUBMITTED_TODAY', message: 'x', details: { inspection_id: 'INS-0007' } } },
          409,
        ),
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument())
    for (const radio of screen.getAllByRole('radio', { name: 'ปกติ' })) await user.click(radio)
    await user.click(screen.getByRole('button', { name: 'ส่งผลการตรวจ' }))
    await waitFor(() => expect(screen.getByTestId('inspection-already-submitted')).toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent('วันนี้มีการส่งผลตรวจของเครื่องนี้แล้ว')
  })

  it('an asset without a checklist shows the explicit missing-checklist message', async () => {
    stub({
      form: { error: { code: 'MISSING_CHECKLIST', message: 'x', details: null } },
      formStatus: 404,
    })
    renderPage()
    await waitFor(() => expect(screen.getByText(/ยังไม่มีรายการตรวจเช็คที่กำหนดให้กับรุ่นหรือเครื่องนี้/)).toBeInTheDocument())
  })
})
