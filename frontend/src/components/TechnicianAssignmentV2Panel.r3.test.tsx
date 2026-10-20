import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import type { TechnicianAssignments } from '../lib/technicianV2'
import { TechnicianAssignmentV2Panel } from './TechnicianAssignmentV2Panel'

/**
 * R3 L8 (Owner decision): on an R3 Finding round the V2 assign control needs
 * can_manage_finding_repair as well; L9: the lead is replaced, never withdrawn.
 * Non-R3 jobs are unchanged. Synthetic stubs only;
 * the backend is authoritative.
 */

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const SET = {
  assignment_set_id: 'SET-SYN-1', assigned_at: '2026-01-02T08:00:00Z', assigned_by_user_id: 'SYN-MGR',
  primary_technician_id: 'TEC-SYN-1', collaborator_technician_ids: [], reason_th: null, record_ids: ['R1'],
}
const VALID: TechnicianAssignments = { job_id: 'RPR-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'VALID', current: SET, sets: [SET], withdrawals: [] }
const TECHS = { items: [{ technician_id: 'TEC-SYN-1', first_name: 'ช่าง', last_name: 'หนึ่ง', active_status: 'ACTIVE' }], page: 1, page_size: 200, total_items: 1 }

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

function setup(capabilities: string[], r3FindingRound: boolean) {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    if (input === '/api/v1/me') return jsonResponse({ user_id: 'SYN-U', roles: [], capabilities, data_context: 'TEST' })
    if (input === '/api/v1/repairs/RPR-SYN-1/technician-assignments') return jsonResponse(VALID)
    if (input.startsWith('/api/v1/technicians?')) return jsonResponse(TECHS)
    throw new Error(`unexpected ${input}`)
  }))
  render(
    <MemoryRouter>
      <CapabilitiesProvider>
        <TechnicianAssignmentV2Panel kind="REPAIR" jobId="RPR-SYN-1" jobStatus="OPEN" r3FindingRound={r3FindingRound} />
      </CapabilitiesProvider>
    </MemoryRouter>,
  )
}

const MAINTENANCE = ['can_view', 'can_manage_repair', 'can_close_repair']
const MANAGER = [...MAINTENANCE, 'can_manage_finding_repair']

describe('R3 L8 — V2 assignment on an R3 Finding round', () => {
  it('can_manage_repair alone: no assign or withdraw control, an explicit Thai explanation', async () => {
    setup(MAINTENANCE, true)
    // L11 wording: the authority is the per-employee Finding capability, not a job title.
    expect(await screen.findByTestId('v2-assignment-finding-authority')).toHaveTextContent('สิทธิ์จัดการงานซ่อมจากรายการผิดปกติ')
    expect(screen.getAllByText('TEC-SYN-1').length).toBeGreaterThan(0) // the current set stays readable
    expect(screen.queryByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeNull()
    expect(screen.queryByRole('heading', { name: 'เปลี่ยนทีมช่าง' })).toBeNull()
  })

  it('the Maintenance Department Manager replaces the team; the lead is never withdrawn (L9)', async () => {
    setup(MANAGER, true)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'เปลี่ยนทีมช่าง' })).toBeInTheDocument())
    expect(screen.getByTestId('v2-assignment-r3-lead-kept')).toHaveTextContent('เปลี่ยนช่างหลักได้โดยมอบหมายทีมใหม่')
    expect(screen.queryByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeNull()
    expect(screen.queryByTestId('v2-assignment-finding-authority')).toBeNull()
  })

  it('a non-R3 job keeps the accepted behaviour for can_manage_repair', async () => {
    setup(MAINTENANCE, false)
    expect(await screen.findByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeInTheDocument()
    expect(screen.queryByTestId('v2-assignment-finding-authority')).toBeNull()
  })
})

describe('L11 — source-scoped Finding delegate', () => {
  const DELEGATE = ['can_view', 'can_manage_finding_repair']

  it('the Finding authority alone manages the team of an R3 round', async () => {
    setup(DELEGATE, true)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'เปลี่ยนทีมช่าง' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeNull() // L9 kept
    expect(screen.queryByTestId('v2-assignment-finding-authority')).toBeNull()
  })

  it('the Finding authority grants nothing on a non-R3 job', async () => {
    setup(DELEGATE, false)
    await waitFor(() => expect(screen.getAllByText('TEC-SYN-1').length).toBeGreaterThan(0))
    expect(screen.queryByRole('heading', { name: 'เปลี่ยนทีมช่าง' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'ถอนการมอบหมายช่างทั้งหมด' })).toBeNull()
  })
})
