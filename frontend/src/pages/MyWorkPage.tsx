import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  assetTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  pmWorkOrderStatusLabel,
  pmWorkOrderStatusTone,
  repairSourceTypeLabel,
  repairStatusLabel,
  repairStatusTone,
} from '../lib/labels'
import type { Page, PmWorkOrderSummary, RepairSummary } from '../lib/types'

type LoadState<T> =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: T[] }

/**
 * "งานของฉัน" (Core Demo Fixes prompt, REPAIR WORKFLOW CORRECTIONS section
 * C) — OPEN repairs assigned (as primary technician or collaborator) to
 * the current application actor/user context. Backend resolves "current
 * actor" from RequestContext (dev-safe capability gate, not production
 * auth) via GET /repairs/my-work.
 */
export function MyWorkPage() {
  const [repairState, setRepairState] = useState<LoadState<RepairSummary>>({ kind: 'loading' })
  const [pmState, setPmState] = useState<LoadState<PmWorkOrderSummary>>({ kind: 'loading' })

  const loadRepairs = useCallback(async () => {
    setRepairState({ kind: 'loading' })
    const result = await apiGet<Page<RepairSummary>>('/repairs/my-work?page_size=50')
    if (!result.ok) {
      const err = result.error
      setRepairState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setRepairState({ kind: 'ready', items: result.data.items })
  }, [])

  // Core Demo Fixes Delta REV06 section 18 — PM My Work: derived exactly
  // like Repair My Work above (active assignment to the current actor via
  // GET /pm/work-orders/my-work), smallest safe addition to this existing
  // page rather than a separate screen.
  const loadPmWorkOrders = useCallback(async () => {
    setPmState({ kind: 'loading' })
    const result = await apiGet<Page<PmWorkOrderSummary>>('/pm/work-orders/my-work?page_size=50')
    if (!result.ok) {
      const err = result.error
      setPmState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setPmState({ kind: 'ready', items: result.data.items })
  }, [])

  useEffect(() => {
    void loadRepairs()
    void loadPmWorkOrders()
  }, [loadRepairs, loadPmWorkOrders])

  return (
    <section className="page">
      <h1>งานของฉัน</h1>

      <h2>ใบแจ้งซ่อม</h2>
      <p>ใบแจ้งซ่อมที่กำลังดำเนินการ (OPEN) ซึ่งได้รับมอบหมายให้ฉันเป็นช่างหลักหรือผู้ร่วมงาน</p>

      {repairState.kind === 'loading' && <LoadingState message="กำลังโหลดงานของฉัน..." />}
      {repairState.kind === 'error' && (
        <ErrorState
          message={repairState.message}
          requestId={repairState.requestId}
          onRetry={loadRepairs}
        />
      )}

      {repairState.kind === 'ready' && (
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
          ]}
          rows={repairState.items}
          getRowKey={(row) => row.repair_id}
          emptyTitle="ยังไม่มีงานที่มอบหมายให้ฉัน"
          emptyDescription="เมื่อได้รับมอบหมายใบแจ้งซ่อมที่ยังไม่ปิดงาน รายการจะแสดงที่นี่"
        />
      )}

      <h2>ใบสั่งงาน PM</h2>
      <p>ใบสั่งงาน PM ที่กำลังดำเนินการ (OPEN) ซึ่งได้รับมอบหมายให้ฉันเป็นช่างหลักหรือผู้ร่วมงาน</p>

      {pmState.kind === 'loading' && <LoadingState message="กำลังโหลดงาน PM ของฉัน..." />}
      {pmState.kind === 'error' && (
        <ErrorState message={pmState.message} requestId={pmState.requestId} onRetry={loadPmWorkOrders} />
      )}

      {pmState.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'opened_at',
              header: 'วันที่เปิดงาน',
              render: (row) => (
                <Link to={`/pm/work-orders/${row.pm_work_order_id}`}>
                  {formatThaiDateTime(row.opened_at)}
                </Link>
              ),
            },
            {
              key: 'asset',
              header: 'สินทรัพย์',
              render: (row) => `${assetTypeLabel[row.asset_type] ?? row.asset_type} ${row.asset_id}`,
            },
            {
              key: 'result_count',
              header: 'จำนวนผลงานที่บันทึกแล้ว',
              render: (row) => row.result_count,
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
          ]}
          rows={pmState.items}
          getRowKey={(row) => row.pm_work_order_id}
          emptyTitle="ยังไม่มีงาน PM ที่มอบหมายให้ฉัน"
          emptyDescription="เมื่อได้รับมอบหมายใบสั่งงาน PM ที่ยังไม่ปิดงาน รายการจะแสดงที่นี่"
        />
      )}
    </section>
  )
}
