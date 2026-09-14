import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  assetTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  repairStatusLabel,
  repairStatusTone,
} from '../lib/labels'
import type { Page, RepairSummary } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: RepairSummary[] }

/**
 * "งานซ่อมค้าง" (Core Demo Fixes prompt, REPAIR WORKFLOW CORRECTIONS
 * section C) — every OPEN repair, for authorized maintenance/supervisory
 * use. Gated server-side by a development-safe role check (never a
 * production RBAC matrix) — GET /repairs/open-queue returns 403 for a
 * non-supervisory actor.
 */
export function OpenRepairQueuePage() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Page<RepairSummary>>('/repairs/open-queue?page_size=100')
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
      <h1>งานซ่อมค้าง</h1>
      <p>ใบแจ้งซ่อมที่ยังไม่ปิดงาน (OPEN) ทั้งหมด สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุง</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดงานซ่อมค้าง..." />}
      {state.kind === 'denied' && <PermissionDeniedState message="หน้านี้สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุงเท่านั้น" />}
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
              key: 'asset',
              header: 'สินทรัพย์',
              render: (row) => `${assetTypeLabel[row.asset_type] ?? row.asset_type} ${row.asset_id}`,
            },
            {
              key: 'symptom',
              header: 'อาการ/ปัญหาที่พบ',
              render: (row) => row.symptom ?? '-',
            },
            {
              key: 'assignment',
              header: 'ผู้รับผิดชอบ',
              render: (row) =>
                row.primary_technician
                  ? `${row.primary_technician}${row.collaborators.length ? ` +${row.collaborators.length}` : ''}`
                  : 'ยังไม่มอบหมาย',
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
          ]}
          rows={state.items}
          getRowKey={(row) => row.repair_id}
          emptyTitle="ไม่มีงานซ่อมค้างในขณะนี้"
          emptyDescription="ใบแจ้งซ่อมที่ยังไม่ปิดงานทั้งหมดจะแสดงที่นี่"
        />
      )}
    </section>
  )
}
