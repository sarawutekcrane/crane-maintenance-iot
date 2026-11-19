import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilitiesProvider } from '../lib/capabilities'
import { MasterDataPage } from './MasterDataPage'

// R8 PRE-UAT (workstream A) — "ข้อมูลหลัก" page (models / branches / technicians). Synthetic data.
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function installApi(caps: string[], status = 200) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), 'http://localhost').pathname.replace('/api/v1', '')
    if (path === '/me') return json({ user_id: 'USR-1', roles: [], capabilities: caps, is_dev_auth: true })
    if (path.startsWith('/master-records/')) {
      if (status !== 200) return json({ error: { code: 'ACCESS_ACTOR_NOT_VERIFIED', message: 'x', request_id: 'r' } }, status)
      const entity = path.split('/')[2]
      return json({ entity, note_th: 'รายการ TEST เท่านั้น', items: entity === 'models'
        ? [{ model_id: 'MODEL-0002', model_code: 'A', model_name: 'จริง', scope: 'REAL' },
           { model_id: 'MODEL-TEST-5001', model_code: 'T', model_name: 'ทดสอบ', scope: 'TEST' }]
        : [{ branch_id: 'BR-RAYONG', branch_name: 'ระยอง', scope: 'REAL' }] })
    }
    throw new Error(`Unexpected fetch: ${path}`)
  }))
}

const renderPage = () => render(<MemoryRouter><CapabilitiesProvider><MasterDataPage /></CapabilitiesProvider></MemoryRouter>)

afterEach(() => vi.unstubAllGlobals())

describe('MasterDataPage', () => {
  it('lists models; only TEST rows get an edit button for a grant holder', async () => {
    installApi(['can_view', 'can_test_manage_master_records'])
    renderPage()
    expect(await screen.findByText('MODEL-TEST-5001')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'แก้ไข' })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'เพิ่มรุ่นรถ (TEST)' })).toBeInTheDocument()
  })

  it('switches tabs and is read-only without the grant', async () => {
    installApi(['can_view'])
    renderPage()
    await screen.findByText('MODEL-0002')
    await userEvent.click(screen.getByRole('tab', { name: 'สาขา' }))
    expect(await screen.findByText('BR-RAYONG')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /เพิ่ม/ })).not.toBeInTheDocument()
  })

  it('shows a permission message on 403', async () => {
    installApi([], 403)
    renderPage()
    expect(await screen.findByText('ไม่มีสิทธิ์ดูข้อมูลนี้')).toBeInTheDocument()
  })
})
