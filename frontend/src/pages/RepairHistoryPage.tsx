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
  repairSourceTypeLabel,
  repairStatusLabel,
  repairStatusTone,
} from '../lib/labels'
import type { AssetType, Page, RepairSummary } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: RepairSummary[] }

export function RepairHistoryPage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''
  const newRepairPath = vehicleId
    ? `/vehicle/${vehicleId}/repairs/new`
    : `/equipment/${equipmentId}/repairs/new`

  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Page<RepairSummary>>(
      `/repairs?asset_type=${assetType}&asset_id=${assetId}&page_size=50`,
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
      <h1>ประวัติการแจ้งซ่อม</h1>
      <p>รหัสอ้างอิง: {assetId}</p>

      <Link to={newRepairPath} className="button button--primary button--full-width">
        แจ้งซ่อมใหม่
      </Link>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดประวัติการแจ้งซ่อม..." />}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'opened_at',
              header: 'วันที่แจ้งซ่อม',
              render: (row) => (
                <Link to={`/repairs/${row.repair_id}`}>{formatThaiDateTime(row.opened_at)}</Link>
              ),
            },
            {
              key: 'source',
              header: 'แหล่งที่มา',
              render: (row) => repairSourceTypeLabel[row.source_type] ?? row.source_type,
            },
            {
              key: 'status',
              header: 'สถานะ',
              render: (row) => (
                <StatusBadge
                  label={repairStatusLabel[row.status] ?? row.status}
                  tone={repairStatusTone[row.status]}
                />
              ),
            },
            { key: 'action_count', header: 'จำนวนการดำเนินการ', render: (row) => row.action_count },
          ]}
          rows={state.items}
          getRowKey={(row) => row.repair_id}
          emptyTitle="ยังไม่มีประวัติการแจ้งซ่อม"
          emptyDescription="แจ้งซ่อมครั้งแรกได้จากปุ่มด้านบน"
        />
      )}
    </section>
  )
}
