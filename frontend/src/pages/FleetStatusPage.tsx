import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, operationalStatusLabel, operationalStatusTone } from '../lib/labels'
import type { FleetStatusSummary, OperationalStatus } from '../lib/types'

const STATUS_ORDER: OperationalStatus[] = [
  'WORKING',
  'READY',
  'MAINTENANCE',
  'OUT_OF_SERVICE',
  'LONG_TERM_PARKING',
]

// Data-quality and schema failures are "numbers withheld on purpose", not
// a transient load failure; every other failure uses the generic title.
const WITHHELD_CODES = new Set(['VEHICLE_MASTER_DATA_INVALID', 'VEHICLE_MASTER_SCHEMA_INVALID'])

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; title: string; message: string; requestId?: string | null }
  | { kind: 'ready'; summary: FleetStatusSummary }

function toErrorState(err: ApiError | Error): LoadState {
  if (err instanceof ApiError && err.status === 403) return { kind: 'denied' }
  const code = err instanceof ApiError ? err.code : undefined
  return {
    kind: 'error',
    title: code && WITHHELD_CODES.has(code) ? 'ไม่แสดงตัวเลขสรุป' : 'โหลดภาพรวมกองรถไม่สำเร็จ',
    message: describeErrorCode(code),
    requestId: err instanceof ApiError ? err.requestId : null,
  }
}

/**
 * "ภาพรวมกองรถ" (Web/API Phase 7 Batch 7B2) — global counts of vehicle
 * master records by recorded operational status, from ONE page-owned
 * GET /dashboard/fleet-status per load or refresh. Numbers are rendered
 * only on success, exactly as the server sent them; loading, error and
 * permission states never show a number. Status cards are deliberately
 * not links: the only navigation is the plain unfiltered vehicle list.
 */
export function FleetStatusPage() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  // Request generation: only the latest request's success OR error is
  // applied, so a slow older response can never replace a newer one.
  const generation = useRef(0)

  // `load` only fetches and applies the result; `reload` (called from
  // event handlers) hides the current numbers by showing loading first.
  const load = useCallback(async () => {
    const current = ++generation.current
    const result = await apiGet<FleetStatusSummary>('/dashboard/fleet-status')
    if (current !== generation.current) return
    setState(result.ok ? { kind: 'ready', summary: result.data } : toErrorState(result.error))
  }, [])

  const reload = () => {
    setState({ kind: 'loading' })
    void load()
  }

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section className="page">
      <h1>ภาพรวมกองรถ</h1>
      <p>สรุปจำนวนรถตามสถานะที่บันทึกในทะเบียนรถ</p>
      <div className="fleet-status__toolbar">
        <button type="button" className="button button--secondary" onClick={reload}>
          โหลดข้อมูลใหม่
        </button>
      </div>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดภาพรวมกองรถ..." />}
      {state.kind === 'denied' && <PermissionDeniedState />}
      {state.kind === 'error' && (
        <ErrorState
          title={state.title}
          message={state.message}
          requestId={state.requestId}
          onRetry={reload}
        />
      )}
      {state.kind === 'ready' && <FleetStatusCards summary={state.summary} />}

      <p className="fleet-status__scope">
        หน้านี้แสดงเฉพาะจำนวนรถตามสถานะที่บันทึกไว้ในทะเบียนรถ ยังไม่แสดงกำหนด PM อายุชิ้นส่วน
        ใบรับรองหมดอายุ งานซ่อมที่เปิด สถานะออนไลน์/ออฟไลน์ หรือการแจ้งเตือน
      </p>
    </section>
  )
}

function FleetStatusCards({ summary }: { summary: FleetStatusSummary }) {
  return (
    <>
      <div className="fleet-status__grid">
        <Card className="fleet-status__card fleet-status__card--total">
          <p className="fleet-status__label">รถในทะเบียนทั้งหมด</p>
          <p className="fleet-status__count">{`${summary.vehicle_total} คัน`}</p>
          <Link to="/vehicles">ดูรายการรถทั้งหมด (ไม่กรองสถานะ)</Link>
        </Card>
        {STATUS_ORDER.map((status) => (
          <Card key={status} className="fleet-status__card">
            <StatusBadge
              label={operationalStatusLabel[status] ?? status}
              tone={operationalStatusTone[status]}
            />
            <p className="fleet-status__count">{`${summary.status_counts[status]} คัน`}</p>
          </Card>
        ))}
      </div>
      {summary.vehicle_total === 0 && <EmptyState title="ยังไม่มีรายการรถในทะเบียน" />}
      <p className="fleet-status__hint">
        ต้องการดูรถตามสถานะ ให้เปิดรายการรถแล้วเลือกตัวกรอง “สถานะ”
      </p>
    </>
  )
}
