import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode } from '../lib/labels'
import { personnelName, personnelStatusLabel } from '../lib/lifecycleAdapters'
import { listHref, listQueryParams, readListQuery } from '../lib/listQuery'
import type { Page, Personnel } from '../lib/types'

const PAGE_SIZE = 50

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; page: Page<Personnel> }

async function fetchPage(page: number): Promise<LoadState> {
  const result = await apiGet<Page<Personnel>>(`/personnel?page=${page}&page_size=${PAGE_SIZE}`)
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
 * R2 Batch R2e — operational personnel list (the R2c-1 read: test rows are
 * never listed). Inactive records stay visible; an unknown status is shown as
 * unknown, never as active. Search text and page live in the URL.
 */
export function PersonnelListPage() {
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
      !needle || p.personnel_id.toLowerCase().includes(needle) || personnelName(p).toLowerCase().includes(needle))
    : []
  const lastPage = state.kind === 'ready' ? Math.max(1, Math.ceil(state.page.total_items / PAGE_SIZE)) : 1
  const from = listHref('/personnel', query)

  return (
    <section className="page">
      <h1>บุคลากร</h1>
      <p>รายชื่อบุคลากร (ข้อมูลบุคคล ไม่ใช่บัญชีผู้ใช้งาน) แตะรายการเพื่อดูรายละเอียดและประวัติสถานะ</p>
      <Card>
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault()
            setParams(listQueryParams({ q: draft.trim(), page: query.page }))
          }}
        >
          <FormField label="ค้นหาในหน้านี้ (รหัส/ชื่อ)" htmlFor="personnel-search-q">
            <input id="personnel-search-q" type="text" value={draft} onChange={(event) => setDraft(event.target.value)} />
          </FormField>
          <button type="submit" className="button button--primary button--full-width">ค้นหา</button>
        </form>
      </Card>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายชื่อบุคลากร..." />}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={() => reload(query.page)} />
      )}
      {state.kind === 'ready' && (
        <>
          <ResponsiveTable
            columns={[
              {
                key: 'personnel_id',
                header: 'รหัสบุคลากร',
                render: (p: Personnel) => (
                  <Link to={`/personnel/${encodeURIComponent(p.personnel_id)}`} state={{ from }}>
                    <code>{p.personnel_id}</code>
                  </Link>
                ),
              },
              { key: 'name', header: 'ชื่อ', render: (p: Personnel) => personnelName(p) },
              { key: 'active_status', header: 'สถานะ', render: (p: Personnel) => personnelStatusLabel(p.active_status) },
            ]}
            rows={rows}
            getRowKey={(p) => p.personnel_id}
            emptyTitle="ไม่พบบุคลากร"
            emptyDescription={needle ? 'ลองเปลี่ยนคำค้นหา' : 'ยังไม่มีข้อมูลบุคลากรในระบบ'}
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
