import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, formatThaiDateTime } from '../lib/labels'
import type { AssetType, InspectionSummary, Page } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: InspectionSummary[] }

/** Inspection history for one asset (Phase 3 scope item 11: "history").
 * Reachable from both Vehicle Detail and Equipment Detail. */
export function InspectionHistoryPage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''

  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Page<InspectionSummary>>(
      `/inspections?asset_type=${assetType}&asset_id=${assetId}&page_size=50`,
    )
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', items: result.data.items })
  }, [assetType, assetId])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section className="page">
      <h1>ประวัติการตรวจเช็ค</h1>
      <p>รหัสอ้างอิง: {assetId}</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดประวัติการตรวจเช็ค..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'submitted_at',
              header: 'วันที่ตรวจ',
              render: (row) => (
                <Link to={`/inspections/${row.inspection_id}`}>
                  {formatThaiDateTime(row.submitted_at)}
                </Link>
              ),
            },
            {
              key: 'result',
              header: 'ผลรวม',
              render: (row) =>
                row.has_fail ? (
                  <StatusBadge label={`ไม่ผ่าน ${row.fail_count} รายการ`} tone="danger" />
                ) : (
                  <StatusBadge label="ผ่านทุกรายการ" tone="success" />
                ),
            },
            {
              key: 'counts',
              header: 'ผ่าน/ไม่ผ่าน/ไม่เกี่ยวข้อง',
              render: (row) => `${row.pass_count} / ${row.fail_count} / ${row.na_count}`,
            },
            {
              key: 'inspector',
              header: 'ผู้ตรวจ',
              render: (row) => row.inspector_user_id ?? 'ไม่ทราบ',
            },
          ]}
          rows={state.items}
          getRowKey={(row) => row.inspection_id}
          emptyTitle="ยังไม่มีประวัติการตรวจเช็ค"
          emptyDescription="เริ่มตรวจเช็คครั้งแรกได้จากหน้ารายละเอียด"
        />
      )}
    </section>
  )
}
