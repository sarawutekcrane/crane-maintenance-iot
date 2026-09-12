import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InspectionFormPage } from './InspectionFormPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const checklistBody = {
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
    {
      item_id: 'ITM-V-0001',
      revision_id: 'REV-0001',
      sequence: 1,
      title: 'รายการตรวจสอบตัวอย่างที่ 1',
      inspection_point: null,
      method: null,
      standard: null,
      instruction: null,
      frequency: null,
      required_photo_on_fail: false,
      required_remark_on_fail: false,
      is_critical: false,
      reference_image: null,
    },
    {
      item_id: 'ITM-V-0002',
      revision_id: 'REV-0001',
      sequence: 2,
      title: 'รายการตรวจสอบตัวอย่างที่ 2',
      inspection_point: null,
      method: null,
      standard: null,
      instruction: null,
      frequency: null,
      required_photo_on_fail: false,
      required_remark_on_fail: false,
      is_critical: false,
      reference_image: null,
    },
  ],
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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/vehicle/VEH-1046/inspect']}>
      <Routes>
        <Route path="/vehicle/:vehicleId/inspect" element={<InspectionFormPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('InspectionFormPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads the active checklist automatically and renders Thai item titles', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/checklists/active')) return jsonResponse(checklistBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(vehicleDetailBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument(),
    )
    expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 2')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /TC-12/ })).toBeInTheDocument()
  })

  it('disables submit until every item has a result, then submits PASS answers', async () => {
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
        if (url.includes('/checklists/active')) return jsonResponse(checklistBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(vehicleDetailBody)
        if (method === 'POST' && url.includes('/inspections')) {
          return jsonResponse({
            header: {
              inspection_id: 'INS-0001',
              asset_type: 'VEHICLE',
              asset_id: 'VEH-1046',
              checklist_id: 'CHK-0001',
              revision_id: 'REV-0001',
              revision_number: 1,
              submitted_at: '2026-02-01T00:00:00Z',
              inspector_user_id: 'dev-user',
              overall_remark: null,
            },
            items: [],
            findings: [],
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument(),
    )

    const submitButton = screen.getByRole('button', { name: 'ส่งผลการตรวจ' })
    expect(submitButton).toBeDisabled()

    const passButtons = screen.getAllByRole('radio', { name: 'ผ่าน' })
    await user.click(passButtons[0])
    expect(submitButton).toBeDisabled()
    await user.click(passButtons[1])
    expect(submitButton).toBeEnabled()

    await user.click(submitButton)

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/inspections'))).toBe(
        true,
      ),
    )
    const submitCall = calls.find((c) => c.method === 'POST' && c.url.includes('/inspections'))
    const body = submitCall?.body as { asset_type: string; asset_id: string; items: unknown[] }
    expect(body.asset_type).toBe('VEHICLE')
    expect(body.asset_id).toBe('VEH-1046')
    expect(body.items).toHaveLength(2)
  })

  it('shows the remark field immediately on FAIL but does not require it when the item does not require a remark', async () => {
    // CORRECTION (post-Phase-3 verification): `checklistBody`'s items both
    // have `required_remark_on_fail: false` (the seed/placeholder
    // default) — a FAIL must be submittable without a remark.
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
        if (url.includes('/checklists/active')) return jsonResponse(checklistBody)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(vehicleDetailBody)
        if (method === 'POST' && url.includes('/inspections')) {
          return jsonResponse({
            header: {
              inspection_id: 'INS-0001',
              asset_type: 'VEHICLE',
              asset_id: 'VEH-1046',
              checklist_id: 'CHK-0001',
              revision_id: 'REV-0001',
              revision_number: 1,
              submitted_at: '2026-02-01T00:00:00Z',
              inspector_user_id: 'dev-user',
              overall_remark: null,
            },
            items: [],
            findings: [],
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()
    await waitFor(() =>
      expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument(),
    )

    const failButtons = screen.getAllByRole('radio', { name: 'ไม่ผ่าน' })
    await user.click(failButtons[0])
    // Remark field appears immediately without navigating away, labeled optional.
    expect(screen.getAllByLabelText('หมายเหตุ (ถ้ามี)')[0]).toBeInTheDocument()

    const passButtons = screen.getAllByRole('radio', { name: 'ผ่าน' })
    await user.click(passButtons[1])

    const submitButton = screen.getByRole('button', { name: 'ส่งผลการตรวจ' })
    await user.click(submitButton)

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/inspections'))).toBe(
        true,
      ),
    )
  })

  it('blocks submission until a remark is entered when the item requires one', async () => {
    const user = userEvent.setup()
    const requiredRemarkChecklist = {
      ...checklistBody,
      items: [
        { ...checklistBody.items[0], required_remark_on_fail: true },
        checklistBody.items[1],
      ],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/checklists/active')) return jsonResponse(requiredRemarkChecklist)
        if (url.includes('/vehicles/VEH-1046')) return jsonResponse(vehicleDetailBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()
    await waitFor(() =>
      expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument(),
    )

    const failButtons = screen.getAllByRole('radio', { name: 'ไม่ผ่าน' })
    await user.click(failButtons[0])
    expect(screen.getAllByLabelText('หมายเหตุ (จำเป็นเมื่อไม่ผ่าน)')[0]).toBeInTheDocument()

    const passButtons = screen.getAllByRole('radio', { name: 'ผ่าน' })
    await user.click(passButtons[1])

    const submitButton = screen.getByRole('button', { name: 'ส่งผลการตรวจ' })
    await user.click(submitButton)

    await waitFor(() =>
      expect(screen.getByText('กรุณาตรวจสอบรายการที่ยังไม่ครบถ้วน')).toBeInTheDocument(),
    )
  })

  it('shows a controlled Thai not-found message and does not render the checklist when the asset does not exist', async () => {
    // CORRECTION (post-Phase-3 verification): validate the asset before
    // allowing inspection entry, instead of only discovering an invalid
    // asset at final submission.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/checklists/active')) return jsonResponse(checklistBody)
        if (url.includes('/vehicles/VEH-1046')) {
          return jsonResponse(
            { error: { code: 'VEHICLE_NOT_FOUND', message: 'Vehicle not found' } },
            404,
          )
        }
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('ไม่พบข้อมูลยานพาหนะนี้')).toBeInTheDocument(),
    )
    expect(screen.queryByText('รายการตรวจสอบตัวอย่างที่ 1')).not.toBeInTheDocument()
  })
})
