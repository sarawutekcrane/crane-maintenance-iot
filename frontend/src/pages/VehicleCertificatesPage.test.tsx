import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { VehicleCertificatesPage } from './VehicleCertificatesPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const historyBody = [
  {
    certificate_id: 'CERT-0002',
    vehicle_id: 'VEH-1046',
    certificate_type_code: 'INSURANCE',
    certificate_type_name_th: 'ประกันภัย',
    document_no: '0012345678',
    issue_date: '2026-01-01',
    expiry_date: '2027-01-01',
    alert_lead_days: 30,
    certificate_status: 'ACTIVE',
    replaced_by_certificate_id: null,
    storage_ref: null,
    created_by_user_id: 'dev-user',
    created_at: '2026-01-01T08:00:00Z',
    note_th: null,
  },
  {
    certificate_id: 'CERT-0001',
    vehicle_id: 'VEH-1046',
    certificate_type_code: 'TAX',
    certificate_type_name_th: 'ภาษี',
    document_no: null,
    issue_date: null,
    expiry_date: null,
    alert_lead_days: null,
    certificate_status: null,
    replaced_by_certificate_id: null,
    storage_ref: null,
    created_by_user_id: 'dev-user',
    created_at: '2025-06-01T08:00:00Z',
    note_th: null,
  },
]

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/certificates']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/certificates" element={<VehicleCertificatesPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('VehicleCertificatesPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows every certificate ever created for the vehicle — history is never hidden', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(historyBody)))

    renderPage()

    await waitFor(() => expect(screen.getByText('ประกันภัย')).toBeInTheDocument())
    expect(screen.getByText('ภาษี')).toBeInTheDocument()
    expect(screen.getByText('0012345678')).toBeInTheDocument()
  })

  it('creates a certificate via POST', async () => {
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
        if (method === 'POST' && url.includes('/certificates')) {
          return jsonResponse({
            ...historyBody[0],
            certificate_id: 'CERT-0003',
            document_no: '0099999999',
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('+ เพิ่มเอกสาร/ใบรับรอง')).toBeInTheDocument())
    await user.click(screen.getByText('+ เพิ่มเอกสาร/ใบรับรอง'))
    await user.type(screen.getByLabelText('เลขที่เอกสาร'), '0099999999')
    await user.click(screen.getByText('บันทึก'))

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.url.includes('/vehicles/VEH-1046/certificates')),
      ).toBe(true),
    )
    const createCall = calls.find((c) => c.method === 'POST')
    expect(createCall?.body).toMatchObject({ document_no: '0099999999' })
  })

  it('shows a Thai error message with request id when the load fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { error: { code: 'VEHICLE_NOT_FOUND', message: 'not found', request_id: 'req-1' } },
          404,
        ),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeInTheDocument())
  })
})

// ---------------------------------------------------------------------------
// Web/API Phase 6 Batch 2B — renewal UI
// ---------------------------------------------------------------------------

const lifecycleHistoryBody = [
  {
    certificate_id: 'CERT-0003',
    vehicle_id: 'VEH-1046',
    certificate_type_code: 'INSURANCE',
    certificate_type_name_th: 'ประกันภัย ใหม่',
    document_no: null,
    issue_date: null,
    expiry_date: null,
    alert_lead_days: 30,
    certificate_status: 'ACTIVE',
    replaced_by_certificate_id: null,
    storage_ref: null,
    created_by_user_id: 'dev-user',
    created_at: '2027-01-01T08:00:00Z',
    note_th: null,
  },
  {
    certificate_id: 'CERT-0002',
    vehicle_id: 'VEH-1046',
    certificate_type_code: 'INSURANCE',
    certificate_type_name_th: 'ประกันภัย เดิม',
    document_no: '0012345678',
    issue_date: '2026-01-01',
    expiry_date: '2027-01-01',
    alert_lead_days: 15,
    certificate_status: 'REPLACED',
    replaced_by_certificate_id: 'CERT-0003',
    storage_ref: null,
    created_by_user_id: 'dev-user',
    created_at: '2026-01-01T08:00:00Z',
    note_th: null,
  },
  {
    certificate_id: 'CERT-0001',
    vehicle_id: 'VEH-1046',
    certificate_type_code: 'TAX',
    certificate_type_name_th: 'ภาษี',
    document_no: null,
    issue_date: null,
    expiry_date: null,
    alert_lead_days: null,
    certificate_status: 'EXPIRED',
    replaced_by_certificate_id: null,
    storage_ref: null,
    created_by_user_id: 'dev-user',
    created_at: '2020-01-01T08:00:00Z',
    note_th: null,
  },
]

