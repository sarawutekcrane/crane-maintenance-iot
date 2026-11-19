import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { PmMasterTestPage } from './PmMasterTestPage'

// R8 PRE-UAT SG-PM — the PM Master TEST profile page. Synthetic data only.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const PREVIEW = { preview_id: 'PV-1', source_file: 'S.xlsx', source_digest: 'abcdef1234567890', registered_by: 'U',
  ledger: [{ entry_id: 'E-1', action: 'REVIEW', issue: 'METER_COMPONENT_UNRESOLVED', row_or_key: 'cycles!row:5',
    plan_scope: ['UAT8 PM Plan'], resolved: false }],
  mapping_candidates: [{ source_row: 'vehicle_pm_mapping!row:2', vehicle_ref: 'UAT8-VEH-01', plan_code: 'UAT8 PM Plan',
    plan_model: 'UAT8-V-A', status: 'MATCHED_PENDING_IMPLEMENTATION' }] }
const HEAD = { revision_id: 'R1', plan_code: 'UAT8 PM Plan', revision_number: 1, source_digest: 'abc', sets: [
  { set_key: 'UAT8-V-A|CRANE|A', model_variant: 'UAT8-V-A', section: 'CRANE', meter_type: 'ENGINE_HOUR',
    interval_value: 600, interval_unit: 'HOUR', independent_group: '', items: [{ item_key: 'I1', task_text: 'ตรวจน้ำมันไฮดรอลิก' }] }] }
const status = (over: Record<string, unknown> = {}) => ({ note_th: 'โปรไฟล์ทดสอบแผน PM หลัก (TEST เท่านั้น)', plan_code: 'UAT8 PM Plan',
  source_file: 'S.xlsx', latest_preview_id: null, head_revision: null, assignments: [], variant_approvals: [], ...over })

function install(caps: string[], current: () => Response, preview = PREVIEW) {
  const posts: { path: string; body: Record<string, unknown>; requestId: string | null }[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
    if (path === '/me') return json({ user_id: 'U', roles: [], capabilities: caps })
    if (path === '/pm-master-test/status') return current()
    if (path === '/pm-master-test/previews/PV-1') return json(preview)
    if (init.method === 'POST') {
      posts.push({ path, body: JSON.parse(String(init.body)), requestId: new Headers(init.headers).get('X-Request-Id') })
      return json({ ok: true })
    }
    throw new Error(path)
  }))
  return posts
}

const renderPage = () => render(<MemoryRouter><CapabilitiesProvider><PmMasterTestPage /></CapabilitiesProvider></MemoryRouter>)

afterEach(() => vi.unstubAllGlobals())

describe('PmMasterTestPage', () => {
  it('says the profile is not enabled when the backend answers 404', async () => {
    install(['can_view'], () => json({ error: { code: 'PM_MASTER_TEST_PROFILE_DISABLED', message: 'x', request_id: 'r' } }, 404))
    renderPage()
    expect(await screen.findByText(/ยังไม่เปิดโปรไฟล์ทดสอบแผน PM หลัก/)).toBeInTheDocument()
  })

  it('registers the synthetic source with a request id (publisher grant)', async () => {
    const posts = install(['can_view', 'can_test_pm_master_publish'], () => json(status()))
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'ลงทะเบียนต้นทางสังเคราะห์' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].path).toBe('/pm-master-test/previews')
    expect(posts[0].requestId).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('blocks publishing until the REVIEW entry is decided, then resolves the meter', async () => {
    const posts = install(['can_view', 'can_test_pm_master_publish'], () => json(status({ latest_preview_id: 'PV-1' })))
    renderPage()
    expect(await screen.findByRole('button', { name: 'เผยแพร่ฉบับที่ 1' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'ยืนยันมิเตอร์' })).toBeDisabled()
    await userEvent.selectOptions(screen.getByLabelText('มิเตอร์ที่ใช้'), 'CRANE')
    await userEvent.click(screen.getByRole('button', { name: 'ยืนยันมิเตอร์' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toMatchObject({ path: '/pm-master-test/previews/PV-1/reviews', body: {
      entry_id: 'E-1', outcome: 'RESOLVE_METER', expected_source_digest: 'abcdef1234567890',
      values: { meter_type: 'ENGINE_HOUR', driving_component: 'CRANE_ENGINE' } } })
  })

  it('approves the variant from the mapping rows and assigns a vehicle (separate grants)', async () => {
    const resolved = { ...PREVIEW, ledger: PREVIEW.ledger.map((e) => ({ ...e, resolved: true })) }
    const posts = install(['can_view', 'can_test_pm_master_publish', 'can_test_pm_master_assign'],
      () => json(status({ latest_preview_id: 'PV-1', head_revision: HEAD })), resolved)
    renderPage()
    expect(await screen.findByText('ตรวจน้ำมันไฮดรอลิก')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'อนุมัติ UAT8-V-A' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toMatchObject({ model_id: 'UAT8-MDL-A', model_variant: 'UAT8-V-A', expected_version: 0,
      source_rows: ['vehicle_pm_mapping!row:2'] })
    await userEvent.click(screen.getByRole('button', { name: 'กำหนดแผนให้ UAT8-VEH-01' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1]).toMatchObject({ path: '/pm-master-test/assignments', body: { vehicle_id: 'UAT8-VEH-01',
      plan_code: 'UAT8 PM Plan', expected_version: 0 } })
    expect(posts[0].requestId).not.toBe(posts[1].requestId)
  })

  it('is read-only without the TEST grants', async () => {
    install(['can_view'], () => json(status({ latest_preview_id: 'PV-1', head_revision: HEAD })))
    renderPage()
    expect(await screen.findByText(/ดูได้อย่างเดียว/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /ลงทะเบียน|เผยแพร่|อนุมัติ|กำหนดแผน/ })).not.toBeInTheDocument()
  })
})
