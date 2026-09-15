import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { RepairDetailPage } from './RepairDetailPage'

const maintenanceMeBody = {
  user_id: 'user-maintenance-1',
  roles: ['MAINTENANCE'],
  capabilities: [
    'can_view',
    'can_manage_pm',
    'can_report_repair',
    'can_manage_repair',
    'can_close_repair',
    'can_record_inspection',
  ],
}

const driverMeBody = {
  user_id: 'user-driver-1',
  roles: ['DRIVER'],
  capabilities: ['can_view', 'can_report_repair', 'can_record_inspection'],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const repairDetail = {
  repair: {
    repair_id: 'RPR-0001',
    asset_type: 'VEHICLE',
    asset_id: 'VEH-1046',
    source_type: 'FINDING',
    source_id: 'FND-0001',
    category: 'ระบบไฮดรอลิก',
    symptom: 'มีเสียงดังผิดปกติ',
    meter_snapshot_id: null,
    status: 'OPEN',
    opened_at: '2026-02-01T00:00:00Z',
    opened_by: 'dev-user',
    closed_at: null,
    closed_by: null,
    close_note: null,
  },
  actions: [
    {
      repair_action_id: 'RPRA-0001',
      repair_id: 'RPR-0001',
      action_text: 'ตรวจสอบเบื้องต้น',
      actor: 'dev-user',
      created_at: '2026-02-01T00:10:00Z',
      attachment_ids: [],
    },
  ],
  parts: [],
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/repairs/RPR-0001']}>
      <Routes>
        <Route path="/repairs/:repairId" element={<RepairDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function renderPageWithCapabilities() {
  return render(
    <CapabilitiesProvider>
      <MemoryRouter initialEntries={['/repairs/RPR-0001']}>
        <Routes>
          <Route path="/repairs/:repairId" element={<RepairDetailPage />} />
        </Routes>
      </MemoryRouter>
    </CapabilitiesProvider>,
  )
}

describe('RepairDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the repair source, status, and existing append-only action history in Thai', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/attachments/by-source/')) return jsonResponse([])
        return jsonResponse(repairDetail)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('รหัสใบแจ้งซ่อม: RPR-0001')).toBeInTheDocument())
    expect(screen.getByText('ข้อบกพร่องจากการตรวจเช็ค (FND-0001)')).toBeInTheDocument()
    expect(screen.getByText('อาการ/ปัญหา: มีเสียงดังผิดปกติ')).toBeInTheDocument()
    expect(screen.getByText('ตรวจสอบเบื้องต้น')).toBeInTheDocument()
  })

  it('appends a new action without removing the previous one, and adds an actual part', async () => {
    const user = userEvent.setup()
    let actions = [...repairDetail.actions]
    let parts: {
      repair_part_id: string
      repair_id: string
      part_description: string
      quantity: number | null
      unit: string | null
      recorded_by: string | null
      recorded_at: string
    }[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'

        if (url.includes('/attachments/by-source/')) return jsonResponse([])
        if (method === 'GET' && url.includes('/repairs/RPR-0001')) {
          return jsonResponse({ repair: repairDetail.repair, actions, parts })
        }
        if (method === 'POST' && url.includes('/actions')) {
          const body = JSON.parse(init?.body as string)
          actions = [
            ...actions,
            {
              repair_action_id: 'RPRA-0002',
              repair_id: 'RPR-0001',
              action_text: body.action_text,
              actor: 'dev-user',
              created_at: '2026-02-01T00:20:00Z',
              attachment_ids: [],
            },
          ]
          return jsonResponse({ repair: repairDetail.repair, actions, parts })
        }
        if (method === 'POST' && url.includes('/parts')) {
          const body = JSON.parse(init?.body as string)
          parts = [
            {
              repair_part_id: 'RPRP-0001',
              repair_id: 'RPR-0001',
              part_description: body.part_description,
              quantity: body.quantity,
              unit: body.unit,
              recorded_by: 'dev-user',
              recorded_at: '2026-02-01T00:25:00Z',
            },
          ]
          return jsonResponse({ repair: repairDetail.repair, actions, parts })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ตรวจสอบเบื้องต้น')).toBeInTheDocument())

    await user.type(screen.getByLabelText('เพิ่มการดำเนินการ'), 'เปลี่ยนอะไหล่และทดสอบ')
    await user.click(screen.getByText('บันทึกการดำเนินการ'))

    await waitFor(() => expect(screen.getByText('เปลี่ยนอะไหล่และทดสอบ')).toBeInTheDocument())
    // The previous action remains visible — append-only history.
    expect(screen.getByText('ตรวจสอบเบื้องต้น')).toBeInTheDocument()

    await user.click(screen.getByText('ไม่พบอะไหล่ในระบบ — ระบุชื่อเอง (สำหรับอะไหล่ที่ยังไม่ได้ลงทะเบียน)'))
    await user.type(
      screen.getByLabelText('ชื่ออะไหล่ (ระบุเอง — อะไหล่ยังไม่ได้ลงทะเบียนใน Part Master)'),
      'สายไฮดรอลิก',
    )
    await user.click(screen.getByText('+ เพิ่มอะไหล่'))

    await waitFor(() => expect(screen.getByText('สายไฮดรอลิก')).toBeInTheDocument())
  })

  // ---------------------------------------------------------------------
  // F2 (Final Cross-Phase Integration Fix) — previously-uploaded action
  // evidence must remain visible after navigation/reload, not just during
  // the same in-memory session.
  // ---------------------------------------------------------------------

  it('shows previously-uploaded action evidence after reload, resolved via the by-source attachment endpoint', async () => {
    const detailWithEvidence = {
      repair: repairDetail.repair,
      actions: [
        {
          repair_action_id: 'RPRA-0001',
          repair_id: 'RPR-0001',
          action_text: 'ตรวจสอบเบื้องต้น',
          actor: 'dev-user',
          created_at: '2026-02-01T00:10:00Z',
          attachment_ids: ['ATT-0001'],
        },
      ],
      parts: [],
    }
    const evidenceAttachment = {
      attachment_id: 'ATT-0001',
      purpose: 'REPAIR_EVIDENCE',
      filename: 'evidence.jpg',
      content_type: 'image/jpeg',
      size_bytes: 123,
      uploaded_at: '2026-02-01T00:09:00Z',
      uploaded_by: 'dev-user',
      url: '/api/v1/attachments/ATT-0001/file',
    }

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/attachments/by-source/REPAIR/RPR-0001')) {
          return jsonResponse([evidenceAttachment])
        }
        if (url.includes('/repairs/RPR-0001')) return jsonResponse(detailWithEvidence)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ตรวจสอบเบื้องต้น')).toBeInTheDocument())
    const image = await screen.findByAltText('รูปแนบการดำเนินการ')
    expect(image).toHaveAttribute('src', '/api/v1/attachments/ATT-0001/file')
  })

  it('shows a sensible message when the evidence fetch fails, without breaking the rest of the page', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/attachments/by-source/')) {
          return jsonResponse(
            { error: { code: 'ATTACHMENT_SOURCE_NOT_AUTHORIZED', message: 'no', request_id: 'r1' } },
            403,
          )
        }
        return jsonResponse(repairDetail)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('รหัสใบแจ้งซ่อม: RPR-0001')).toBeInTheDocument())
    expect(screen.getByText(/ไม่สามารถโหลดรูปแนบได้/)).toBeInTheDocument()
    // The rest of the page (existing action history) still renders.
    expect(screen.getByText('ตรวจสอบเบื้องต้น')).toBeInTheDocument()
  })

  // ---------------------------------------------------------------------
  // F6 (Final Cross-Phase Integration Fix) — no silent failures.
  // ---------------------------------------------------------------------

  it('shows an error and keeps the form usable when addEvidence fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (url.includes('/attachments/by-source/')) return jsonResponse([])
        if (method === 'GET' && url.includes('/repairs/RPR-0001')) {
          return jsonResponse({ repair: repairDetail.repair, actions: repairDetail.actions, parts: [] })
        }
        if (method === 'POST' && url.endsWith('/attachments')) {
          return jsonResponse(
            { error: { code: 'ATTACHMENT_TOO_LARGE', message: 'too big', request_id: 'r1' } },
            422,
          )
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ตรวจสอบเบื้องต้น')).toBeInTheDocument())

    const file = new File(['x'], 'photo.jpg', { type: 'image/jpeg' })
    const input = document.getElementById('action-photo') as HTMLInputElement
    await userEvent.upload(input, file)

    await waitFor(() =>
      expect(screen.getByText('ไฟล์มีขนาดใหญ่เกินกำหนด กรุณาเลือกไฟล์ที่มีขนาดเล็กลง')).toBeInTheDocument(),
    )
    // The action form remains usable — the text field is still there.
    expect(screen.getByLabelText('เพิ่มการดำเนินการ')).toBeInTheDocument()
  })

  // ---------------------------------------------------------------------
  // F5 (Final Cross-Phase Integration Fix) — frontend capability gating.
  // ---------------------------------------------------------------------

  it('does not show Assign/Close controls to a DRIVER', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/me')) return jsonResponse(driverMeBody)
        if (url.includes('/attachments/by-source/')) return jsonResponse([])
        return jsonResponse(repairDetail)
      }),
    )

    renderPageWithCapabilities()

    await waitFor(() => expect(screen.getByText('รหัสใบแจ้งซ่อม: RPR-0001')).toBeInTheDocument())
    expect(screen.queryByText('การมอบหมายงาน')).not.toBeInTheDocument()
    expect(screen.queryByText('ปิดใบแจ้งซ่อม')).not.toBeInTheDocument()
  })

  it('shows Assign/Close controls to a MAINTENANCE actor', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/me')) return jsonResponse(maintenanceMeBody)
        if (url.includes('/attachments/by-source/')) return jsonResponse([])
        return jsonResponse(repairDetail)
      }),
    )

    renderPageWithCapabilities()

    await waitFor(() => expect(screen.getByText('รหัสใบแจ้งซ่อม: RPR-0001')).toBeInTheDocument())
    expect(await screen.findByText('การมอบหมายงาน')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ปิดใบแจ้งซ่อม' })).toBeInTheDocument()
  })

  it('shows an error and does not close the repair when the close action fails (MAINTENANCE)', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (url.includes('/me')) return jsonResponse(maintenanceMeBody)
        if (url.includes('/attachments/by-source/')) return jsonResponse([])
        if (method === 'POST' && url.includes('/close')) {
          return jsonResponse(
            { error: { code: 'REPAIR_ALREADY_CLOSED', message: 'closed', request_id: 'r1' } },
            422,
          )
        }
        if (method === 'GET' && url.includes('/repairs/RPR-0001')) return jsonResponse(repairDetail)
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPageWithCapabilities()

    const closeButton = await screen.findByRole('button', { name: 'ปิดใบแจ้งซ่อม' })
    await user.click(closeButton)

    await waitFor(() =>
      expect(screen.getByText('ใบแจ้งซ่อมนี้ถูกปิดไปแล้ว')).toBeInTheDocument(),
    )
    // Still shows the OPEN status — no false success/navigation happened.
    expect(screen.getByText('รหัสใบแจ้งซ่อม: RPR-0001')).toBeInTheDocument()
  })
})
