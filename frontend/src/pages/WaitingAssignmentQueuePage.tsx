import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { ApiError, apiGet } from '../lib/apiClient'
import { assetTypeLabel, describeErrorCode, formatThaiDateTime } from '../lib/labels'
import type { Page, RepairSummary } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: RepairSummary[] }

/**
 * "รอมอบหมายช่าง" (Core Demo Fixes Delta REV05 section 5B) — every OPEN
 * Repair with no active PRIMARY technician. Derived from the same
 * `primary_technician` field the assignment endpoint keeps in sync —
 * never a separate stored table. Maintenance-only.
 */
export function WaitingAssignmentQueuePage() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Page<RepairSummary>>('/repairs/waiting-assignment?page_size=100')
    if (!result.ok) {
      const err = result.error
      if (err instanceof ApiError && err.status === 403) {
        setState({ kind: 'denied' })
        return
      }
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', items: result.data.items })
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section className="page">
      <h1>รอมอบหมายช่าง</h1>
      <p>ใบแจ้งซ่อมที่เปิดแล้วแต่ยังไม่ได้มอบหมายช่างผู้รับผิดชอบหลัก สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุง</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายการรอมอบหมาย..." />}
      {state.kind === 'denied' && (
        <PermissionDeniedState message="หน้านี้สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุงเท่านั้น" />
      )}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'opened_at',
              header: 'วันที่เปิดงาน',
              render: (row) => (
                <Link to={`/repairs/${row.repair_id}`}>{formatThaiDateTime(row.opened_at)}</Link>
              ),
            },
            {
              key: 'asset',
              header: 'สินทรัพย์',
              render: (row) => `${assetTypeLabel[row.asset_type] ?? row.asset_type} ${row.asset_id}`,
            },
            {
              key: 'symptom',
              header: 'อาการ/ปัญหาที่พบ',
              render: (row) => row.symptom ?? '-',
            },
          ]}
          rows={state.items}
          getRowKey={(row) => row.repair_id}
          emptyTitle="ไม่มีงานรอมอบหมายในขณะนี้"
          emptyDescription="ใบแจ้งซ่อมที่ยังไม่ได้มอบหมายช่างจะแสดงที่นี่"
        />
      )}
    </section>
  )
}
