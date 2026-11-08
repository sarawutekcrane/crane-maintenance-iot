import { type FormEvent, type ReactNode, useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { VehiclePmDueSummary } from '../components/PmDueSetTable'
import { apiGet } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_VIEW } from '../lib/capabilityNames'
import { operationalStatusLabel } from '../lib/labels'
import { readFailure, type ReadFailure } from '../lib/technicianV2'
import type { OperationalStatus, Page, VehiclePmDue } from '../lib/types'

export const PM_DUE_PATH = '/pm/due/vehicles'
const PAGE_SIZE = 20
const STATUS_FILTERS: OperationalStatus[] = ['WORKING', 'READY', 'MAINTENANCE', 'OUT_OF_SERVICE', 'LONG_TERM_PARKING']

type LoadState<T> = { kind: 'loading' } | { kind: 'error'; failure: ReadFailure } | { kind: 'ready'; data: T }

interface Filters {
  q: string
  status: string
  modelId: string
}

function readPage(raw: string | null): number {
  const value = Number(raw)
  return Number.isInteger(value) && value >= 1 ? value : 1
}

function readFilters(params: URLSearchParams): Filters {
  const status = params.get('status') ?? ''
  return {
    q: params.get('q') ?? '',
    status: STATUS_FILTERS.includes(status as OperationalStatus) ? status : '',
    modelId: params.get('model_id') ?? '',
  }
}

/** Shared by the fleet and vehicle views: the result is tied to its own request. */
function useDueRead<T>(path: string, reload: number): LoadState<T> {
  const key = `${path}|${reload}`
  const [loaded, setLoaded] = useState<{ key: string; state: LoadState<T> } | null>(null)
  useEffect(() => {
    let cancelled = false
    void apiGet<T>(path).then((result) => {
      if (cancelled) return
      setLoaded({
        key,
        state: result.ok ? { kind: 'ready', data: result.data } : { kind: 'error', failure: readFailure(result.error) },
      })
    })
    return () => {
      cancelled = true
    }
  }, [path, key])
  return loaded?.key === key ? loaded.state : { kind: 'loading' }
}

