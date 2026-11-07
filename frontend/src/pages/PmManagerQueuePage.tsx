import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge, type StatusTone } from '../components/StatusBadge'
import { V2ContextBanner } from '../components/V2ContextBanner'
import { apiGet } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_MANAGE_PM } from '../lib/capabilityNames'
import { formatThaiDateTime, pmWorkOrderStatusLabel, pmWorkOrderStatusTone } from '../lib/labels'
import { jobDetailRoute, readFailure, type ReadFailure } from '../lib/technicianV2'
import type {
  PmManagerQueueItem,
  PmManagerQueueResponse,
  PmManagerQueueStatus,
  PmManagerTeamMember,
} from '../lib/types'

export const PM_MANAGER_QUEUE_PATH = '/pm/work-orders/v2-manager-queue'
const PAGE_SIZE = 50
const STATUSES: PmManagerQueueStatus[] = ['OPEN', 'IN_PROGRESS', 'PENDING_REVIEW']

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; failure: ReadFailure }
  | { kind: 'ready'; data: PmManagerQueueResponse }

/** The server's assignment classification, shown as-is and never reinterpreted. */
const ASSIGNMENT_BADGES: Record<string, { label: string; tone: StatusTone }> = {
  NONE: { label: 'ยังไม่ได้มอบหมายทีมช่าง', tone: 'warning' },
  AMBIGUOUS: { label: 'ระบุทีมช่างปัจจุบันไม่ได้', tone: 'danger' },
  DATA_INVALID: { label: 'ข้อมูลการมอบหมายไม่ถูกต้อง', tone: 'danger' },
}

function memberLabel(member: PmManagerTeamMember): string {
  return member.display_name ? `${member.display_name} (${member.technician_id})` : member.technician_id
}

function assetPmRoute(item: PmManagerQueueItem): string | null {
  const id = encodeURIComponent(item.asset_id)
  if (item.asset_type === 'VEHICLE') return `/vehicle/${id}/pm`
  if (item.asset_type === 'EQUIPMENT') return `/equipment/${id}/pm`
  return null
}

function Team({ item }: { item: PmManagerQueueItem }) {
  if (item.assignment_status === 'VALID' && item.primary_technician) {
    return (
      <span data-testid="pm-manager-team" data-status="VALID">
        <span>หัวหน้า: {memberLabel(item.primary_technician)}</span>
        {item.collaborators.length > 0 && (
          <span className="form-field__hint"> ผู้ร่วมงาน: {item.collaborators.map(memberLabel).join(', ')}</span>
        )}
      </span>
    )
  }
  const badge = ASSIGNMENT_BADGES[item.assignment_status] ?? {
    label: `ไม่รู้จักสถานะ: ${item.assignment_status}`,
    tone: 'danger' as const,
  }
  return (
    <span data-testid="pm-manager-team" data-status={item.assignment_status}>
      <StatusBadge label={badge.label} tone={badge.tone} />
      {Object.keys(item.issues).length > 0 && (
        <span className="form-field__hint">
          {' '}
          {Object.entries(item.issues)
            .map(([code, count]) => `${code} × ${count}`)
            .join(', ')}
        </span>
      )}
    </span>
  )
}

function readPage(raw: string | null): number {
  const value = Number(raw)
  return Number.isInteger(value) && value >= 1 ? value : 1
}

function readStatus(raw: string | null): PmManagerQueueStatus | null {
  return STATUSES.includes(raw as PmManagerQueueStatus) ? (raw as PmManagerQueueStatus) : null
}

async function fetchQueue(status: PmManagerQueueStatus | null, page: number): Promise<LoadState> {
  const query = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  if (status) query.set('status', status)
  const result = await apiGet<PmManagerQueueResponse>(`${PM_MANAGER_QUEUE_PATH}?${query.toString()}`)
  return result.ok ? { kind: 'ready', data: result.data } : { kind: 'error', failure: readFailure(result.error) }
}

/**
 * The fleet PM queue. The status filter and page live in the URL, so returning
 * from a Work Order keeps them. Any failed read REPLACES the rows (never stale or
 * partial rows); every change of filter or page starts from the loading state.
 */
