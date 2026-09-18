import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ModelDocumentsPage } from './ModelDocumentsPage'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const historyBody = [
  {
    model_document_id: 'MDOC-0002',
    model_id: 'MODEL-0001',
    document_type: 'LOAD_CHART',
    document_name_th: 'ตารางยกของ',
    version: '2.0',
    effective_from: '2026-01-01',
    effective_to: null,
    storage_ref: 'attachments/load-chart-v2.pdf',
    file_status: 'UPLOADED',
    active_status: 'ACTIVE',
    replaced_by_document_id: null,
    note_th: null,
  },
  {
    model_document_id: 'MDOC-0001',
    model_id: 'MODEL-0001',
    document_type: 'SERVICE_MANUAL',
    document_name_th: 'คู่มือซ่อมบำรุง',
    version: '001',
    effective_from: null,
    effective_to: null,
    storage_ref: null,
    file_status: null,
    active_status: null,
    replaced_by_document_id: null,
    note_th: null,
  },
]

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/models/MODEL-0001/documents']}>
      <Routes>
        <Route path="/models/:modelId/documents" element={<ModelDocumentsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ModelDocumentsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows every document ever created for the model — history is never hidden', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(historyBody)))

    renderPage()

    await waitFor(() => expect(screen.getByText('ตารางยกของ')).toBeInTheDocument())
    expect(screen.getByText('คู่มือซ่อมบำรุง')).toBeInTheDocument()
    expect(screen.getByText('001')).toBeInTheDocument()
  })

  it('creates a document via POST', async () => {
    const user = userEvent.setup()
    const calls: { method: string; url: string; body?: unknown }[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        calls.push({
          method,
          url,
          body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
        })
        if (method === 'GET') return jsonResponse([])
        if (method === 'POST' && url.includes('/documents')) {
          return jsonResponse({
            ...historyBody[0],
            model_document_id: 'MDOC-0003',
            version: '1.0',
          })
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('+ เพิ่มเอกสาร')).toBeInTheDocument())
    await user.click(screen.getByText('+ เพิ่มเอกสาร'))
    await user.type(screen.getByLabelText('เวอร์ชัน/ฉบับที่'), '1.0')
    await user.click(screen.getByText('บันทึก'))

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === 'POST' && c.url.includes('/models/MODEL-0001/documents')),
      ).toBe(true),
    )
    const createCall = calls.find((c) => c.method === 'POST')
    expect(createCall?.body).toMatchObject({ version: '1.0' })
  })

  it('shows a Thai error message with request id when the load fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { error: { code: 'MODEL_NOT_FOUND', message: 'not found', request_id: 'req-1' } },
          404,
        ),
      ),
    )

    renderPage()

    await waitFor(() => expect(screen.getByText('ไม่พบข้อมูลรุ่นเครื่องจักรนี้')).toBeInTheDocument())
  })

  it('never renders a revision/replace/delete/upload control', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(historyBody)))

    renderPage()

    await waitFor(() => expect(screen.getByText('ตารางยกของ')).toBeInTheDocument())
    expect(screen.queryByText(/แก้ไขฉบับ|แทนที่เอกสาร|ลบเอกสาร|อัปโหลดไฟล์/)).not.toBeInTheDocument()
  })
})
