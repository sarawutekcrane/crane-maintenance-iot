import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, operationalStatusLabel, operationalStatusTone } from '../lib/labels'
import { resolveCode, useReferenceLists } from '../lib/referenceResolution'
import type { FleetStatusSummary, OperationalStatus } from '../lib/types'
import { vehicleListHref } from '../lib/vehicleListQuery'

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

const MAX_BRANCH_LENGTH = 100

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; title: string; message: string; requestId?: string | null }
  | { kind: 'ready'; summary: FleetStatusSummary; branchId: string }

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

function branchFromUrl(params: URLSearchParams): string {
  const raw = params.get('branch_id') ?? ''
  return raw.length > MAX_BRANCH_LENGTH ? '' : raw
}

/**
 * "ภาพรวมกองรถ" (Web/API Phase 7 Batch 7B2; R8 R8-01 / R8-S1) — counts of
 * vehicle master records by recorded operational status, from ONE page-owned
 * GET /dashboard/fleet-status per load or refresh. Numbers are rendered only on
 * success, exactly as the server sent them; loading, error and permission
 * states never show a number. R8: each of the six cards links to the vehicle
 * list already filtered to that status (and the selected branch), so the card
 * and the list it opens show the same total; the branch filter is kept in the
 * URL. The six KPIs are unchanged (new KPIs are separate work).
 */
export function FleetStatusPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const branchId = branchFromUrl(searchParams)
  const references = useReferenceLists()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  // Request generation: only the latest request's success OR error is
  // applied, so a slow older response can never replace a newer one.
  const generation = useRef(0)

  // `load` only fetches and applies the result; `reload` (called from
  // event handlers) hides the current numbers by showing loading first.
  const load = useCallback(async (branch: string) => {
    const current = ++generation.current
    const query = branch ? `?branch_id=${encodeURIComponent(branch)}` : ''
    const result = await apiGet<FleetStatusSummary>(`/dashboard/fleet-status${query}`)
    if (current !== generation.current) return
    setState(result.ok ? { kind: 'ready', summary: result.data, branchId: branch } : toErrorState(result.error))
  }, [])

  const reload = () => {
    setState({ kind: 'loading' })
    void load(branchId)
  }

  useEffect(() => {
    void load(branchId)
  }, [load, branchId])

  const changeBranch = (next: string) => {
    setState({ kind: 'loading' }) // hide the previous branch's numbers while the new ones load
    setSearchParams(next ? { branch_id: next } : {})
  }

  const branchOptions = references.branches.kind === 'ready' ? [...references.branches.byCode] : []
  const branchListed = references.branches.kind === 'ready' && references.branches.byCode.has(branchId)

  return (
    <section className="page">
      <h1>ภาพรวมกองรถ</h1>
      <p>สรุปจำนวนรถตามสถานะที่บันทึกในทะเบียนรถ แตะการ์ดเพื่อเปิดรายการรถตามสถานะนั้น</p>
      <div className="fleet-status__toolbar">
        <FormField label="สาขาที่รับผิดชอบ" htmlFor="fleet-status-branch">
          <select id="fleet-status-branch" value={branchId} onChange={(event) => changeBranch(event.target.value)}>
            <option value="">ทุกสาขา</option>
            {branchId && !branchListed && (
              <option value={branchId}>{resolveCode(branchId, references.branches).text}</option>
            )}
            {branchOptions.map(([code, entry]) => (
              <option key={code} value={code}>
                {entry.isActive ? entry.name : `${entry.name} (ไม่ใช้งาน)`}
              </option>
            ))}
          </select>
        </FormField>
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
      {state.kind === 'ready' && (
        <FleetStatusCards
          summary={state.summary}
          branchId={state.branchId}
          branchText={state.branchId ? resolveCode(state.branchId, references.branches).text : ''}
        />
      )}

      <p className="fleet-status__scope">
        หน้านี้แสดงเฉพาะจำนวนรถตามสถานะที่บันทึกไว้ในทะเบียนรถ ยังไม่แสดงกำหนด PM อายุชิ้นส่วน
        ใบรับรองหมดอายุ งานซ่อมที่เปิด สถานะออนไลน์/ออฟไลน์ หรือการแจ้งเตือน (ดูได้จากรายงานแต่ละหน้า)
      </p>
    </section>
  )
}

function FleetStatusCards({
  summary,
  branchId,
  branchText,
}: {
  summary: FleetStatusSummary
  branchId: string
  branchText: string
}) {
  return (
    <>
      {branchId && <p className="fleet-status__hint">เฉพาะสาขา: {branchText}</p>}
      <div className="fleet-status__grid">
        <Card className="fleet-status__card fleet-status__card--total">
          <p className="fleet-status__label">{branchId ? 'รถในสาขานี้ทั้งหมด' : 'รถในทะเบียนทั้งหมด'}</p>
          <p className="fleet-status__count">{`${summary.vehicle_total} คัน`}</p>
          <Link to={vehicleListHref({ branchId })}>ดูรายการรถทั้งหมด (ไม่กรองสถานะ)</Link>
        </Card>
        {STATUS_ORDER.map((status) => (
          <Card key={status} className="fleet-status__card">
            <StatusBadge
              label={operationalStatusLabel[status] ?? status}
              tone={operationalStatusTone[status]}
            />
            <p className="fleet-status__count">{`${summary.status_counts[status]} คัน`}</p>
            <Link
              to={vehicleListHref({ status, branchId })}
              aria-label={`ดูรายการรถสถานะ ${operationalStatusLabel[status] ?? status} (${summary.status_counts[status]} คัน)`}
            >
              ดูรายการรถ
            </Link>
          </Card>
        ))}
      </div>
      {summary.vehicle_total === 0 && <EmptyState title="ยังไม่มีรายการรถในทะเบียน" />}
    </>
  )
}
