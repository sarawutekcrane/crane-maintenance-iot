import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ModelDocumentsPage } from './ModelDocumentsPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function errorResponse(code: string, status = 422) {
  return jsonResponse({ error: { code, message: code, request_id: 'req-1' } }, status)
}

const historyBody = [
  {
    model_document_id: 'MDOC-0002',
    model_id: 'MODEL-0001',
    document_type: 'LOAD_CHART',
    document_name_th: 'ตารางยกของ',
    version: '2.0',
    effective_from: '2026-01-01',
    effective_to: null,
    storage_ref: 'attachments/load-chart-v2.pdf',
    file_status: 'UPLOADED',
    active_status: 'ACTIVE',
    replaced_by_document_id: null,
    note_th: null,
  },
  {
    model_document_id: 'MDOC-0001',
    model_id: 'MODEL-0001',
    document_type: 'SERVICE_MANUAL',
    document_name_th: 'คู่มือซ่อมบำรุง',
    version: '001',
    effective_from: null,
    effective_to: null,
    storage_ref: null,
    file_status: null,
    active_status: null,
    replaced_by_document_id: null,
    note_th: null,
  },
]

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/models/MODEL-0001/documents']}>
      <Routes>
        <Route path="/models/:modelId/documents" element={<ModelDocumentsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ModelDocumentsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows every document ever created for the model — history is never hidden', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(historyBody)))

    renderPage()

    await waitFor(() => expect(screen.getByText('ตารางยกของ')).toBeInTheDocument())
    expect(screen.getByText('คู่มือซ่อมบำรุง')).toBeInTheDocument()
    expect(screen.getByText('001')).toBeInTheDocument()
    // Document IDs are now shown explicitly (Batch 3B requirement).
    expect(screen.getByText('MDOC-0002')).toBeInTheDocument()
    expect(screen.getByText('MDOC-0001')).toBeInTheDocument()
  })

  it('creates a document via POST', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({
          method,
          url,
          body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
        })
        if (method === 'GET') return jsonResponse([])
        if (method === 'POST' && url.includes('/documents')) {
          return jsonResponse({
            ...historyBody[0],
            model_document_id: 'MDOC-0003',
            version: '1.0',
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('+ เพิ่มเอกสาร')).toBeInTheDocument())
    await user.click(screen.getByText('+ เพิ่มเอกสาร'))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่'), '1.0')
    await user.click(screen.getByText('บันทึก'))

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.url.includes('/models/MODEL-0001/documents')),
      ).toBe(true),
    )
    const createCall = calls.find((c) => c.method === 'POST')
    expect(createCall?.body).toMatchObject({ version: '1.0' })
  })

  it('shows a Thai error message with request id when the load fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { error: { code: 'MODEL_NOT_FOUND', message: 'not found', request_id: 'req-1' } },
          404,
        ),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่พบข้อมูลรุ่นเครื่องจักรนี้')).toBeInTheDocument())
  })

  it('never renders a delete or upload control', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(historyBody)))

    renderPage()

    await waitFor(() => expect(screen.getByText('ตารางยกของ')).toBeInTheDocument())
    expect(screen.queryByText(/ลบเอกสาร|อัปโหลดไฟล์/)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Web/API Phase 6 Batch 3B / 6F — revision UI
// ---------------------------------------------------------------------------

const lifecycleHistoryBody = [
  {
    model_document_id: 'MDOC-0004',
    model_id: 'MODEL-0001',
    document_type: 'LOAD_CHART',
    document_name_th: 'ตารางยกของ (ปัจจุบัน)',
    version: '2.0',
    effective_from: '2026-06-01',
    effective_to: null,
    storage_ref: 'attachments/load-chart-v2.pdf',
    file_status: 'UPLOADED',
    // Seeded non-null so tests can prove none of these three are ever
    // inherited into a revision — a blank revise input must not be
    // confused with "this source simply has no value here".
    active_status: 'ACTIVE',
    replaced_by_document_id: null,
    note_th: 'หมายเหตุต้นทาง (ห้ามสืบทอด)',
  },
  {
    model_document_id: 'MDOC-0003',
    model_id: 'MODEL-0001',
    document_type: 'LOAD_CHART',
    document_name_th: 'ตารางยกของ (ใหม่)',
    version: '1.5',
    effective_from: '2026-06-01',
    effective_to: null,
    storage_ref: null,
    file_status: null,
    active_status: null,
    replaced_by_document_id: null,
    note_th: null,
  },
  {
    model_document_id: 'MDOC-0002',
    model_id: 'MODEL-0001',
    document_type: 'LOAD_CHART',
    document_name_th: 'ตารางยกของ (เดิม)',
    version: '1.0',
    effective_from: '2026-01-01',
    effective_to: '2026-05-31',
    storage_ref: null,
    file_status: null,
    active_status: null,
    replaced_by_document_id: 'MDOC-0003',
    note_th: null,
  },
  {
    model_document_id: 'MDOC-0001',
    model_id: 'MODEL-0001',
    document_type: 'SERVICE_MANUAL',
    document_name_th: 'คู่มือซ่อมบำรุง',
    version: '001',
    effective_from: null,
    effective_to: null,
    storage_ref: null,
    file_status: null,
    active_status: null,
    replaced_by_document_id: null,
    note_th: null,
  },
]

function stubLifecycleFetch(
  handlePost: (url: string, body: unknown) => Response | Promise<Response>,
  calls: { method: string; url: string; body?: unknown }[] = [],
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    calls.push({ method, url, body })
    if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
    if (method === 'POST' && url.includes('/revise')) return handlePost(url, body)
    throw new Error(`Unexpected fetch: ${method} ${url}`)
  })
}

