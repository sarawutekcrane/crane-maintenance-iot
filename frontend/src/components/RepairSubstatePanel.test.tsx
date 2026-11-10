import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Repair, RepairSubstatePeriod, RepairSubstatesResponse } from '../lib/types'
import { RepairSubstatePanel } from './RepairSubstatePanel'

// R5 Repair substates กำลังซ่อม / รออะไหล่ — synthetic data only.

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const repair = {
  repair_id: 'RPR-1', asset_type: 'VEHICLE', asset_id: 'VEH-1048', source_type: 'MANUAL', source_id: null, category: null,
  symptom: null, meter_snapshot_id: null, status: 'OPEN', opened_at: '2026-11-01T00:00:00Z', opened_by: 'u', closed_at: null,
  closed_by: null, close_note: null, assignment_model: 'TECHNICIAN_V2',
} as unknown as Repair

function period(over: Partial<RepairSubstatePeriod> = {}): RepairSubstatePeriod {
  return {
    period_id: 'P1', revision: 1, record_kind: 'ENTRY', repair_id: 'RPR-1', substate: 'REPAIRING', started_at: '2026-11-01T01:00:00Z',
    ended_at: null, material_request_id: null, recorded_by: 'u', recorded_at: '2026-11-01T01:05:00Z', reason: null, request_id: 'r',
    request_fingerprint: 'f', is_test_data: 'TRUE', test_batch_id: 'B', ...over,
  }
}

function body(periods: RepairSubstatePeriod[], durations = { repairing_seconds: 5 * 86400, awaiting_parts_seconds: 10 * 86400, other_seconds: 0, elapsed_seconds: 15 * 86400 }): RepairSubstatesResponse {
  return { repair_id: 'RPR-1', periods, history: periods, durations, as_of: '2026-11-16T00:00:00Z' }
}

function install(initial: RepairSubstatesResponse, post?: (init: RequestInit) => Response) {
  const posts: RequestInit[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posts.push(init)
        return post ? post(init) : json(initial)
      }
      if (String(input).endsWith('/substates')) return json(initial)
      throw new Error(`unexpected ${String(input)}`)
    }),
  )
  return posts
}

afterEach(() => vi.unstubAllGlobals())