function FleetDue() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = readFilters(searchParams)
  const page = readPage(searchParams.get('page'))
  const [draft, setDraft] = useState<Filters>(filters)
  // The form follows the ACTIVE URL: when its filters change (Back / Forward, a link, a
  // submit) the draft is replaced by them; while they stay the same (refresh, paging)
  // the user's unsubmitted edits are kept. Adjusted during render, not in an effect.
  const urlFilterKey = JSON.stringify([filters.q, filters.status, filters.modelId])
  const [draftUrlKey, setDraftUrlKey] = useState(urlFilterKey)
  if (draftUrlKey !== urlFilterKey) {
    setDraftUrlKey(urlFilterKey)
    setDraft(filters)
  }
  const [reload, setReload] = useState(0)
  const query = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  if (filters.q) query.set('q', filters.q)
  if (filters.status) query.set('status', filters.status)
  if (filters.modelId) query.set('model_id', filters.modelId)
  const state = useDueRead<Page<VehiclePmDue>>(`${PM_DUE_PATH}?${query.toString()}`, reload)

  const navigate = useCallback(
    (next: Filters, nextPage: number) => {
      const params = new URLSearchParams()
      if (next.q) params.set('q', next.q)
      if (next.status) params.set('status', next.status)
      if (next.modelId) params.set('model_id', next.modelId)
      if (nextPage > 1) params.set('page', String(nextPage))
      setSearchParams(params)
    },
    [setSearchParams],
  )
  const apply = (event: FormEvent) => {
    event.preventDefault()
    navigate({ ...draft, q: draft.q.trim(), modelId: draft.modelId.trim() }, 1)
  }

  if (state.kind === 'error' && state.failure.status === 403) return <PermissionDeniedState />
  const totalPages = state.kind === 'ready' ? Math.max(1, Math.ceil(state.data.total_items / PAGE_SIZE)) : 1
  const outOfRange = state.kind === 'ready' && page > totalPages
  return (
    <section aria-label="กำหนด PM ทั้งกองรถ" data-testid="fleet-pm-due">
      <Card>
        <form className="form-grid form-grid--two-column" onSubmit={apply} aria-label="กรองรายการรถ">
          <label className="form-field">
            <span>ค้นหา (เลขรถ / รหัส / รุ่น)</span>
            <input value={draft.q} onChange={(e) => setDraft({ ...draft, q: e.target.value })} />
          </label>
          <label className="form-field">
            <span>สถานะรถ</span>
            <select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
              <option value="">ทั้งหมด</option>
              {STATUS_FILTERS.map((s) => (
                <option key={s} value={s}>
                  {operationalStatusLabel[s] ?? s}
                </option>
              ))}
            </select>
          </label>
          <label className="form-field">
            <span>รหัสรุ่นรถ</span>
            <input value={draft.modelId} onChange={(e) => setDraft({ ...draft, modelId: e.target.value })} />
          </label>
          <div className="status-card__actions">
            <button type="submit" className="button">
              ค้นหา
            </button>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setReload((n) => n + 1)}
              disabled={state.kind === 'loading'}
            >
              รีเฟรช
            </button>
          </div>
        </form>
      </Card>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดกำหนด PM..." />}
      {state.kind === 'error' && (
        <ErrorState
          title="โหลดกำหนด PM ไม่สำเร็จ"
          message={state.failure.message}
          code={state.failure.code}
          requestId={state.failure.requestId}
          onRetry={() => setReload((n) => n + 1)}
        />
      )}
      {state.kind === 'ready' && (
        <>
          {/* The vehicle count only: no fleet Due totals are derived from one page. */}
          <p className="form-field__hint" data-testid="fleet-pm-due-total">
            รถทั้งหมด {state.data.total_items} คันตามเงื่อนไข
          </p>
          {outOfRange && (
            <div className="state-panel" role="status" data-testid="fleet-pm-due-out-of-range">
              <p>
                ไม่มีหน้า {page} — {state.data.total_items > 0 ? `มีทั้งหมด ${totalPages} หน้า` : 'ไม่มีรถตามเงื่อนไขนี้'}
              </p>
              <button type="button" className="button" onClick={() => navigate(filters, totalPages)}>
                {totalPages > 1 ? `ไปหน้าสุดท้าย (หน้า ${totalPages})` : 'ไปหน้าแรก'}
              </button>
            </div>
          )}
          {!outOfRange && state.data.items.length === 0 && (
            <div className="state-panel" role="status" data-testid="fleet-pm-due-empty">
              <p>ไม่มีรถตามเงื่อนไขที่เลือก</p>
            </div>
          )}
          {!outOfRange &&
            state.data.items.map((vehicle) => (
              <Card key={vehicle.vehicle_id}>
                <h2>
                  <Link to={`/vehicle/${encodeURIComponent(vehicle.vehicle_id)}/pm/due`}>{vehicle.machine_no}</Link>{' '}
                  <span className="form-field__hint">
                    {vehicle.vehicle_id} · {vehicle.model_id}
                  </span>
                </h2>
                <VehiclePmDueSummary vehicle={vehicle} />
              </Card>
            ))}
          {totalPages > 1 && !outOfRange && (
            <div className="status-card__actions">
              <button
                type="button"
                className="button button--secondary"
                disabled={page <= 1}
                onClick={() => navigate(filters, page - 1)}
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
                onClick={() => navigate(filters, page + 1)}
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

function VehicleDue({ vehicleId }: { vehicleId: string }) {
  const [reload, setReload] = useState(0)
  const state = useDueRead<VehiclePmDue>(`${PM_DUE_PATH}/${encodeURIComponent(vehicleId)}`, reload)
  if (state.kind === 'loading') return <LoadingState message="กำลังโหลดกำหนด PM..." />
  if (state.kind === 'error') {
    if (state.failure.status === 403) return <PermissionDeniedState />
    return (
      <ErrorState
        title="โหลดกำหนด PM ไม่สำเร็จ"
        message={state.failure.message}
        code={state.failure.code}
        requestId={state.failure.requestId}
        onRetry={() => setReload((n) => n + 1)}
      />
    )
  }
  return (
    <Card>
      <h2>
        {state.data.machine_no} <span className="form-field__hint">{state.data.vehicle_id}</span>
      </h2>
      <VehiclePmDueSummary vehicle={state.data} />
    </Card>
  )
}

function CanView({ children }: { children: ReactNode }) {
  const { loading, hasCapability } = useCapabilities()
  if (loading) return <LoadingState message="กำลังตรวจสอบสิทธิ์..." />
  if (!hasCapability(CAN_VIEW)) return <PermissionDeniedState />
  return <>{children}</>
}

/**
 * "กำหนด PM ทั้งกองรถ" — R4 / TASK-010 Fleet PM Due B1: every vehicle (the same
 * vehicle filters and paging as the vehicle list) with its PM Due from the backend's
 * canonical read model. Shown to `can_view`; the backend decides.
 */
export function FleetPmDuePage() {
  return (
    <section className="page">
      <h1>กำหนด PM ทั้งกองรถ</h1>
      <CanView>
        <FleetDue />
      </CanView>
    </section>
  )
}

/** The same read model for one vehicle (linked from the vehicle's PM page). */
export function VehiclePmDuePage() {
  const { vehicleId = '' } = useParams<{ vehicleId: string }>()
  return (
    <section className="page">
      <h1>กำหนด PM ของรถ</h1>
      <Card>
        <Link to={`/vehicle/${encodeURIComponent(vehicleId)}/pm`} className="button button--secondary">
          กลับไปหน้า PM ของรถ
        </Link>
      </Card>
      <CanView>
        <VehicleDue vehicleId={vehicleId} />
      </CanView>
    </section>
  )
}
