import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { JobAssignmentSection } from './JobAssignmentSection'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.unstubAllGlobals())

function renderSection(model: unknown, urls: string[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string) => {
      urls.push(input)
      if (input === '/api/v1/me') {
        return jsonResponse({ user_id: 'SYN-USER', roles: [], capabilities: ['can_view', 'can_manage_pm'], technician_assignment_v2_enabled: true, data_context: 'TEST' })
      }
      if (input === '/api/v1/pm/work-orders/PMWO-SYN-1/technician-assignments') {
        return jsonResponse({ job_id: 'PMWO-SYN-1', assignment_model: 'TECHNICIAN_V2', status: 'NONE', current: null, sets: [] })
      }
      if (input.startsWith('/api/v1/technicians?')) {
        return jsonResponse({ items: [{ technician_id: 'TEC-SYN-1', first_name: 'ช่าง', last_name: 'หนึ่ง', active_status: 'ACTIVE' }], page: 1, page_size: 200, total_items: 1 })
      }
      throw new Error(`unexpected ${input}`)
    }),
  )
  return render(
    <MemoryRouter>
      <CapabilitiesProvider>
        <JobAssignmentSection kind="PM" jobId="PMWO-SYN-1" jobStatus="OPEN" assignmentModel={model} legacyPrimary="legacy-u" legacyCollaborators={[]} />
      </CapabilitiesProvider>
    </MemoryRouter>,
  )
}

describe('JobAssignmentSection (B5, PM and Repair detail)', () => {
  it('TECHNICIAN_V2 (PM): the V2 panel on the PM assignment routes, with the TEST label', async () => {
    const urls: string[] = []
    renderSection('TECHNICIAN_V2', urls)
    expect(await screen.findByRole('button', { name: 'บันทึกการมอบหมายช่าง' })).toBeInTheDocument()
    expect(screen.getByTestId('v2-data-context')).toHaveTextContent('TEST')
    expect(urls).toContain('/api/v1/pm/work-orders/PMWO-SYN-1/technician-assignments')
  })

  it('LEGACY: read-only legacy ids, no V2 read, no control', async () => {
    const urls: string[] = []
    renderSection('LEGACY', urls)
    expect(await screen.findByTestId('legacy-assignment-readonly')).toBeInTheDocument()
    expect(screen.getByText('legacy-u')).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
    expect(urls.some((u) => u.includes('technician-assignments'))).toBe(false)
  })

  it.each([undefined, null, '', 'legacy', 'V2', 'INVALID'])('%s: fail closed with an explicit error and no control', async (model) => {
    const urls: string[] = []
    renderSection(model, urls)
    expect(await screen.findByText('รูปแบบการมอบหมายของงานนี้ไม่ถูกต้อง')).toBeInTheDocument()
    expect(screen.getByText('รหัสข้อผิดพลาด: ASSIGNMENT_MODEL_INVALID')).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
    expect(urls.some((u) => u.includes('technician-assignments'))).toBe(false)
  })
})
