import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode } from '../lib/labels'
import { departmentStatusLabel } from '../lib/lifecycleAdapters'
import { listHref, listQueryParams, readListQuery } from '../lib/listQuery'
import type { Page, Department } from '../lib/types'

const PAGE_SIZE = 50

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; page: Page<Department> }

async function fetchPage(page: number): Promise<LoadState> {
  const result = await apiGet<Page<Department>>(`/departments?page=${page}&page_size=${PAGE_SIZE}`)
  if (!result.ok) {
    const err = result.error
    return {
      kind: 'error',
      message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
      requestId: err instanceof ApiError ? err.requestId : null,
    }
  }
  return { kind: 'ready', page: result.data }
}

/**
 * R2 Batch R2e — operational department list (the R2c-2 read: test rows are
 * never listed). Inactive departments stay visible. While the live
 * department_master tab does not exist, the read error is shown as "data
 * unavailable" — never as an empty list. Search text and page live in the URL.
 */
export function DepartmentListPage() {
  const [params, setParams] = useSearchParams()
  const query = readListQuery(params)
  const [draft, setDraft] = useState(query.q)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const reload = useCallback((page: number) => {
    setState({ kind: 'loading' })
    void fetchPage(page).then(setState)
  }, [])

  useEffect(() => {
    let cancelled = false
    void fetchPage(query.page).then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [query.page])

  const needle = query.q.trim().toLowerCase()
  const rows = state.kind === 'ready'
    ? state.page.items.filter((p) =>
      !needle || p.department_id.toLowerCase().includes(needle) || p.department_name_th.toLowerCase().includes(needle))
    : []
  const lastPage = state.kind === 'ready' ? Math.max(1, Math.ceil(state.page.total_items / PAGE_SIZE)) : 1
  const from = listHref('/departments', query)

  return (
    <section className="page">
      <h1>แผนก</h1>
      <p>รายชื่อแผนก แตะรายการเพื่อดูรายละเอียดและประวัติสถานะ</p>
      <Card>
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault()
            setParams(listQueryParams({ q: draft.trim(), page: query.page }))
          }}
        >
          <FormField label="ค้นหาในหน้านี้ (รหัส/ชื่อแผนก)" htmlFor="department-search-q">
            <input id="department-search-q" type="text" value={draft} onChange={(event) => setDraft(event.target.value)} />
          </FormField>
          <button type="submit" className="button button--primary button--full-width">ค้นหา</button>
        </form>
      </Card>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายชื่อแผนก..." />}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={() => reload(query.page)} />
      )}
      {state.kind === 'ready' && (
        <>
          <ResponsiveTable
            columns={[
              {
                key: 'department_id',
                header: 'รหัสแผนก',
                render: (p: Department) => (
                  <Link to={`/departments/${encodeURIComponent(p.department_id)}`} state={{ from }}>
                    <code>{p.department_id}</code>
                  </Link>
                ),
              },
              { key: 'name', header: 'ชื่อ', render: (p: Department) => p.department_name_th },
              { key: 'active_status', header: 'สถานะ', render: (p: Department) => departmentStatusLabel(p.is_active) },
            ]}
            rows={rows}
            getRowKey={(p) => p.department_id}
            emptyTitle="ไม่พบแผนก"
            emptyDescription={needle ? 'ลองเปลี่ยนคำค้นหา' : 'ยังไม่มีข้อมูลแผนกในระบบ'}
          />
          <div className="dialog__actions">
            <button type="button" className="button button--secondary" disabled={query.page <= 1}
              onClick={() => setParams(listQueryParams({ q: query.q, page: query.page - 1 }))}>
              หน้าก่อนหน้า
            </button>
            <span>หน้า {query.page} / {lastPage}</span>
            <button type="button" className="button button--secondary" disabled={query.page >= lastPage}
              onClick={() => setParams(listQueryParams({ q: query.q, page: query.page + 1 }))}>
              หน้าถัดไป
            </button>
          </div>
        </>
      )}
    </section>
  )
}
