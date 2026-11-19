import { render, screen, waitFor, within } from '@testing-library/react'
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

/** Every rendered work order is Technician V2, so the assignment panel reads its V2 team and the
 * technician list; these tests are about the rest of the page, so the panel gets an empty team. */
function withV2Panel(handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/technician-assignments')) {
      return jsonResponse({ job_id: 'RPR-0001', assignment_model: 'TECHNICIAN_V2', status: 'NONE', current: null, sets: [], withdrawals: [] })
    }
    if (url.includes('/technicians?')) return jsonResponse({ items: [], page: 1, page_size: 200, total_items: 0 })
    // R8 PRE-UAT: the material (Store) and classification panels read their own state.
    if (url.endsWith('/store-reconciliation')) {
      return jsonResponse({ repair_id: 'RPR-0001', state: 'RECONCILED', blockers: [], lines: [], events: [],
        exceptions_note: 'EXCEPTION_POLICY_PENDING', scope_note: 'ไม่ใช่บัญชีสต็อกคลัง' })
    }
    if (url.endsWith('/classification')) {
      return jsonResponse({ repair_id: 'RPR-0001', state: 'NOT_ELIGIBLE', blockers: ['REPAIR_OPEN'], draft_revision: 0,
        draft_rows: [], final: null, replayed: false, note_th: 'TEST candidate — ไม่อนุมัติสำหรับ REAL' })
    }
    return handler(input, init)
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
    // DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107: the application renders Technician V2 work orders only.
    assignment_model: 'TECHNICIAN_V2',
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
      withV2Panel(async (input: RequestInfo | URL) => {
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
      withV2Panel(async (input: RequestInfo | URL, init?: RequestInit) => {
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
      withV2Panel(async (input: RequestInfo | URL) => {
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
      withV2Panel(async (input: RequestInfo | URL) => {
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
      withV2Panel(async (input: RequestInfo | URL, init?: RequestInit) => {
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
      withV2Panel(async (input: RequestInfo | URL) => {
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

  // R2 Batch R2f-h4 B5 (deliberate test migration): the legacy free-text "การมอบหมายงาน" control
  // (POST /repairs/{id}/assign) is retired; the Close control this test protects is unchanged, and a LEGACY
  // job now shows its stored legacy ids read-only (the V2 panel is covered in TechnicianV2Cutover.test.tsx).
  it('shows the Close control and the V2 team panel (no free-text Assign) to a MAINTENANCE actor', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      withV2Panel(async (input: RequestInfo | URL) => {
        const url = String(input)
        urls.push(url)
        if (url.includes('/me')) return jsonResponse(maintenanceMeBody)
        if (url.includes('/attachments/by-source/')) return jsonResponse([])
        return jsonResponse(repairDetail)
      }),
    )

    renderPageWithCapabilities()

    await waitFor(() => expect(screen.getByText('รหัสใบแจ้งซ่อม: RPR-0001')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'ปิดใบแจ้งซ่อม' })).toBeInTheDocument()
    expect(await screen.findByTestId('v2-data-context')).toBeInTheDocument() // the V2 team area
    expect(screen.queryByTestId('legacy-assignment-readonly')).toBeNull()
    expect(screen.queryByLabelText('ช่างผู้รับผิดชอบหลัก')).toBeNull()
    expect(screen.queryByRole('button', { name: 'บันทึกการมอบหมาย' })).toBeNull()
    expect(urls.some((u) => u.endsWith('/assign') || u.includes('assignment-history'))).toBe(false)
  })

  it.each([
    ['LEGACY', { assignment_model: 'LEGACY', primary_technician: 'legacy-user-1', collaborators: ['legacy-user-2'] }],
    ['blank', { assignment_model: '', primary_technician: 'legacy-user-1', collaborators: [] }],
    ['unknown', { assignment_model: 'technician_v2', primary_technician: 'legacy-user-1', collaborators: [] }],
  ])('a %s-model Repair is never rendered: unsupported state, no stored user id, no operation', async (_label, extra) => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      withV2Panel(async (input: RequestInfo | URL) => {
        const url = String(input)
        urls.push(url)
        if (url.includes('/me')) return jsonResponse(maintenanceMeBody)
        return jsonResponse({ ...repairDetail, repair: { ...repairDetail.repair, ...extra } })
      }),
    )

    renderPageWithCapabilities()

    expect(await screen.findByText('ใบงานนี้ไม่รองรับในระบบปัจจุบัน')).toBeInTheDocument()
    expect(screen.getByText('รหัสข้อผิดพลาด: ASSIGNMENT_MODEL_UNSUPPORTED')).toBeInTheDocument()
    expect(screen.queryByText(/legacy-user/)).toBeNull()
    expect(screen.queryByText('ตรวจสอบเบื้องต้น')).toBeNull()
    expect(screen.queryByRole('button', { name: 'ปิดใบแจ้งซ่อม' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'บันทึกการดำเนินการ' })).toBeNull()
    // Nothing beyond the detail itself (and the caller's own capabilities) is read for it.
    expect(urls.every((u) => u.includes('/me') || u.endsWith('/repairs/RPR-0001'))).toBe(true)
  })

  it('shows an error and does not close the repair when the close action fails (MAINTENANCE)', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      withV2Panel(async (input: RequestInfo | URL, init?: RequestInit) => {
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

  // ---------------------------------------------------------------- R5

  const substates = {
    repair_id: 'RPR-0001', periods: [], history: [], as_of: '2026-02-02T00:00:00Z',
    durations: { repairing_seconds: 0, awaiting_parts_seconds: 0, other_seconds: 86400, elapsed_seconds: 86400 },
  }
  const workTime = (unconfirmed: number) => ({
    work_kind: 'REPAIR', job_id: 'RPR-0001', status: 'OPEN', entries: [], confirmations: [], technicians: {},
    team: { regular_seconds: 0, overtime_seconds: 0, total_seconds: 0, technician_count: 0 },
    elapsed_seconds: 86400, unconfirmed_count: unconfirmed,
  })

  function installR5(post: (url: string, init: RequestInit) => Response | Promise<Response>) {
    const posts: { url: string; init: RequestInit }[] = []
    vi.stubGlobal(
      'fetch',
      withV2Panel(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (url.includes('/me')) return jsonResponse(maintenanceMeBody)
        if (url.includes('/attachments/by-source/')) return jsonResponse([])
        if (url.endsWith('/substates')) return jsonResponse(substates)
        if (url.endsWith('/work-time')) return jsonResponse(workTime(1))
        if (method === 'POST') {
          posts.push({ url, init: init! })
          return post(url, init!)
        }
        if (url.includes('/repairs/RPR-0001')) return jsonResponse(repairDetail)
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )
    return posts
  }

  it('R5: shows the substate and work-time panels on an OPEN repair', async () => {
    installR5(() => jsonResponse(repairDetail))
    renderPageWithCapabilities()
    expect(await screen.findByRole('heading', { name: 'สถานะย่อยงานซ่อม' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'เวลาทำงานของช่าง' })).toBeInTheDocument()
    expect(await screen.findByTestId('substate-durations')).toHaveTextContent('อื่น ๆ (ไม่ได้ระบุสถานะย่อย)1 วัน 0 ชม. 0 นาที')
    expect(await screen.findByTestId('wt-unconfirmed')).toHaveTextContent('ต้องยืนยันทุกรายการก่อนปิดงาน')
  })

  it('R8 PRE-UAT: shows the material (Store) panel and the TEST classification panel', async () => {
    installR5(() => jsonResponse(repairDetail))
    renderPageWithCapabilities()
    expect(await screen.findByRole('heading', { name: /อะไหล่ของใบงาน/ })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'จัดประเภทงานซ่อม' })).toBeInTheDocument()
    expect(screen.getByText('TEST candidate — ไม่อนุมัติสำหรับ REAL')).toBeInTheDocument()
  })

  it('R5 OD-2: a close refused for unconfirmed work time is explained and the repair stays open', async () => {
    const user = userEvent.setup()
    installR5(() =>
      jsonResponse({ error: { code: 'WORK_TIME_NOT_CONFIRMED', message: 'x', details: { unconfirmed_entries: 1 }, request_id: 'r' } }, 409),
    )
    renderPageWithCapabilities()
    await user.click(await screen.findByRole('button', { name: 'ปิดใบแจ้งซ่อม' }))
    expect(await screen.findByText(/กรุณายืนยันเวลาทำงานทุกรายการก่อนปิดใบแจ้งซ่อม/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ปิดใบแจ้งซ่อม' })).toBeInTheDocument()
  })

  it('R5 retry safety: an action with an unknown outcome is re-sent with the SAME request id', async () => {
    const user = userEvent.setup()
    let attempt = 0
    const posts = installR5(() => {
      attempt += 1
      if (attempt === 1) throw new TypeError('network down')
      return jsonResponse(repairDetail)
    })
    renderPageWithCapabilities()
    await user.type(await screen.findByLabelText('เพิ่มการดำเนินการ'), 'ถอดปั๊ม')
    await user.click(screen.getByText('บันทึกการดำเนินการ'))
    expect(await screen.findByText(/ไม่ทราบผลการบันทึก/)).toBeInTheDocument()
    await user.click(screen.getByText('บันทึกการดำเนินการ'))
    await waitFor(() => expect(posts).toHaveLength(2))
    const ids = posts.map((p) => new Headers(p.init.headers).get('X-Request-Id'))
    expect(ids[0]).toMatch(/^[0-9a-f-]{36}$/)
    expect(ids[1]).toBe(ids[0])
  })

  it('R5 retry safety: the close is sent with a request id', async () => {
    const user = userEvent.setup()
    const posts = installR5(() => jsonResponse({ ...repairDetail, repair: { ...repairDetail.repair, status: 'CLOSED' } }))
    renderPageWithCapabilities()
    await user.click(await screen.findByRole('button', { name: 'ปิดใบแจ้งซ่อม' }))
    await waitFor(() => expect(posts.some((p) => p.url.endsWith('/close'))).toBe(true))
    const close = posts.find((p) => p.url.endsWith('/close'))!
    expect(new Headers(close.init.headers).get('X-Request-Id')).toMatch(/^[0-9a-f-]{36}$/)
  })
})

// ISS-01 (R8 PRE-UAT browser UAT 2026-11-19): one "parts actually used" card with two separately labelled
// sources — confirmed Store uses (read-only) and the manually entered repair parts. Synthetic data only.
describe('RepairDetailPage — ISS-01 parts actually used', () => {
  afterEach(() => vi.unstubAllGlobals())

  const use = (over: Record<string, string> = {}) => ({ event_id: 'STE-1', event_type: 'USE_CONFIRMED', part_id: 'PART-0001',
    part_instance_id: '', part_code_snapshot: 'FLT-1', quantity: '1', unit: 'ชิ้น', position_code: 'ซ้าย',
    actor_user_id: 'USR-TEST-911', ...over })
  const manual = { ...repairDetail, parts: [{ repair_part_id: 'RPRP-1', repair_id: 'RPR-0001', part_description: 'ซีลมือ',
    quantity: 2, unit: 'อัน', action: null, part_instance_id: null, created_at: '2026-02-01T00:00:00Z' }] }

  function install(store: () => Response, detail: unknown = repairDetail) {
    vi.stubGlobal('fetch', withV2Panel(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/attachments/by-source/')) return jsonResponse([])
      return jsonResponse(detail)
    }))
    const inner = globalThis.fetch as unknown as (i: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).endsWith('/store-reconciliation') ? store() : inner(input, init)))
  }

  const rec = (events: unknown[], lines: unknown[] = []) => jsonResponse({ repair_id: 'RPR-0001', state: 'RECONCILED',
    blockers: [], lines, events, exceptions_note: '', scope_note: '' })
  const err = (status: number, code: string) => jsonResponse({ error: { code, message: 'x', request_id: 'r' } }, status)

  it('lists confirmed Store uses (part, instance, quantity, unit, position, source) apart from the manual list', async () => {
    install(() => rec([use(), use({ event_id: 'STE-2', part_id: 'PART-0005', part_instance_id: 'PINST-9', part_code_snapshot: '',
      position_code: '' }), { ...use({ event_id: 'STE-3' }), event_type: 'ISSUED' }]), manual)
    renderPage()
    const uses = await screen.findByRole('list', { name: 'อะไหล่ที่ยืนยันใช้จริงจากคลัง' })
    expect(within(uses).getAllByRole('listitem')).toHaveLength(2) // ISSUED is not a use
    expect(uses).toHaveTextContent('PART-0001 (FLT-1) · 1 ชิ้น · ตำแหน่ง ซ้าย')
    expect(within(uses).getByRole('link', { name: 'PINST-9' })).toHaveAttribute('href', '/part-instances/PINST-9')
    expect(uses).toHaveTextContent('แหล่งที่มา: คลัง STE-1 โดย USR-TEST-911')
    const legacy = screen.getByRole('list', { name: 'อะไหล่ที่บันทึกในใบซ่อมด้วยมือ' })
    expect(legacy).toHaveTextContent('ซีลมือ x2อัน')
    expect(legacy).not.toHaveTextContent('PART-0001') // never merged or duplicated
    expect(screen.getByRole('heading', { name: 'บันทึกในใบซ่อมด้วยมือ (ระบบเดิม)' })).toBeInTheDocument()
  })

  it('says "no confirmed use yet" only when the feed was read and holds none; the manual history stays', async () => {
    install(() => rec([]), manual)
    renderPage()
    expect(await screen.findByText('ยังไม่มีการยืนยันใช้จริงจากคลัง')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'อะไหล่ที่บันทึกในใบซ่อมด้วยมือ' })).toHaveTextContent('ซีลมือ')
  })

  it.each([
    [403, 'PREUAT_ACTION_NOT_AUTHORIZED', 'ไม่มีสิทธิ์ดูข้อมูลการเบิก-จ่ายของใบงานนี้'],
    [501, 'FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE', 'การยืนยันใช้จริงจากระบบเบิก-จ่ายไม่มีในโหมดข้อมูลนี้'],
    [500, 'INTERNAL_ERROR', 'อ่านข้อมูลการเบิก-จ่ายไม่สำเร็จ (INTERNAL_ERROR)'],
  ])('an unreadable feed (%s) is never shown as zero uses', async (status, code, text) => {
    install(() => err(status, code))
    renderPage()
    expect(await screen.findByText(new RegExp(text.replace(/[()]/g, '\\$&')))).toBeInTheDocument()
    expect(screen.queryByText('ยังไม่มีการยืนยันใช้จริงจากคลัง')).not.toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'อะไหล่ที่ยืนยันใช้จริงจากคลัง' })).not.toBeInTheDocument()
  })

  it('a failed read can be retried', async () => {
    let calls = 0
    install(() => { calls += 1; return calls <= 2 ? err(500, 'INTERNAL_ERROR') : rec([use()]) })
    renderPage()
    const retry = await screen.findByRole('button', { name: 'ลองอีกครั้ง' })
    await userEvent.click(retry)
    expect(await screen.findByRole('list', { name: 'อะไหล่ที่ยืนยันใช้จริงจากคลัง' })).toHaveTextContent('PART-0001')
  })

  it('shows the part name of the request line and never a TEST heading when the workflow is unavailable', async () => {
    install(() => rec([use({ requisition_line_id: 'REQL-1' } as Record<string, string>)],
      [{ requisition_line_id: 'REQL-1', part_description: 'ไส้กรองน้ำมัน' }]))
    renderPage()
    expect(await screen.findByRole('list', { name: 'อะไหล่ที่ยืนยันใช้จริงจากคลัง' })).toHaveTextContent('ไส้กรองน้ำมัน — PART-0001')
  })

  it('a 501 shows one neutral line without the TEST heading', async () => {
    install(() => err(501, 'FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE'))
    renderPage()
    await screen.findByText(/ไม่มีในโหมดข้อมูลนี้/)
    expect(screen.queryByRole('heading', { name: /ระบบเบิก-จ่าย — TEST/ })).not.toBeInTheDocument()
  })

  it.each([
    ['a malformed 2xx body', () => jsonResponse({ unexpected: true })],
    ['a network failure', () => { throw new TypeError('network down') }],
  ])('%s is an error with retry, never an empty list', async (_name, answer) => {
    install(answer as () => Response)
    renderPage()
    expect(await screen.findByRole('button', { name: 'ลองอีกครั้ง' })).toBeInTheDocument()
    expect(screen.queryByText('ยังไม่มีการยืนยันใช้จริงจากคลัง')).not.toBeInTheDocument()
  })
})

describe('RepairDetailPage — ISS-01 refresh after a Store write in the panel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('re-reads the confirmed uses after the panel records a use (read only, nothing written twice)', async () => {
    const line = { requisition_line_id: 'REQL-1', material_request_id: 'MR-1', part_id: 'PART-0001', part_description: 'ไส้กรองน้ำมัน',
      unit: 'ชิ้น', requested: '1', decision: 'APPROVED', approved: '1', issued: '1', used: '0', return_declared: '0',
      return_accepted: '0', unreconciled: '1', pending_return: '0', awaiting_issue: '0', issued_part_ids: ['PART-0001'],
      issued_parts: [{ part_id: 'PART-0001', part_instance_id: '', part_code_snapshot: 'FLT', issued: '1', used: '0',
        return_declared: '0', return_accepted: '0', unreconciled: '1' }], blockers: [] }
    let used = false
    const posts: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input)
      if (url.endsWith('/me')) return jsonResponse({ user_id: 'USR-TEST-911', roles: [], capabilities: ['can_view'] })
      if (url.endsWith('/technician-assignments')) {
        return jsonResponse({ job_id: 'RPR-0001', assignment_model: 'TECHNICIAN_V2', status: 'NONE', current: null, sets: [], withdrawals: [] })
      }
      if (url.includes('/technicians?')) return jsonResponse({ items: [], page: 1, page_size: 200, total_items: 0 })
      if (url.endsWith('/classification')) {
        return jsonResponse({ repair_id: 'RPR-0001', state: 'NOT_ELIGIBLE', blockers: [], draft_revision: 0, draft_rows: [], final: null,
          replayed: false, note_th: 'TEST candidate' })
      }
      if (init.method === 'POST') { posts.push(url); used = true; return jsonResponse({ replayed: false, material_request_id: 'MR-1', events: [] }) }
      if (url.endsWith('/store-reconciliation')) {
        return jsonResponse({ repair_id: 'RPR-0001', state: 'UNRECONCILED', blockers: [], exceptions_note: '', scope_note: '',
          lines: [used ? { ...line, used: '1', unreconciled: '0' } : line],
          events: used ? [{ event_id: 'STE-9', event_type: 'USE_CONFIRMED', requisition_line_id: 'REQL-1', part_id: 'PART-0001',
            part_instance_id: '', part_code_snapshot: 'FLT', quantity: '1', unit: 'ชิ้น', position_code: 'ซ้าย', actor_user_id: 'USR-TEST-911' }] : [] })
      }
      if (url.includes('/attachments/by-source/')) return jsonResponse([])
      return jsonResponse(repairDetail)
    }))
    renderPageWithCapabilities()
    expect(await screen.findByText('ยังไม่มีการยืนยันใช้จริงจากคลัง')).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'ยืนยันใช้จริง' }))
    await userEvent.type(screen.getByLabelText(/^จำนวน \(/), '1')
    await userEvent.type(screen.getByLabelText('ตำแหน่งที่ติดตั้ง *'), 'ซ้าย')
    await userEvent.click(screen.getByRole('button', { name: 'บันทึก' }))
    expect(await screen.findByRole('list', { name: 'อะไหล่ที่ยืนยันใช้จริงจากคลัง' })).toHaveTextContent('ไส้กรองน้ำมัน — PART-0001')
    expect(posts).toHaveLength(1) // the page itself writes nothing
  })
})
