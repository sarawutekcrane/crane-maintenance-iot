import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RepairDetailPage } from './RepairDetailPage'

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

describe('RepairDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the repair source, status, and existing append-only action history in Thai', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(repairDetail)))

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
})