describe('VehicleCertificatesPage renewal', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the renew button only for the ACTIVE certificate, never for REPLACED or EXPIRED', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(lifecycleHistoryBody)))

    renderPage()

    await waitFor(() => expect(screen.getAllByText('ต่ออายุ/ออกใหม่').length).toBeGreaterThan(0))
    // Exactly one certificate (the ACTIVE one) exposes the renew action;
    // the heading text inside the opened form also reads "ต่ออายุ/ออกใหม่",
    // but the form only renders after the button is clicked — so at rest
    // there is exactly one match, the button itself.
    expect(screen.getAllByText('ต่ออายุ/ออกใหม่').length).toBe(1)
  })

  it('shows replaced_by_certificate_id for a REPLACED record', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(lifecycleHistoryBody)))

    renderPage()

    await waitFor(() => expect(screen.getByText('ถูกแทนที่โดย')).toBeInTheDocument())
    expect(screen.getByText('CERT-0003')).toBeInTheDocument()
  })

  it('never renders a manual expire or replace control', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(lifecycleHistoryBody)))

    renderPage()

    await waitFor(() => expect(screen.getAllByText('ต่ออายุ/ออกใหม่').length).toBeGreaterThan(0))
    expect(screen.queryByText(/หมดอายุด้วยตนเอง|ทำเครื่องหมายหมดอายุ|ทำเครื่องหมายแทนที่/)).not.toBeInTheDocument()
  })

  it('pre-fills certificate_type_name_th and alert_lead_days from the source certificate', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(lifecycleHistoryBody)))

    renderPage()

    await waitFor(() => expect(screen.getAllByText('ต่ออายุ/ออกใหม่').length).toBeGreaterThan(0))
    await user.click(screen.getAllByText('ต่ออายุ/ออกใหม่')[0])

    const nameInput = screen.getByLabelText('ประเภทเอกสาร (ชื่อภาษาไทย)') as HTMLInputElement
    const alertInput = screen.getByLabelText('แจ้งเตือนล่วงหน้า (วัน)') as HTMLInputElement
    expect(nameInput.value).toBe('ประกันภัย ใหม่')
    expect(alertInput.value).toBe('30')
  })

  it('does not auto-carry document_no/issue_date/expiry_date/storage_ref/note_th unless supplied', async () => {
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
        if (method === 'GET') return jsonResponse(lifecycleHistoryBody)
        if (method === 'POST' && url.includes('/renew')) {
          return jsonResponse({ ...lifecycleHistoryBody[0], certificate_id: 'CERT-0004' })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getAllByText('ต่ออายุ/ออกใหม่').length).toBeGreaterThan(0))
    await user.click(screen.getAllByText('ต่ออายุ/ออกใหม่')[0])
    await user.click(screen.getByText('ยืนยันต่ออายุ/ออกใหม่'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/renew'))).toBe(true),
    )
    const renewCall = calls.find((c) => c.method === 'POST' && c.url.includes('/renew'))
    expect(renewCall?.body).toMatchObject({
      document_no: null,
      issue_date: null,
      expiry_date: null,
      storage_ref: null,
      note_th: null,
    })
  })

  it('refreshes the history after a successful renewal', async () => {
    const user = userEvent.setup()
    let getCount = 0

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (method === 'GET') {
          getCount += 1
          return jsonResponse(lifecycleHistoryBody)
        }
        if (method === 'POST' && url.includes('/renew')) {
          return jsonResponse({ ...lifecycleHistoryBody[0], certificate_id: 'CERT-0004' })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getAllByText('ต่ออายุ/ออกใหม่').length).toBeGreaterThan(0))
    const countAfterInitialLoad = getCount
    await user.click(screen.getAllByText('ต่ออายุ/ออกใหม่')[0])
    await user.click(screen.getByText('ยืนยันต่ออายุ/ออกใหม่'))

    await waitFor(() => expect(getCount).toBeGreaterThan(countAfterInitialLoad))
  })
})

