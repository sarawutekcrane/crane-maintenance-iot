import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PartDetailPage } from './PartDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const instanceTrackedPart = {
  part_id: 'PART-0005',
  part_code: 'HYD-PUMP-INST',
  name: 'ปั๊มไฮดรอลิกหลัก แบบติดตามรายชิ้น (ข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบ)',
  specification: null,
  manufacturer: null,
  part_number: null,
  tracking_mode: 'INSTANCE_TRACKED',
  category: 'HYDRAULIC',
  is_active: true,
  metadata: {},
  created_at: '2026-01-15T08:00:00Z',
  updated_at: '2026-01-15T08:00:00Z',
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/parts/PART-0005']}>
      <Routes>
        <Route path="/parts/:partId" element={<PartDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PartDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the tracking mode and an instance-registration action for INSTANCE_TRACKED parts', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(instanceTrackedPart)))

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('ติดตามรายชิ้น (มีรหัสชิ้นงานเฉพาะ)')).toBeInTheDocument(),
    )
    expect(screen.getByText('+ ลงทะเบียนชิ้นงานใหม่')).toBeInTheDocument()
  })

  it('R6: lists lifetime rules with their action and deactivates with a reason and a request id', async () => {
    const user = userEvent.setup()
    const posts: { url: string; body: unknown; id: string | null }[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if ((init?.method ?? 'GET') === 'POST') {
        posts.push({ url, body: JSON.parse(String(init?.body)),
          id: ((init?.headers ?? {}) as Record<string, string>)['X-Request-Id'] ?? null })
        return jsonResponse({ ...instanceTrackedPart, is_active: false })
      }
      if (url.includes('/lifetime-rules')) {
        return jsonResponse([{ lifetime_rule_id: 'LTR-1', part_id: instanceTrackedPart.part_id, scope: 'MODEL',
          model_id: 'MODEL-0003', vehicle_id: null, trigger_type: 'CYCLE', component_role: null, first_due_value: null,
          interval_value: null, warning_window_value: null, note: null, created_at: '2026-01-01T00:00:00Z',
          due_action: 'REPLACE', interval_unit: null, condition_group_key: null, combination: null }])
      }
      return jsonResponse(instanceTrackedPart)
    }))
    renderPage()
    await waitFor(() => expect(screen.getByTestId('part-rule')).toBeInTheDocument())
    expect(screen.getByTestId('part-rule')).toHaveTextContent('เปลี่ยน — จำนวนรอบการทำงาน')
    expect(screen.getByTestId('part-rule')).toHaveTextContent('ยังไม่รองรับการคำนวณ')
    await user.type(screen.getByLabelText('เหตุผล'), 'เลิกใช้ (ทดสอบ)')
    await user.click(screen.getByText('เลิกใช้'))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toContain('/deactivate')
    expect(posts[0].body).toEqual({ reason: 'เลิกใช้ (ทดสอบ)' })
    expect(posts[0].id).toMatch(/^[0-9a-f-]{36}$/)
  })
})
