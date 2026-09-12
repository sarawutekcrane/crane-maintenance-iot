import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
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

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: PmWorkOrderSummary[] }

export function PmWorkOrderHistoryPage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''

  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Page<PmWorkOrderSummary>>(
      `/pm/work-orders?asset_type=${assetType}&asset_id=${assetId}&page_size=50`,
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
      <h1>ประวัติ PM</h1>
      <p>รหัสอ้างอิง: {assetId}</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดประวัติ PM..." />}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'opened_at',
              header: 'วันที่เปิดใบสั่งงาน',
              render: (row) => (
                <Link to={`/pm/work-orders/${row.pm_work_order_id}`}>
                  {formatThaiDateTime(row.opened_at)}
                </Link>
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
          rows={state.items}
          getRowKey={(row) => row.pm_work_order_id}
          emptyTitle="ยังไม่มีประวัติ PM"
          emptyDescription="เริ่มทำ PM ครั้งแรกได้จากหน้าสรุป PM"
        />
      )}
    </section>
  )
}
