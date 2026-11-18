import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { isLinkableVehicleId } from '../lib/certificateReportLinks'
import { describeErrorCode, partLifetimeItemStatusLabel, partLifetimeItemStatusTone } from '../lib/labels'
import type { PartLifetimeDueReport, PartLifetimeItemStatus } from '../lib/types'

/**
 * R8 (R8-09) — "อายุอะไหล่ถึงกำหนด (ทั้งกองรถ)". Read-only; each row is the R6
 * per-vehicle lifetime result (no recalculation here). UNKNOWN is never shown
 * as not due, "no applicable rule" is its own status, and vehicles outside the
 * data scope are counted on the page instead of being hidden. Paging is over
 * vehicles (a bounded number of reads per page).
 */

const STATUSES: PartLifetimeItemStatus[] = ['DUE', 'UNKNOWN', 'NOT_DUE', 'NO_APPLICABLE_RULE']
const PAGE_SIZE = 20

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; report: PartLifetimeDueReport }

function toErrorState(err: ApiError | Error): LoadState {
  if (err instanceof ApiError && err.status === 403) return { kind: 'denied' }
  return {
    kind: 'error',
    message: describeErrorCode(err instanceof ApiError ? err.code : undefined),
    requestId: err instanceof ApiError ? err.requestId : null,
  }
}

export function PartLifetimeDueReportPage() {
  const [params, setParams] = useSearchParams()
  const rawStatus = params.get('status') ?? ''
  const status = (STATUSES as string[]).includes(rawStatus) ? (rawStatus as PartLifetimeItemStatus) : ''
  const rawPage = params.get('page') ?? ''
  const page = /^[1-9]\d{0,4}$/.test(rawPage) ? Number(rawPage) : 1
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const generation = useRef(0)

  const load = useCallback(async (s: string, p: number) => {
    const current = ++generation.current
    const query = new URLSearchParams({ page: String(p), page_size: String(PAGE_SIZE) })
    if (s) query.set('status', s)
    const result = await apiGet<PartLifetimeDueReport>(`/reports/part-lifetime-due?${query.toString()}`)
    if (current !== generation.current) return
    setState(result.ok ? { kind: 'ready', report: result.data } : toErrorState(result.error))
  }, [])

  useEffect(() => {
    void load(status, page)
  }, [load, status, page])

  const go = (next: { status?: string; page?: number }) => {
    setState({ kind: 'loading' })
    const merged = { status, page, ...next }
    const search: Record<string, string> = {}
    if (merged.status) search.status = merged.status
    if (merged.page > 1) search.page = String(merged.page)
    setParams(search)
  }

  return (
    <section className="page">
      <h1>อายุอะไหล่ถึงกำหนด (ทั้งกองรถ)</h1>
      <p>
        ผลการประเมินอายุอะไหล่ที่ติดตั้งอยู่บนรถ จากบริการอายุอะไหล่เดียวกับหน้าประจำรถ ดูได้โดยผู้มีสิทธิ์ดูข้อมูล
        (รายงานนี้แยกจากการแจ้งเตือนและจากกำหนด PM)
      </p>
      <Card>
        <FormField label="สถานะ" htmlFor="part-due-status">
          <select id="part-due-status" value={status} onChange={(e) => go({ status: e.target.value, page: 1 })}>
            <option value="">ทุกสถานะ</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {partLifetimeItemStatusLabel[s]}
              </option>
            ))}
          </select>
        </FormField>
      </Card>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดรายงาน..." />}
      {state.kind === 'denied' && <PermissionDeniedState />}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={() => void load(status, page)} />
      )}
      {state.kind === 'ready' && (
        <>
          <p aria-live="polite">
            หน้า {state.report.page} · รถในหน้านี้ที่ประเมิน {state.report.vehicles_evaluated} คัน
            {state.report.vehicles_out_of_scope > 0 &&
              ` · ไม่ได้ประเมิน ${state.report.vehicles_out_of_scope} คัน (อยู่นอกชุดข้อมูลของเซิร์ฟเวอร์ ไม่ได้แปลว่าไม่ถึงกำหนด)`}{' '}
            · รถทั้งหมด {state.report.total_vehicles} คัน
          </p>
          <ResponsiveTable
            columns={[
              {
                key: 'vehicle',
                header: 'รถ',
                render: (i) =>
                  isLinkableVehicleId(i.vehicle_id) ? (
                    <Link to={`/vehicle/${i.vehicle_id}/parts`}>{i.machine_no ?? i.vehicle_id}</Link>
                  ) : (
                    i.vehicle_id
                  ),
              },
              { key: 'target', header: 'รายการ', render: (i) => `${i.part_id ?? '-'} · ${i.target_id}` },
              { key: 'position', header: 'ตำแหน่ง', render: (i) => i.position_code ?? '-' },
              {
                key: 'status',
                header: 'สถานะ',
                render: (i) => (
                  <StatusBadge label={partLifetimeItemStatusLabel[i.status] ?? i.status} tone={partLifetimeItemStatusTone[i.status]} />
                ),
              },
            ]}
            rows={state.report.items}
            getRowKey={(i) => `${i.vehicle_id}:${i.target_type}:${i.target_id}`}
            emptyTitle="ไม่มีรายการในหน้านี้"
            emptyDescription="ไม่พบรายการตามเงื่อนไขในรถหน้านี้ (ไม่ได้ยืนยันว่าทั้งกองรถไม่มีรายการ ลองหน้าถัดไป)"
          />
          <nav className="vehicle-list__pager" aria-label="เปลี่ยนหน้ารายงาน">
            <button type="button" className="button button--secondary" disabled={page <= 1} onClick={() => go({ page: page - 1 })}>
              ก่อนหน้า
            </button>
            <span className="vehicle-list__page-label">หน้า {page}</span>
            <button type="button" className="button button--secondary"
              disabled={page * PAGE_SIZE >= state.report.total_vehicles} onClick={() => go({ page: page + 1 })}>
              ถัดไป
            </button>
          </nav>
        </>
      )}
    </section>
  )
}