describe('VehicleCertificatesPage R7 document file panel', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const legacyRefBody = [{ ...historyBody[0], storage_ref: 'https://legacy.example.invalid/000123.pdf' }]

  it('makes no attachment call until asked and never renders a historical storage_ref as a link', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        urls.push(String(input))
        return jsonResponse(legacyRefBody)
      }),
    )
    renderPage()
    await waitFor(() => expect(screen.getByText('ประกันภัย')).toBeInTheDocument())
    expect(urls).toEqual(['/api/v1/vehicles/VEH-1046/certificates'])
    expect(screen.getByText(/ยังไม่ได้ตรวจสอบว่าเป็นไฟล์ในระบบ/)).toBeInTheDocument()
    expect(screen.queryByText('https://legacy.example.invalid/000123.pdf')).not.toBeInTheDocument()
    expect(document.querySelector('a[href*="legacy.example.invalid"]')).toBeNull()
  })

  it('shows PDF attaching as unavailable and renders no file picker without the server-reported grant', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(historyBody)))
    renderPage()
    await waitFor(() => expect(screen.getByText('ประกันภัย')).toBeInTheDocument())
    expect(
      screen.getAllByText('ไม่มีสิทธิ์แนบไฟล์ (เฉพาะผู้จัดการเอกสารที่ได้รับสิทธิ์ในบริบท TEST)'),
    ).toHaveLength(2)
    expect(document.querySelector('input[type="file"]')).toBeNull()
  })

  it('checks on demand with one GET and links only the authorized server file route', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push({ method: init?.method ?? 'GET', url })
        if (url.startsWith('/api/v1/attachments/by-source/')) {
          return jsonResponse([
            {
              attachment_id: 'ATT-0007',
              purpose: 'VEHICLE_CERTIFICATE_DOCUMENT',
              filename: 'insurance.pdf',
              content_type: 'application/pdf',
              size_bytes: 10,
              uploaded_at: '2026-01-01T08:00:00Z',
              uploaded_by: null,
              url: '/api/v1/attachments/ATT-0007/file',
            },
            {
              attachment_id: 'ATT-0008',
              purpose: 'VEHICLE_CERTIFICATE_DOCUMENT',
              filename: 'smuggled.pdf',
              content_type: 'application/pdf',
              size_bytes: 10,
              uploaded_at: '2026-01-01T08:00:00Z',
              uploaded_by: null,
              url: 'https://evil.example.invalid/x.pdf',
            },
            {
              attachment_id: 'ATT-0009',
              purpose: 'INSPECTION_EVIDENCE',
              filename: 'photo.png',
              content_type: 'image/png',
              size_bytes: 10,
              uploaded_at: '2026-01-01T08:00:00Z',
              uploaded_by: null,
              url: '/api/v1/attachments/ATT-0009/file',
            },
          ])
        }
        return jsonResponse(historyBody)
      }),
    )
    renderPage()
    await waitFor(() => expect(screen.getByText('ประกันภัย')).toBeInTheDocument())
    await user.click(screen.getAllByRole('button', { name: 'ตรวจสอบไฟล์ PDF' })[0])
    const link = await screen.findByRole('link', { name: 'เปิดไฟล์ PDF' })
    expect(link).toHaveAttribute('href', '/api/v1/attachments/ATT-0007/file')
    expect(screen.getAllByRole('link', { name: 'เปิดไฟล์ PDF' })).toHaveLength(1)
    expect(screen.queryByText('smuggled.pdf')).not.toBeInTheDocument()
    expect(screen.queryByText('photo.png')).not.toBeInTheDocument()
    expect(calls).toEqual([
      { method: 'GET', url: '/api/v1/vehicles/VEH-1046/certificates' },
      { method: 'GET', url: '/api/v1/attachments/by-source/VEHICLE_CERTIFICATE/CERT-0002' },
    ])
  })

  it('shows missing, forbidden and not-found results honestly', async () => {
    const user = userEvent.setup()
    let attachmentResponse: Response = jsonResponse([])
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).startsWith('/api/v1/attachments/') ? attachmentResponse : jsonResponse(historyBody),
      ),
    )
    renderPage()
    await waitFor(() => expect(screen.getByText('ประกันภัย')).toBeInTheDocument())
    const [check] = screen.getAllByRole('button', { name: 'ตรวจสอบไฟล์ PDF' })
    await user.click(check)
    expect(await screen.findByText('ยังไม่มีไฟล์ PDF ที่ตรวจสอบแล้วในระบบ')).toBeInTheDocument()

    attachmentResponse = jsonResponse(
      { error: { code: 'ATTACHMENT_SOURCE_NOT_AUTHORIZED', message: 'x', request_id: 'r' } },
      403,
    )
    await user.click(check)
    expect(await screen.findByRole('alert')).toHaveTextContent('คุณไม่มีสิทธิ์ดูไฟล์ของเอกสารนี้')

    attachmentResponse = jsonResponse(
      { error: { code: 'VEHICLE_CERTIFICATE_NOT_FOUND', message: 'x', request_id: 'r' } },
      404,
    )
    await user.click(check)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('ไม่พบเอกสารต้นทางของไฟล์นี้'))
    expect(screen.queryByRole('link', { name: 'เปิดไฟล์ PDF' })).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// R7 TEST-only PDF Management: the picker is driven ONLY by the server's /me
