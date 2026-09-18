import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