describe('RepairSubstatePanel', () => {
  it('EX-1: 5 days repairing + 10 days awaiting parts = 15 elapsed days, with "other" shown, not assumed', async () => {
    install(body([period({ ended_at: '2026-11-06T01:00:00Z' }), period({ period_id: 'P2', substate: 'AWAITING_PARTS', started_at: '2026-11-06T01:00:00Z', ended_at: '2026-11-16T01:00:00Z' })]))
    render(<RepairSubstatePanel repair={repair} awaitingPartsFlag={false} />)
    const durations = await screen.findByTestId('substate-durations')
    expect(durations).toHaveTextContent('กำลังซ่อม5 วัน 0 ชม. 0 นาที')
    expect(durations).toHaveTextContent('รออะไหล่10 วัน 0 ชม. 0 นาที')
    expect(durations).toHaveTextContent('อื่น ๆ (ไม่ได้ระบุสถานะย่อย)0 วัน 0 ชม. 0 นาที')
    expect(durations).toHaveTextContent('ระยะเวลาใบงานทั้งหมด15 วัน 0 ชม. 0 นาที')
  })

  it('shows the ongoing substate and keeps the Store flag as a separate statement', async () => {
    install(body([period({ substate: 'AWAITING_PARTS' })]))
    render(<RepairSubstatePanel repair={repair} awaitingPartsFlag />)
    expect(await screen.findByTestId('substate-current')).toHaveTextContent('รออะไหล่')
    expect(screen.getByTestId('store-awaiting-flag')).toHaveTextContent('ไม่ใช่ช่วงเวลารออะไหล่ที่บันทึก')
  })

  it('switching to awaiting parts closes the ongoing period in the same request with a request id', async () => {
    const posts = install(body([period()]), () => json(body([period({ ended_at: '2026-11-02T00:00:00Z' }), period({ period_id: 'P2', substate: 'AWAITING_PARTS' })])))
    const user = userEvent.setup()
    render(<RepairSubstatePanel repair={repair} awaitingPartsFlag={false} />)
    await user.click(await screen.findByRole('button', { name: 'รออะไหล่ (ตอนนี้)' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    const sent = JSON.parse(String(posts[0].body))
    expect(sent).toEqual({ substate: 'AWAITING_PARTS', close_ongoing: true }) // the server decides "now"
    expect(new Headers(posts[0].headers).get('X-Request-Id')).toMatch(/^[0-9a-f-]{36}$/)
    expect(await screen.findByTestId('substate-current')).toHaveTextContent('รออะไหล่')
  })

  it('a retrospective period is sent with Asia/Bangkok effective times', async () => {
    const posts = install(body([]))
    const user = userEvent.setup()
    render(<RepairSubstatePanel repair={repair} awaitingPartsFlag={false} />)
    await user.click(await screen.findByText('บันทึกช่วงสถานะย้อนหลัง'))
    await user.type(screen.getByLabelText('เริ่ม (เวลาที่เกิดขึ้นจริง)'), '2026-11-02T08:00')
    await user.type(screen.getByLabelText('สิ้นสุด (เว้นว่างถ้ายังดำเนินอยู่)'), '2026-11-03T08:00')
    await user.click(screen.getByRole('button', { name: 'บันทึกช่วงย้อนหลัง' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(JSON.parse(String(posts[0].body))).toEqual({
      substate: 'REPAIRING', started_at: '2026-11-02T08:00:00+07:00', ended_at: '2026-11-03T08:00:00+07:00',
    })
  })

  it('a conflict is explained and a transport failure keeps the request id for the resend', async () => {
    let attempt = 0
    const posts = install(body([]), () => {
      attempt += 1
      if (attempt === 1) return json({ error: { code: 'REPAIR_SUBSTATE_CONFLICT', message: 'x', details: null, request_id: 'r' } }, 409)
      if (attempt === 2) throw new TypeError('network down')
      return json(body([period()]))
    })
    const user = userEvent.setup()
    render(<RepairSubstatePanel repair={repair} awaitingPartsFlag={false} />)
    await user.click(await screen.findByRole('button', { name: 'เริ่ม/กลับมาซ่อม (ตอนนี้)' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ช่วงเวลานี้ซ้อนกับช่วงสถานะที่บันทึกไว้แล้ว')
    await user.click(screen.getByRole('button', { name: 'เริ่ม/กลับมาซ่อม (ตอนนี้)' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ไม่ทราบผลการบันทึก')
    const unknownId = new Headers(posts[1].headers).get('X-Request-Id')
    await user.click(screen.getByRole('button', { name: 'เริ่ม/กลับมาซ่อม (ตอนนี้)' }))
    await waitFor(() => expect(posts).toHaveLength(3))
    expect(new Headers(posts[0].headers).get('X-Request-Id')).not.toBe(unknownId) // a definite refusal ends the intent
    expect(new Headers(posts[2].headers).get('X-Request-Id')).toBe(unknownId)
    expect(posts[2].body).toBe(posts[1].body) // the resend repeats the identical request (same "now" time)
  })

  it('a closed repair offers no substate controls', async () => {
    install(body([period({ ended_at: '2026-11-02T00:00:00Z' })]))
    render(<RepairSubstatePanel repair={{ ...repair, status: 'CLOSED' } as Repair} awaitingPartsFlag={false} />)
    await screen.findByTestId('substate-period')
    expect(screen.queryByRole('button', { name: 'รออะไหล่ (ตอนนี้)' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'ยกเลิกช่วงนี้' })).toBeNull()
  })
})