function ManagerQueue() {
  const [searchParams, setSearchParams] = useSearchParams()
  const status = readStatus(searchParams.get('status'))
  const page = readPage(searchParams.get('page'))
  const [reload, setReload] = useState(0)
  // The result is tied to the request that produced it: any other filter, page or
  // refresh is "loading" until its own response arrives (never the previous rows).
  const requestKey = `${status ?? 'ALL'}|${page}|${reload}`
  const [loaded, setLoaded] = useState<{ key: string; state: LoadState } | null>(null)
  const state: LoadState = loaded?.key === requestKey ? loaded.state : { kind: 'loading' }

  useEffect(() => {
    let cancelled = false
    void fetchQueue(status, page).then((next) => {
      if (!cancelled) setLoaded({ key: requestKey, state: next })
    })
    return () => {
      cancelled = true
    }
  }, [status, page, requestKey])

  const navigate = useCallback(
    (nextStatus: PmManagerQueueStatus | null, nextPage: number) => {
      const next = new URLSearchParams()
      if (nextStatus) next.set('status', nextStatus)
      if (nextPage > 1) next.set('page', String(nextPage))
      setSearchParams(next)
    },
    [setSearchParams],
  )

  if (state.kind === 'error' && state.failure.status === 403) return <PermissionDeniedState />
  const totalPages = state.kind === 'ready' ? Math.max(1, Math.ceil(state.data.total_items / PAGE_SIZE)) : 1
  // A page beyond the last one the server's total proves (e.g. an old or edited URL)
  // is not an empty queue: say so and offer the last real page, keeping the filter.
  const outOfRange = state.kind === 'ready' && page > totalPages
  return (
    <Card className="pm-manager-queue">
      <section aria-label="คิวใบงาน PM" data-testid="pm-manager-queue">
        <div className="status-card__actions" role="group" aria-label="กรองตามสถานะใบงาน">
          <button
            type="button"
            className={status === null ? 'button' : 'button button--secondary'}
            aria-pressed={status === null}
            onClick={() => navigate(null, 1)}
          >
            ทั้งหมด
          </button>
          {STATUSES.map((value) => (
            <button
              key={value}
              type="button"
              className={status === value ? 'button' : 'button button--secondary'}
              aria-pressed={status === value}
              onClick={() => navigate(value, 1)}
            >
              {pmWorkOrderStatusLabel[value]}
            </button>
          ))}
          <button
            type="button"
            className="button button--secondary"
            onClick={() => setReload((n) => n + 1)}
            disabled={state.kind === 'loading'}
          >
            รีเฟรช
          </button>
        </div>
        {state.kind === 'loading' && <LoadingState message="กำลังโหลดคิวใบงาน PM..." />}
        {state.kind === 'error' && (
          <ErrorState
            title="โหลดคิวใบงาน PM ไม่สำเร็จ"
            message={state.failure.message}
            code={state.failure.code}
            requestId={state.failure.requestId}
            onRetry={() => setReload((n) => n + 1)}
          />
        )}
        {state.kind === 'ready' && (
          <>
            <p className="form-field__hint" data-testid="pm-manager-total">
              ทั้งหมด {state.data.total_items} รายการ
              {state.data.data_context === 'TEST' && ' (ข้อมูลทดสอบ TEST)'}
            </p>
            {outOfRange && (
              <div className="state-panel" role="status" data-testid="pm-manager-out-of-range">
                <p>
                  ไม่มีหน้า {page} — {state.data.total_items > 0 ? `มีทั้งหมด ${totalPages} หน้า` : 'ไม่มีใบงานในเงื่อนไขนี้'}
                </p>
                <button type="button" className="button" onClick={() => navigate(status, totalPages)}>
                  {totalPages > 1 ? `ไปหน้าสุดท้าย (หน้า ${totalPages})` : 'ไปหน้าแรก'}
                </button>
              </div>
            )}
            {!outOfRange && (
              <ResponsiveTable<PmManagerQueueItem>
                rows={state.data.items}
                getRowKey={(item) => item.pm_work_order_id}
                emptyTitle="ไม่มีใบงาน PM ที่ยังดำเนินการอยู่"
                emptyDescription={status ? 'ไม่มีใบงานในสถานะที่เลือก' : 'ใบงาน PM ทั้งหมดปิดหรือยกเลิกแล้ว'}
                columns={[
                  {
                    key: 'work-order',
                    header: 'ใบงาน',
                    render: (item) => <Link to={jobDetailRoute('PM', item.pm_work_order_id)}>{item.pm_work_order_id}</Link>,
                  },
                  {
                    key: 'asset',
                    header: 'รถ / เครื่องมือ',
                    render: (item) => {
                      const route = assetPmRoute(item)
                      return route ? <Link to={route}>{item.asset_id}</Link> : `${item.asset_type} ${item.asset_id}`
                    },
                  },
                  {
                    key: 'status',
                    header: 'สถานะใบงาน',
                    render: (item) => (
                      <StatusBadge
                        label={pmWorkOrderStatusLabel[item.status] ?? item.status}
                        tone={pmWorkOrderStatusTone[item.status] ?? 'neutral'}
                      />
                    ),
                  },
                  { key: 'opened', header: 'เปิดเมื่อ', render: (item) => formatThaiDateTime(item.opened_at) },
                  { key: 'team', header: 'ทีมช่าง', render: (item) => <Team item={item} /> },
                ]}
              />
            )}
            {totalPages > 1 && !outOfRange && (
              <div className="status-card__actions">
                <button
                  type="button"
                  className="button button--secondary"
                  disabled={page <= 1}
                  onClick={() => navigate(status, page - 1)}
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
                  onClick={() => navigate(status, page + 1)}
                >
                  ถัดไป
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </Card>
  )
}

/**
 * "คิวใบงาน PM" — R4 / TASK-010: every PM Work Order still in progress (OPEN,
 * IN_PROGRESS, PENDING_REVIEW) across the fleet, with its current team. Actions
 * (assign, review, return, close, Outstanding) stay on the existing Work Order
 * detail page; this page only lists. Shown to `can_manage_pm`; the backend decides.
 */
export function PmManagerQueuePage() {
  const { loading, hasCapability } = useCapabilities()
  return (
    <section className="page">
      <h1>คิวใบงาน PM</h1>
      <V2ContextBanner />
      {loading && <LoadingState message="กำลังตรวจสอบสิทธิ์..." />}
      {!loading && !hasCapability(CAN_MANAGE_PM) && <PermissionDeniedState />}
      {!loading && hasCapability(CAN_MANAGE_PM) && <ManagerQueue />}
    </section>
  )
}