// (grant + TEST data context); every upload is one explicit, never-repeated POST.
// ---------------------------------------------------------------------------

const TEST_DOCUMENT_GRANT = 'can_manage_test_document_file'

function meBody(capabilities: string[], dataContext = 'TEST') {
  return { user_id: 'USR-TEST-AM-MGR', roles: [], capabilities, data_context: dataContext }
}

function renderWithMe() {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={['/vehicle/VEH-1046/certificates']}>
        <Routes>
          <Route path="/vehicle/:vehicleId/certificates" element={<VehicleCertificatesPage />} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

const uploadedBody = {
  attachment_id: 'ATT-0100',
  purpose: 'VEHICLE_CERTIFICATE_DOCUMENT',
  filename: 'insurance.pdf',
  content_type: 'application/pdf',
  size_bytes: 12,
  uploaded_at: '2026-11-14T08:00:00Z',
  uploaded_by: 'USR-TEST-AM-MGR',
  url: '/api/v1/attachments/ATT-0100/file',
  source_type: 'VEHICLE_CERTIFICATE',
  source_id: 'CERT-0002',
}

type Call = { method: string; url: string; body?: BodyInit | null }

function stubServer(me: unknown, upload: () => Promise<Response> | Response, listed: () => unknown[] = () => []) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ method: init?.method ?? 'GET', url, body: init?.body })
      if (url === '/api/v1/me') return jsonResponse(me)
      if (url === '/api/v1/attachments') return upload()
      if (url.startsWith('/api/v1/attachments/by-source/')) return jsonResponse(listed())
      return jsonResponse(historyBody)
    }),
  )
  return calls
}

const pdfFile = () => new File(['%PDF-1.4 test'], 'insurance.pdf', { type: 'application/pdf' })
const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST')

