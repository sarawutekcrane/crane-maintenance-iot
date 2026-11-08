import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  describeErrorCode,
  formatThaiDateTime,
  pmWorkOrderStatusLabel,
  pmWorkOrderStatusTone,
} from '../lib/labels'
import type { AssetType, Page, PmWorkOrderSummary } from '../lib/types'

export const HISTORY_PAGE_SIZE = 50

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; data: Page<PmWorkOrderSummary> }

function readPage(raw: string | null): number {
  const value = Number(raw)
  return Number.isInteger(value) && value >= 1 ? value : 1
}

async function fetchHistory(assetType: AssetType, assetId: string, page: number): Promise<LoadState> {
  const query = new URLSearchParams({
    asset_type: assetType,
    asset_id: assetId,
    page: String(page),
    page_size: String(HISTORY_PAGE_SIZE),
  })
  const result = await apiGet<Page<PmWorkOrderSummary>>(`/pm/work-orders?${query.toString()}`)
  if (result.ok) return { kind: 'ready', data: result.data }
  const err = result.error
  // A refused or failed read is never shown as "no history".
  if (err instanceof ApiError && err.status === 403) return { kind: 'denied' }
  return {
    kind: 'error',
    message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
    requestId: err instanceof ApiError ? err.requestId : null,
  }
}

/**
 * The PM history of one vehicle or equipment, every Work Order reachable by
 * server pages (newest first). The page lives in the URL, so returning from a
 * Work Order keeps it. A result belongs to the request that produced it, so a
 * page change never shows the previous page's rows.
 */
export function PmWorkOrderHistoryPage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''
  const [searchParams, setSearchParams] = useSearchParams()
  const page = readPage(searchParams.get('page'))
  const [reload, setReload] = useState(0)
  const requestKey = `${assetType}|${assetId}|${page}|${reload}`
  const [loaded, setLoaded] = useState<{ key: string; state: LoadState } | null>(null)
  const state: LoadState = loaded?.key === requestKey ? loaded.state : { kind: 'loading' }

  useEffect(() => {
    let cancelled = false
    void fetchHistory(assetType, assetId, page).then((next) => {
      if (!cancelled) setLoaded({ key: requestKey, state: next })
    })
    return () => {
      cancelled = true
    }
  }, [assetType, assetId, page, requestKey])

  const goTo = (next: number) => setSearchParams(next > 1 ? { page: String(next) } : {})
  const totalPages = state.kind === 'ready' ? Math.max(1, Math.ceil(state.data.total_items / HISTORY_PAGE_SIZE)) : 1
  const outOfRange = state.kind === 'ready' && page > totalPages

  return (
    <section className="page">
      <h1>ประวัติ PM</h1>
      <p>รหัสอ้างอิง: {assetId}</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดประวัติ PM..." />}
      {state.kind === 'denied' && <PermissionDeniedState />}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={() => setReload((n) => n + 1)} />
      )}

      {state.kind === 'ready' && (
        <>
          <p className="form-field__hint" data-testid="pm-history-total">
            ทั้งหมด {state.data.total_items} รายการ
          </p>
          {outOfRange ? (
            <div className="state-panel" role="status" data-testid="pm-history-out-of-range">
              <p>
                ไม่มีหน้า {page} — {state.data.total_items > 0 ? `มีทั้งหมด ${totalPages} หน้า` : 'ยังไม่มีประวัติ PM'}
              </p>
              <button type="button" className="button" onClick={() => goTo(totalPages)}>
                {totalPages > 1 ? `ไปหน้าสุดท้าย (หน้า ${totalPages})` : 'ไปหน้าแรก'}
              </button>
            </div>
          ) : (
            <ResponsiveTable
              columns={[
                {
                  key: 'opened_at',
                  header: 'วันที่เปิดใบสั่งงาน',
                  render: (row) => (
                    <Link to={`/pm/work-orders/${row.pm_work_order_id}`}>{formatThaiDateTime(row.opened_at)}</Link>
                  ),
                },
                {
                  key: 'plan',
                  header: 'แผน',
                  render: (row) => row.pm_plan_id,
                },
                {
                  key: 'status',
                  header: 'สถานะ',
                  render: (row) => (
                    <StatusBadge
                      label={pmWorkOrderStatusLabel[row.status] ?? row.status}
                      tone={pmWorkOrderStatusTone[row.status]}
                    />
                  ),
                },
                { key: 'result_count', header: 'จำนวนงานที่บันทึก', render: (row) => row.result_count },
              ]}
              rows={state.data.items}
              getRowKey={(row) => row.pm_work_order_id}
              emptyTitle="ยังไม่มีประวัติ PM"
              emptyDescription="เริ่มทำ PM ครั้งแรกได้จากหน้าสรุป PM"
            />
          )}
          {totalPages > 1 && !outOfRange && (
            <div className="status-card__actions">
              <button
                type="button"
                className="button button--secondary"
                disabled={page <= 1}
                onClick={() => goTo(page - 1)}
              >
                ก่อนหน้า
              </button>
              <span>
                หน้า {page} / {totalPages}
              </span>
              <button
                type="button"
                className="button button--secondary"
                disabled={page >= totalPages}
                onClick={() => goTo(page + 1)}
              >
                ถัดไป
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
