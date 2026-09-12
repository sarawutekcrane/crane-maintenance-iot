import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InspectionDetailPage } from './InspectionDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const detailBody = {
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
  items: [
    {
      result_id: 'RES-0001',
      inspection_id: 'INS-0001',
      item_id: 'ITM-V-0001',
      sequence: 1,
      title: 'รายการตรวจสอบตัวอย่างที่ 1',
      inspection_point: null,
      method: null,
      standard: null,
      instruction: null,
      is_critical: false,
      result: 'PASS',
      remark: null,
      evidence: [],
    },
    {
      result_id: 'RES-0002',
      inspection_id: 'INS-0001',
      item_id: 'ITM-V-0002',
      sequence: 2,
      title: 'รายการตรวจสอบตัวอย่างที่ 2',
      inspection_point: null,
      method: null,
      standard: null,
      instruction: null,
      is_critical: false,
      result: 'FAIL',
      remark: 'พบความผิดปกติ',
      evidence: [
        {
          attachment_id: 'ATT-0001',
          purpose: 'INSPECTION_EVIDENCE',
          filename: 'evidence.jpg',
          content_type: 'image/jpeg',
          size_bytes: 10,
          uploaded_at: '2026-02-01T00:00:00Z',
          uploaded_by: 'dev-user',
          url: '/api/v1/attachments/ATT-0001/file',
        },
      ],
    },
  ],
  findings: [
    {
      finding_id: 'FND-0001',
      inspection_id: 'INS-0001',
      result_id: 'RES-0002',
      asset_type: 'VEHICLE',
      asset_id: 'VEH-1046',
      item_title: 'รายการตรวจสอบตัวอย่างที่ 2',
      is_critical: false,
      status: 'OPEN',
      created_at: '2026-02-01T00:00:00Z',
    },
  ],
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/inspections/INS-0001']}>
      <Routes>
        <Route path="/inspections/:inspectionId" element={<InspectionDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('InspectionDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the immutable inspection record with results and findings in Thai', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(detailBody)))

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('รหัสผลการตรวจ: INS-0001')).toBeInTheDocument(),
    )
    expect(screen.getByText('รายการตรวจสอบตัวอย่างที่ 1')).toBeInTheDocument()
    expect(screen.getByText('ผ่าน')).toBeInTheDocument()
    expect(screen.getByText('ไม่ผ่าน')).toBeInTheDocument()
    expect(screen.getByText('หมายเหตุ: พบความผิดปกติ')).toBeInTheDocument()
    expect(screen.getByText('ข้อบกพร่องที่พบ')).toBeInTheDocument()
    expect(screen.getAllByText('รายการตรวจสอบตัวอย่างที่ 2').length).toBeGreaterThan(0)
  })

  it('shows a controlled Thai 404 message for an unknown inspection', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: 'INSPECTION_NOT_FOUND',
              message: "Inspection 'INS-9999' was not found",
              details: null,
              request_id: 'req-1',
            },
          },
          404,
        ),
      ),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('ไม่พบข้อมูลผลการตรวจเช็คนี้')).toBeInTheDocument(),
    )
  })
})