describe('VehicleCertificatesPage R7 TEST-only PDF upload', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders no picker for a can_view-only actor, nor for a granted actor outside TEST', async () => {
    for (const me of [meBody(['can_view']), meBody(['can_view', TEST_DOCUMENT_GRANT], 'REAL'),
      meBody(['can_view', TEST_DOCUMENT_GRANT], 'UNCONFIGURED')]) {
      const calls = stubServer(me, () => jsonResponse(uploadedBody))
      const view = renderWithMe()
      await waitFor(() => expect(calls.some((c) => c.url === '/api/v1/me')).toBe(true))
      await waitFor(() => expect(screen.getByText('ประกันภัย')).toBeInTheDocument())
      expect(document.querySelector('input[type="file"]')).toBeNull()
      expect(screen.queryByRole('button', { name: 'อัปโหลดไฟล์ PDF' })).not.toBeInTheDocument()
      expect(screen.getAllByText('ไม่มีสิทธิ์แนบไฟล์ (เฉพาะผู้จัดการเอกสารที่ได้รับสิทธิ์ในบริบท TEST)')).toHaveLength(2)
      expect(posts(calls)).toEqual([])
      view.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('a granted TEST actor uploads exactly this record once, then the authorized list refreshes', async () => {
    const user = userEvent.setup()
    let stored = false
    const calls = stubServer(
      meBody(['can_view', TEST_DOCUMENT_GRANT]),
      () => {
        stored = true
        return jsonResponse(uploadedBody)
      },
      () => (stored ? [uploadedBody] : []),
    )
    renderWithMe()
    const [picker] = await screen.findAllByLabelText('แนบไฟล์ PDF (TEST)')
    const [button] = screen.getAllByRole('button', { name: 'อัปโหลดไฟล์ PDF' })
    expect(button).toBeDisabled() // nothing chosen yet
    expect(picker).toHaveAttribute('accept', 'application/pdf,.pdf')
    await user.upload(picker, pdfFile())
    await user.click(button)

    expect(await screen.findByRole('status')).toHaveTextContent('อัปโหลดไฟล์ insurance.pdf แล้ว')
    const link = await screen.findByRole('link', { name: 'เปิดไฟล์ PDF' })
    expect(link).toHaveAttribute('href', '/api/v1/attachments/ATT-0100/file')
    const [post] = posts(calls)
    expect(posts(calls)).toHaveLength(1)
    const form = post.body as FormData
    expect(form.get('purpose')).toBe('VEHICLE_CERTIFICATE_DOCUMENT')
    expect(form.get('source_type')).toBe('VEHICLE_CERTIFICATE')
    expect(form.get('source_id')).toBe('CERT-0002')
    expect((form.get('file') as File).name).toBe('insurance.pdf')
    expect(calls.map((c) => `${c.method} ${c.url}`)).toContain(
      'GET /api/v1/attachments/by-source/VEHICLE_CERTIFICATE/CERT-0002',
    )
    expect(screen.getAllByText('ยังไม่ได้เลือกไฟล์')).toHaveLength(2) // the picker was cleared
  })

  it('shows accurate Thai errors for 403 / 422 / 500, keeps the chosen file and never retries', async () => {
    const user = userEvent.setup()
    let next: Response = jsonResponse({})
    const calls = stubServer(meBody(['can_view', TEST_DOCUMENT_GRANT]), () => next)
    renderWithMe()
    const [picker] = await screen.findAllByLabelText('แนบไฟล์ PDF (TEST)')
    await user.upload(picker, pdfFile())
    const [button] = screen.getAllByRole('button', { name: 'อัปโหลดไฟล์ PDF' })
    const cases: [Response, string][] = [
      [jsonResponse({ error: { code: 'DOCUMENT_FILE_UPLOAD_NOT_AUTHORIZED', message: 'x', request_id: 'r1' } }, 403),
        'คุณไม่มีสิทธิ์แนบไฟล์ PDF ให้เอกสารนี้ — ไม่มีการบันทึกไฟล์ (รหัสคำขอ r1)'],
      [jsonResponse({ error: { code: 'ACCESS_ACTOR_NOT_VERIFIED', message: 'x', request_id: 'r2' } }, 403),
        'บัญชีนี้ยังไม่ได้ยืนยันว่าเป็นพนักงาน TEST'],
      [jsonResponse({ error: { code: 'ATTACHMENT_CONTENT_MISMATCH', message: 'x', request_id: 'r3' } }, 422),
        'ไฟล์ต้องเป็น PDF ที่ถูกต้องเท่านั้น — ไม่มีการบันทึกไฟล์'],
      [jsonResponse({ error: { code: 'ATTACHMENT_TOO_LARGE', message: 'x', request_id: 'r4' } }, 422),
        'ไฟล์มีขนาดเกินกำหนด'],
      [jsonResponse({ error: { code: 'INTERNAL_ERROR', message: 'x', request_id: 'r5' } }, 500),
        'ไม่ทราบผลการอัปโหลด'],
      [new Response('gateway', { status: 502 }), 'ไม่ทราบผลการอัปโหลด'],
    ]
    for (const [index, [response, text]] of cases.entries()) {
      next = response
      await user.click(button)
      await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(text))
      expect(posts(calls)).toHaveLength(index + 1) // one POST per explicit click, never a retry
      expect(screen.getAllByText('insurance.pdf')).toHaveLength(1) // the chosen file is kept
      expect(button).toBeEnabled()
    }
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('a double click while the upload is in flight sends one request only', async () => {
    const user = userEvent.setup()
    let release: (response: Response) => void = () => {}
    const calls = stubServer(
      meBody(['can_view', TEST_DOCUMENT_GRANT]),
      () => new Promise<Response>((resolve) => (release = resolve)),
    )
    renderWithMe()
    const [picker] = await screen.findAllByLabelText('แนบไฟล์ PDF (TEST)')
    await user.upload(picker, pdfFile())
    const [button] = screen.getAllByRole('button', { name: 'อัปโหลดไฟล์ PDF' })
    await user.click(button)
    expect(await screen.findByRole('button', { name: 'กำลังอัปโหลด...' })).toBeDisabled()
    await user.dblClick(screen.getByRole('button', { name: 'กำลังอัปโหลด...' }))
    expect(posts(calls)).toHaveLength(1)
    release(jsonResponse(uploadedBody))
    expect(await screen.findByRole('status')).toHaveTextContent('อัปโหลดไฟล์ insurance.pdf แล้ว')
    expect(posts(calls)).toHaveLength(1)
  })
})
