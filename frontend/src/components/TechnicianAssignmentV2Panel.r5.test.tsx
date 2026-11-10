import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import type { TechnicianAssignments } from '../lib/technicianV2'
import { TechnicianAssignmentV2Panel } from './TechnicianAssignmentV2Panel'

/**
 * R5 OD-1 — a PM work order also accepts a Technician V2 team change while IN_PROGRESS;
 * PENDING_REVIEW and terminal states do not; a Repair keeps the exactly-OPEN rule.
 * Presentation only (the server enforces the same rule). Synthetic stubs.
 */

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const SET = {
  assignment_set_id: 'SET-SYN-1', assigned_at: '2026-01-02T08:00:00Z', assigned_by_user_id: 'SYN-MGR',
  primary_technician_id: 'TEC-SYN-1', collaborator_technician_ids: ['TEC-SYN-2'], reason_th: null, record_ids: ['R1', 'R2'],
}
const VALID: TechnicianAssignments = { job_id: 'JOB-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'VALID', current: SET, sets: [SET], withdrawals: [] }
const TECHS = {
  items: [
    { technician_id: 'TEC-SYN-1', first_name: 'ช่าง', last_name: 'หนึ่ง', active_status: 'ACTIVE' },
    { technician_id: 'TEC-SYN-2', first_name: 'ช่าง', last_name: 'สอง', active_status: 'ACTIVE' },
    { technician_id: 'TEC-SYN-3', first_name: 'ช่าง', last_name: 'สาม', active_status: 'ACTIVE' },
  ],
  page: 1, page_size: 200, total_items: 3,
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function setup(kind: 'REPAIR' | 'PM', jobStatus: string) {
  const base = kind === 'REPAIR' ? '/api/v1/repairs/JOB-SYN-1' : '/api/v1/pm/work-orders/JOB-SYN-1'
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string) => {
      if (input === '/api/v1/me') return jsonResponse({ user_id: 'SYN-MGR', roles: [], capabilities: ['can_view', 'can_manage_repair', 'can_manage_pm'], data_context: 'TEST' })
      if (input === `${base}/technician-assignments`) return jsonResponse(VALID)
      if (input.startsWith('/api/v1/technicians?')) return jsonResponse(TECHS)
      throw new Error(`unexpected ${input}`)
    }),
  )
  render(
    <MemoryRouter>
      <CapabilitiesProvider>
        <TechnicianAssignmentV2Panel kind={kind} jobId="JOB-SYN-1" jobStatus={jobStatus} />
      </CapabilitiesProvider>
    </MemoryRouter>,
  )
}

describe('R5 OD-1 — team changes on a started PM work order', () => {
  it('PM IN_PROGRESS offers the assignment and withdrawal controls', async () => {
    setup('PM', 'IN_PROGRESS')
    expect(await screen.findByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeInTheDocument()
    expect(screen.queryByTestId('v2-assignment-closed')).toBeNull()
  })

  it.each(['PENDING_REVIEW', 'CLOSED', 'CANCELLED'])('PM %s offers no team change', async (jobStatus) => {
    setup('PM', jobStatus)
    expect(await screen.findByTestId('v2-assignment-closed')).toHaveTextContent(jobStatus)
    expect(screen.queryByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeNull()
  })

  it('a Repair keeps the exactly-OPEN rule (an IN_PROGRESS value never unlocks it)', async () => {
    setup('REPAIR', 'IN_PROGRESS')
    expect(await screen.findByTestId('v2-assignment-closed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeNull()
  })
})