/** Finds a card by an ID/version string that might ALSO appear elsewhere on
 * the page as a successor `<a>` link's text (so a bare `getByText` would be
 * ambiguous) — picks the non-link occurrence, which is the card's own row. */
function findCardByOwnText(text: string): HTMLElement {
  return screen
    .getAllByText(text)
    .find((el) => el.tagName !== 'A')!
    .closest('.card') as HTMLElement
}

function openButtonFor(card: HTMLElement): HTMLElement {
  return screen
    .getAllByText('สร้างเอกสารฉบับปรับปรุง')
    .find((el) => el.closest('.card') === card) as HTMLElement
}

describe('ModelDocumentsPage revision', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows document IDs and the replaced_by_document_id successor link on history cards', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(lifecycleHistoryBody)))

    renderPage()

    await waitFor(() => expect(screen.getByText('ถูกแทนที่ด้วยฉบับปรับปรุง')).toBeInTheDocument())
    const successorLink = screen.getByRole('link', { name: 'MDOC-0003' })
    expect(successorLink).toHaveAttribute('href', '#model-document-MDOC-0003')
  })

  it('offers the revision action only for a source with an effective_from and no successor', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(lifecycleHistoryBody)))

    renderPage()

    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    // MDOC-0004 (eligible) and MDOC-0003 (eligible) both offer the action;
    // MDOC-0002 (already replaced) and MDOC-0001 (missing effective_from) do not.
    expect(screen.getAllByText('สร้างเอกสารฉบับปรับปรุง').length).toBe(2)
  })

  it('explains in Thai that a missing effective_from blocks revision, without inventing a date', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(lifecycleHistoryBody)))

    renderPage()

    await waitFor(() => expect(screen.getByText('คู่มือซ่อมบำรุง')).toBeInTheDocument())
    const card = screen.getByText('คู่มือซ่อมบำรุง').closest('.card') as HTMLElement
    expect(card.textContent).toContain('ยังไม่มีวันที่เริ่มมีผลใช้')
  })

  it('sends only the frozen allowed keys to the source-specific revise route, omitting inherited fields', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      stubLifecycleFetch(
        () => jsonResponse({ ...lifecycleHistoryBody[0], model_document_id: 'MDOC-0005' }),
        calls,
      ),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())

    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(card))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/revise'))).toBe(true),
    )
    const call = calls.find((c) => c.method === 'POST')!
    expect(call.url).toContain('/model-documents/MDOC-0004/revise')
    expect(call.body).toEqual({ version: '3.0', effective_from: '2026-07-01' })
    // Forbidden/backend-owned fields must never appear.
    for (const forbidden of [
      'model_document_id',
      'model_id',
      'document_type',
      'effective_to',
      'replaced_by_document_id',
    ]) {
      expect(call.body).not.toHaveProperty(forbidden)
    }
  })

  it('preserves the exact opaque version string and blocks a blank or duplicate version client-side', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      stubLifecycleFetch(
        () => jsonResponse({ ...lifecycleHistoryBody[0], model_document_id: 'MDOC-0005' }),
        calls,
      ),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(card))

    // Blank version is rejected without ever calling the API.
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))
    expect(screen.getByText('กรุณากรอกเวอร์ชัน/ฉบับที่ของเอกสารฉบับใหม่')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').length).toBe(0)

    // Exact duplicate of the source version ("2.0") is rejected client-side too.
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '2.0')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))
    expect(
      screen.getByText('เวอร์ชัน/ฉบับที่ใหม่ต้องไม่ซ้ำกับเวอร์ชันเดิมของเอกสารต้นทาง'),
    ).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').length).toBe(0)

    // An opaque, non-normalized version string is sent exactly as typed.
    await user.clear(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '  Rev.B ')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(1))
    const call = calls.find((c) => c.method === 'POST')!
    expect(call.body).toMatchObject({ version: '  Rev.B ' })
  })

  it('supports inherit (omit), explicit set, and explicit clear for document_name_th and active_status without normalizing supplied strings', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      stubLifecycleFetch(
        () => jsonResponse({ ...lifecycleHistoryBody[0], model_document_id: 'MDOC-0005' }),
        calls,
      ),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    const openForm = async () => {
      await user.click(openButtonFor(card))
      await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
      await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    }

    // 1) inherit (default) -> key omitted entirely for both fields.
    await openForm()
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(1))
    expect(calls.filter((c) => c.method === 'POST').at(-1)!.body).not.toHaveProperty('document_name_th')
    expect(calls.filter((c) => c.method === 'POST').at(-1)!.body).not.toHaveProperty('active_status')

    // 2) explicit set -> exact string sent, INCLUDING leading/trailing
    // whitespace the user typed — never trimmed/normalized.
    await openForm()
    await user.selectOptions(screen.getByLabelText('ชื่อเอกสาร (ภาษาไทย)'), 'set')
    await user.type(screen.getByLabelText('ชื่อเอกสารใหม่'), '  ชื่อใหม่ที่มีช่องว่าง  ')
    await user.selectOptions(screen.getByLabelText('สถานะการใช้งาน'), 'set')
    await user.type(screen.getByLabelText('สถานะการใช้งานใหม่'), '  DRAFT  ')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(2))
    expect(calls.filter((c) => c.method === 'POST').at(-1)!.body).toMatchObject({
      document_name_th: '  ชื่อใหม่ที่มีช่องว่าง  ',
      active_status: '  DRAFT  ',
    })

    // 3) explicit clear -> literal null sent, distinct from omission.
    await openForm()
    await user.selectOptions(screen.getByLabelText('ชื่อเอกสาร (ภาษาไทย)'), 'clear')
    await user.selectOptions(screen.getByLabelText('สถานะการใช้งาน'), 'clear')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(3))
    const clearBody = calls.filter((c) => c.method === 'POST').at(-1)!.body as Record<string, unknown>
    expect(clearBody.document_name_th).toBeNull()
    expect(clearBody.active_status).toBeNull()
    expect('document_name_th' in clearBody).toBe(true)
    expect('active_status' in clearBody).toBe(true)
  })

  it('blocks an untouched blank "set" value from silently clearing an inherited field', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []
    vi.stubGlobal('fetch', stubLifecycleFetch(() => jsonResponse(lifecycleHistoryBody[0]), calls))

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(card))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.selectOptions(screen.getByLabelText('ชื่อเอกสาร (ภาษาไทย)'), 'set')
    // Leave the new-name input blank, then submit.
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

    expect(
      screen.getByText('กรุณากรอกชื่อเอกสารใหม่ หรือเลือก "คงค่าเดิม" / "ล้างค่า" แทน'),
    ).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').length).toBe(0)
  })

  it('never inherits storage_ref/file_status/note_th from a source with all three set — inputs start blank and an untouched blank omits all three', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      stubLifecycleFetch(
        () => jsonResponse({ ...lifecycleHistoryBody[0], model_document_id: 'MDOC-0005' }),
        calls,
      ),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(card))

    // The source (MDOC-0004) has non-null storage_ref, file_status AND
    // note_th seeded — none of the three are pre-filled here.
    expect((screen.getByLabelText('ไฟล์แนบใหม่ (storage_ref)') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('สถานะไฟล์ใหม่') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('หมายเหตุใหม่') as HTMLTextAreaElement).value).toBe('')

    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    // All three left untouched (blank).
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/revise'))).toBe(true),
    )
    const call = calls.find((c) => c.method === 'POST')!
    expect(call.body).not.toHaveProperty('storage_ref')
    expect(call.body).not.toHaveProperty('file_status')
    expect(call.body).not.toHaveProperty('note_th')
  })

  it('sends storage_ref/file_status/note_th with exact leading/trailing whitespace preserved when supplied', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      stubLifecycleFetch(
        () => jsonResponse({ ...lifecycleHistoryBody[0], model_document_id: 'MDOC-0005' }),
        calls,
      ),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(card))

    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.type(screen.getByLabelText('ไฟล์แนบใหม่ (storage_ref)'), '  files/new.pdf  ')
    await user.type(screen.getByLabelText('สถานะไฟล์ใหม่'), '  UPLOADED  ')
    await user.type(screen.getByLabelText('หมายเหตุใหม่'), '  หมายเหตุใหม่  ')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/revise'))).toBe(true),
    )
    const call = calls.find((c) => c.method === 'POST')!
    expect(call.body).toMatchObject({
      storage_ref: '  files/new.pdf  ',
      file_status: '  UPLOADED  ',
      note_th: '  หมายเหตุใหม่  ',
    })
  })

  it('closes the form and refreshes via GET on success, showing the old row\'s successor link AND the new row', async () => {
    const user = userEvent.setup()
    let getCount = 0
    const updatedList = [
      { ...lifecycleHistoryBody[0], replaced_by_document_id: 'MDOC-0005', effective_to: '2026-06-30' },
      {
        ...lifecycleHistoryBody[0],
        model_document_id: 'MDOC-0005',
        version: '3.0',
        effective_from: '2026-07-01',
        effective_to: null,
        replaced_by_document_id: null,
        note_th: null,
      },
      lifecycleHistoryBody[1],
      lifecycleHistoryBody[2],
      lifecycleHistoryBody[3],
    ]

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (method === 'GET') {
          getCount += 1
          return jsonResponse(getCount === 1 ? lifecycleHistoryBody : updatedList)
        }
        if (method === 'POST' && url.includes('/revise')) {
          return jsonResponse({ ...lifecycleHistoryBody[0], model_document_id: 'MDOC-0005', version: '3.0' })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(card))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

    await waitFor(() => expect(findCardByOwnText('MDOC-0005')).toBeTruthy())
    expect(screen.queryByText('ยืนยันสร้างฉบับปรับปรุง')).not.toBeInTheDocument()

    // The old row now shows the successor link to the new row...
    const oldCard = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    expect(oldCard.textContent).toContain('ถูกแทนที่ด้วยฉบับปรับปรุง')
    expect(within(oldCard).getByRole('link', { name: 'MDOC-0005' })).toHaveAttribute(
      'href',
      '#model-document-MDOC-0005',
    )
    // ...and the new row itself is visible with its own version.
    const newCard = findCardByOwnText('MDOC-0005')
    expect(within(newCard).getByText('3.0')).toBeInTheDocument()
  })

  it('shows the mapped Thai validation/conflict error and preserves inputs (definite rejection, no uncertain-outcome refresh action)', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      stubLifecycleFetch(() => errorResponse('MODEL_DOCUMENT_VERSION_DUPLICATE')),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(card))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

    await waitFor(() =>
      expect(
        screen.getByText('เวอร์ชัน/ฉบับที่ของฉบับใหม่ต้องไม่ซ้ำกับเวอร์ชันของเอกสารต้นทาง'),
      ).toBeInTheDocument(),
    )
    // The form stays open with the entered values untouched.
    expect((screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่') as HTMLInputElement).value).toBe('3.0')
    expect((screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่') as HTMLInputElement).value).toBe(
      '2026-07-01',
    )
    // A definite, sub-500 validation rejection is never treated as an
    // uncertain outcome — no GET-only refresh escape hatch is offered.
    expect(screen.queryByText('รีเฟรชประวัติ')).not.toBeInTheDocument()
  })

  it('prevents a second submission while one is pending (no automatic retry)', async () => {
    let resolvePost!: (value: Response) => void
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
        if (method === 'POST' && url.includes('/revise')) {
          return new Promise<Response>((resolve) => {
            resolvePost = resolve
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    fireEvent.click(openButtonFor(card))

    fireEvent.change(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), { target: { value: '3.0' } })
    fireEvent.change(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), {
      target: { value: '2026-07-01' },
    })

    const submitButton = screen.getByText('ยืนยันสร้างฉบับปรับปรุง')
    fireEvent.click(submitButton)
    fireEvent.click(submitButton)
    fireEvent.click(submitButton)

    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(1))
    resolvePost(jsonResponse({ ...lifecycleHistoryBody[0], model_document_id: 'MDOC-0005' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(1))
  })

  it('blocks opening a different document while a revision POST is pending, and only that pending document\'s workflow completes on success', async () => {
    const user = userEvent.setup()
    let resolvePost!: (value: Response) => void
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
        if (method === 'POST' && url.includes('/model-documents/MDOC-0004/revise')) {
          return new Promise<Response>((resolve) => {
            resolvePost = resolve
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())

    // Submit A (MDOC-0004) — leaves the POST pending.
    const cardA = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(cardA))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(1))

    // Attempt to open B (MDOC-0003) while A is pending — the open button
    // is disabled, and clicking it (even forcibly via fireEvent) must not
    // open a second form.
    const cardB = findCardByOwnText('MDOC-0003')
    const openB = openButtonFor(cardB)
    expect(openB).toBeDisabled()
    fireEvent.click(openB)
    expect(screen.getAllByLabelText('เวอร์ชัน/ฉบับที่ใหม่').length).toBe(1)
    expect((screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่') as HTMLInputElement).value).toBe('3.0')

    // Resolve A's request successfully.
    resolvePost(jsonResponse({ ...lifecycleHistoryBody[0], model_document_id: 'MDOC-0005' }))
    await waitFor(() => expect(screen.queryByText('ยืนยันสร้างฉบับปรับปรุง')).not.toBeInTheDocument())
    // Only A's workflow ever ran: exactly one POST total.
    expect(calls.filter((c) => c.method === 'POST').length).toBe(1)
  })

  it('keeps a POST error associated with the originally-submitted document, never leaking onto another form', async () => {
    const user = userEvent.setup()
    let resolvePost!: (value: Response) => void
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
        if (method === 'POST' && url.includes('/model-documents/MDOC-0004/revise')) {
          return new Promise<Response>((resolve) => {
            resolvePost = resolve
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const cardA = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(cardA))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(1))

    // While pending, attempt (and fail) to open a different document.
    const cardB = findCardByOwnText('MDOC-0003')
    fireEvent.click(openButtonFor(cardB))

    // A's request finally fails with a definite validation error.
    resolvePost(errorResponse('MODEL_DOCUMENT_VERSION_DUPLICATE'))

    await waitFor(() =>
      expect(
        screen.getByText('เวอร์ชัน/ฉบับที่ของฉบับใหม่ต้องไม่ซ้ำกับเวอร์ชันของเอกสารต้นทาง'),
      ).toBeInTheDocument(),
    )
    // The error renders inside A's own card, and A's input is preserved.
    expect(cardA.textContent).toContain('เวอร์ชัน/ฉบับที่ของฉบับใหม่ต้องไม่ซ้ำกับเวอร์ชันของเอกสารต้นทาง')
    expect((screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่') as HTMLInputElement).value).toBe('3.0')
    // B's form never opened at any point.
    expect(screen.getAllByLabelText('เวอร์ชัน/ฉบับที่ใหม่').length).toBe(1)
  })

  it('drops a stale revise response instead of overwriting a different model that was navigated to while it was pending', async () => {
    const user = userEvent.setup()
    let resolvePost!: (value: Response) => void
    const calls: { method: string; url: string }[] = []

    const model1Body = [lifecycleHistoryBody[0]]
    const model2Body = [
      {
        model_document_id: 'MDOC-9001',
        model_id: 'MODEL-0002',
        document_type: 'LOAD_CHART',
        document_name_th: 'เอกสารของรุ่นเครื่องจักรอื่น',
        version: '1.0',
        effective_from: '2026-01-01',
        effective_to: null,
        storage_ref: null,
        file_status: null,
        active_status: null,
        replaced_by_document_id: null,
        note_th: null,
      },
    ]

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET' && url.includes('/models/MODEL-0001/documents')) {
          return jsonResponse(model1Body)
        }
        if (method === 'GET' && url.includes('/models/MODEL-0002/documents')) {
          return jsonResponse(model2Body)
        }
        if (method === 'POST' && url.includes('/model-documents/MDOC-0004/revise')) {
          return new Promise<Response>((resolve) => {
            resolvePost = resolve
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    function Harness() {
      const navigate = useNavigate()
      return (
        <>
          <button type="button" onClick={() => navigate('/models/MODEL-0002/documents')}>
            ไปที่รุ่นเครื่องจักรอื่น (ทดสอบ)
          </button>
          <ModelDocumentsPage />
        </>
      )
    }
    render(
      <MemoryRouter initialEntries={['/models/MODEL-0001/documents']}>
        <Routes>
          <Route path="/models/:modelId/documents" element={<Harness />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const cardA = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(cardA))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').length).toBe(1))

    const model1GetCount = calls.filter(
      (c) => c.method === 'GET' && c.url.includes('MODEL-0001'),
    ).length

    // Navigate to a different model's documents page — same route pattern,
    // same mounted ModelDocumentsPage instance, only the modelId param
    // changes — while the revise POST for MODEL-0001/MDOC-0004 is still
    // pending.
    await user.click(screen.getByText('ไปที่รุ่นเครื่องจักรอื่น (ทดสอบ)'))
    await waitFor(() => expect(screen.getByText('เอกสารของรุ่นเครื่องจักรอื่น')).toBeInTheDocument())

    // The page-wide pending flag persisted across the navigation (proving
    // this really is the same component instance, not a remount) — model
    // 2's own revise action is still blocked by A's still-pending request.
    const model2OpenButton = screen.getByText('สร้างเอกสารฉบับปรับปรุง')
    expect(model2OpenButton).toBeDisabled()

    // Now resolve the STALE request for MODEL-0001's document successfully.
    resolvePost(jsonResponse({ ...model1Body[0], model_document_id: 'MDOC-0005' }))

    // The pending flag clears once the stale response resolves and is
    // recognized as stale...
    await waitFor(() => expect(screen.getByText('สร้างเอกสารฉบับปรับปรุง')).not.toBeDisabled())
    // ...but model 2's own displayed document is completely untouched by
    // it: no fetch/overwrite bound to the old model ever happened.
    expect(screen.getByText('เอกสารของรุ่นเครื่องจักรอื่น')).toBeInTheDocument()
    expect(screen.queryByText('MDOC-0004')).not.toBeInTheDocument()
    expect(
      calls.filter((c) => c.method === 'GET' && c.url.includes('MODEL-0001')).length,
    ).toBe(model1GetCount)
  })

  it('offers a GET-only retry (never another revision POST) when the post-success list refresh fails', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string }[] = []
    let getCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') {
          getCount += 1
          if (getCount === 1) return jsonResponse(lifecycleHistoryBody)
          return jsonResponse({ error: { code: 'MODEL_NOT_FOUND', message: 'x' } }, 404)
        }
        if (method === 'POST' && url.includes('/revise')) {
          return jsonResponse({ ...lifecycleHistoryBody[0], model_document_id: 'MDOC-0005' })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(card))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

    // Mutation succeeded (form closed) but the follow-up list refresh failed.
    await waitFor(() => expect(screen.getByText('ไม่พบข้อมูลรุ่นเครื่องจักรนี้')).toBeInTheDocument())
    expect(screen.getByText('ลองใหม่อีกครั้ง')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').length).toBe(1)

    await user.click(screen.getByText('ลองใหม่อีกครั้ง'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'GET').length).toBe(3))
    // The retry is a GET only — never another revision POST.
    expect(calls.filter((c) => c.method === 'POST').length).toBe(1)
  })

  it('cancel/switch resets source-specific form state without leaking values across documents', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(lifecycleHistoryBody)))

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())

    const cardA = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(cardA))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), 'DRAFT-A')

    await user.click(screen.getByText('ยกเลิก'))
    expect(screen.queryByLabelText('เวอร์ชัน/ฉบับที่ใหม่')).not.toBeInTheDocument()

    const cardB = findCardByOwnText('MDOC-0003')
    await user.click(openButtonFor(cardB))
    expect((screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่') as HTMLInputElement).value).toBe('')

    // Switching directly from A to B (without cancelling first) must not
    // leak A's in-progress value into B's form either.
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), 'DRAFT-B')
    await user.click(openButtonFor(cardA))
    expect((screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่') as HTMLInputElement).value).toBe('')
  })
})

// ---------------------------------------------------------------------------
// Web/API Phase 6 Batch 6F — ambiguous vs. definite server-error classification
// ---------------------------------------------------------------------------

async function submitReviseAndExpectUncertain(
  user: ReturnType<typeof userEvent.setup>,
  calls: { method: string; url: string }[],
) {
  renderPage()
  await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
  const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
  await user.click(openButtonFor(card))
  await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
  await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
  await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

  await waitFor(() => expect(screen.getByText(/ไม่สามารถยืนยันผลการบันทึกได้/)).toBeInTheDocument())
  // Never implies a guaranteed rollback/no-write, and never falsely names
  // the failure as specifically a timeout (it may be a 5xx too).
  expect(screen.queryByText(/^บันทึกไม่สำเร็จ ไม่มีการเปลี่ยนแปลงข้อมูล$/)).not.toBeInTheDocument()
  expect(screen.getByText('รีเฟรชประวัติ')).toBeInTheDocument()
  expect((screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่') as HTMLInputElement).value).toBe('3.0')
  expect(calls.filter((c) => c.method === 'POST').length).toBe(1)

  // The offered recovery is a GET-only refresh, never another POST.
  await user.click(screen.getByText('รีเฟรชประวัติ'))
  await waitFor(() => expect(calls.filter((c) => c.method === 'GET').length).toBeGreaterThan(1))
  expect(calls.filter((c) => c.method === 'POST').length).toBe(1)
}

describe('ModelDocumentsPage revision — server error classification', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('treats a network rejection as an uncertain outcome', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
        if (method === 'POST' && url.includes('/revise')) throw new TypeError('Failed to fetch')
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    await submitReviseAndExpectUncertain(user, calls)
  })

  it('treats a 500 with a VALID error envelope as an uncertain outcome, not a definite rejection', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
        if (method === 'POST' && url.includes('/revise')) {
          return errorResponse('INTERNAL_SERVER_ERROR', 500)
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    await submitReviseAndExpectUncertain(user, calls)
    // A 500 must never be shown as if it were a known/definite mapped
    // error code, even though its body happens to parse as an envelope.
    expect(screen.queryByText('เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ กรุณาลองใหม่อีกครั้ง')).not.toBeInTheDocument()
  })

  it('treats a 502 WITHOUT an error envelope as an uncertain outcome', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
        if (method === 'POST' && url.includes('/revise')) {
          return new Response('Bad Gateway', { status: 502 })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    await submitReviseAndExpectUncertain(user, calls)
  })

  it('treats a 503 WITHOUT an error envelope as an uncertain outcome', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
        if (method === 'POST' && url.includes('/revise')) {
          return new Response('Service Unavailable', { status: 503 })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    await submitReviseAndExpectUncertain(user, calls)
  })

  it('still treats a known 422 validation rejection as definite (not uncertain)', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
        if (method === 'POST' && url.includes('/revise')) {
          return errorResponse('MODEL_DOCUMENT_VERSION_DUPLICATE', 422)
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()
    await waitFor(() => expect(screen.getByText('MDOC-0004')).toBeInTheDocument())
    const card = screen.getByText('MDOC-0004').closest('.card') as HTMLElement
    await user.click(openButtonFor(card))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่ใหม่'), '3.0')
    await user.type(screen.getByLabelText('วันที่เริ่มมีผลใช้ฉบับใหม่'), '2026-07-01')
    await user.click(screen.getByText('ยืนยันสร้างฉบับปรับปรุง'))

    await waitFor(() =>
      expect(
        screen.getByText('เวอร์ชัน/ฉบับที่ของฉบับใหม่ต้องไม่ซ้ำกับเวอร์ชันของเอกสารต้นทาง'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByText(/ไม่สามารถยืนยันผลการบันทึกได้/)).not.toBeInTheDocument()
    expect(screen.queryByText('รีเฟรชประวัติ')).not.toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').length).toBe(1)
  })
})
