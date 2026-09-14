import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PmWorkOrderDetailPage } from './PmWorkOrderDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const workOrder = {
  pm_work_order_id: 'PMWO-0001',
  asset_type: 'VEHICLE',
  asset_id: 'VEH-1046',
  pm_plan_id: 'PMP-0001',
  revision_id: 'PMREV-0001',
  due_reason: null,
  status: 'OPEN',
  opened_at: '2026-02-01T00:00:00Z',
  opened_by: 'dev-user',
  closed_at: null,
  closed_by: null,
  note: null,
}

const revisionDetail = {
  plan: {
    pm_plan_id: 'PMP-0001',
    plan_code: 'PLAN1',
    asset_type: 'VEHICLE',
    name: 'แผนบำรุงรักษาเชิงป้องกัน PLAN1',
    model_ids: [],
  },
  revision: {
    revision_id: 'PMREV-0001',
    pm_plan_id: 'PMP-0001',
    revision_number: 1,
    effective_date: '2026-01-01',
    source_revision_note: null,
    created_at: '2026-01-15T08:00:00Z',
  },
  tasks: [
    {
      pm_task_id: 'PMT-0001',
      revision_id: 'PMREV-0001',
      sequence: 1,
      group: null,
      description: 'งานบำรุงรักษาตัวอย่างที่ 1 (PLAN1)',
      trigger_type: null,
      interval_value: null,
      interval_unit: null,
      standard_parts: [],
    },
  ],
}

const currentMachineStateBody = {
  asset_type: 'VEHICLE',
  asset_id: 'VEH-1046',
  readings: [],
  latitude: null,
  longitude: null,
  gps_observed_at: null,
  note: 'แสดงค่าล่าสุดที่ระบบทราบเท่านั้น (อ่านอย่างเดียว)',
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/pm/work-orders/PMWO-0001']}>
      <Routes>
        <Route path="/pm/work-orders/:workOrderId" element={<PmWorkOrderDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PmWorkOrderDetailPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads the work order, its exact task revision, and vehicle components', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/pm/work-orders/PMWO-0001') && !url.includes('/results'))
          return jsonResponse({ work_order: workOrder, results: [] })
        if (url.includes('/pm/plans/PMP-0001/revisions/PMREV-0001'))
          return jsonResponse(revisionDetail)
        if (url.includes('/machine-state/current')) return jsonResponse(currentMachineStateBody)
        throw new Error(`Unexpected fetch: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() =>
      expect(screen.getByText('งานบำรุงรักษาตัวอย่างที่ 1 (PLAN1)')).toBeInTheDocument(),
    )
    expect(screen.getByText('รหัสใบสั่งงาน: PMWO-0001')).toBeInTheDocument()
    // Manual counter/GPS entry no longer exists on this page — the
    // backend automatically captures machine state; the page only shows
    // the read-only current-state preview.
    await waitFor(() =>
      expect(screen.getByText('ค่ามาตรวัดปัจจุบัน (อ่านอย่างเดียว)')).toBeInTheDocument(),
    )
  })

  it('submits a task result and shows it as an immutable completed record', async () => {
    const user = userEvent.setup()
    let submittedResult: unknown = null

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'

        if (method === 'GET' && url.includes('/pm/work-orders/PMWO-0001') && !url.includes('/results')) {
          return jsonResponse({
            work_order: workOrder,
            results: submittedResult ? [submittedResult] : [],
          })
        }
        if (url.includes('/pm/plans/PMP-0001/revisions/PMREV-0001')) return jsonResponse(revisionDetail)
        if (url.includes('/machine-state/current')) return jsonResponse(currentMachineStateBody)
        if (method === 'POST' && url.includes('/results')) {
          const body = JSON.parse(init?.body as string)
          submittedResult = {
            pm_work_result_id: 'PMWR-0001',
            pm_work_order_id: 'PMWO-0001',
            pm_task_id: body.pm_task_id,
            revision_id: 'PMREV-0001',
            sequence: 1,
            task_description: 'งานบำรุงรักษาตัวอย่างที่ 1 (PLAN1)',
            completed: body.completed,
            meter_snapshot_id: null,
            remark: body.remark,
            used_parts: [],
            evidence_attachment_ids: [],
            performed_by: 'dev-user',
            performed_at: '2026-02-01T00:05:00Z',
          }
          return jsonResponse({ work_order: workOrder, results: [submittedResult] })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('บันทึกผลงาน')).toBeInTheDocument())
    await user.click(screen.getByText('บันทึกผลงาน'))

    await waitFor(() => expect(screen.getByText('ผลงาน: เสร็จสิ้น')).toBeInTheDocument())
    // Once a result exists, the entry form (submit button) is no longer shown.
    expect(screen.queryByText('บันทึกผลงาน')).not.toBeInTheDocument()
  })
})
