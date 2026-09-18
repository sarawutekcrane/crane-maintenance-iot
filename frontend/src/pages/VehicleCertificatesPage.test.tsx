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
