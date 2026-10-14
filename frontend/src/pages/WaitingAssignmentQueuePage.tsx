import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge, type StatusTone } from '../components/StatusBadge'
import { V2ContextBanner } from '../components/V2ContextBanner'
import { apiGet } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_MANAGE_PM, CAN_MANAGE_REPAIR } from '../lib/capabilityNames'
import { formatThaiDateTime } from '../lib/labels'
import {
  jobDetailRoute,
  readFailure,
  waitingQueuePath,
  type ReadFailure,
  type WaitingItem,
  type WaitingQueueResponse,
  type WorkKind,
} from '../lib/technicianV2'

const PAGE_SIZE = 50

type LoadState = { kind: 'loading' } | { kind: 'error'; failure: ReadFailure } | { kind: 'ready'; data: WaitingQueueResponse }

/** The server's classification, shown distinctly and never reinterpreted. */
const STATUS_BADGES: Record<string, { label: string; tone: StatusTone }> = {
  NONE: { label: 'NONE — ยังไม่ได้มอบหมายช่าง', tone: 'warning' },
  AMBIGUOUS: { label: 'AMBIGUOUS — ระบุทีมช่างปัจจุบันไม่ได้', tone: 'danger' },
  DATA_INVALID: { label: 'DATA_INVALID — ข้อมูลการมอบหมายไม่ถูกต้อง', tone: 'danger' },
}

function WaitingStatusBadge({ item }: { item: WaitingItem }) {
  const badge = STATUS_BADGES[item.assignment_status] ?? { label: `ไม่รู้จักสถานะ: ${item.assignment_status}`, tone: 'danger' as const }
  return (
    <span data-testid="v2-waiting-status" data-status={item.assignment_status}>
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

async function fetchQueue(kind: WorkKind, page: number): Promise<LoadState> {
  const result = await apiGet<WaitingQueueResponse>(`${waitingQueuePath(kind)}?page=${page}&page_size=${PAGE_SIZE}`)
  return result.ok ? { kind: 'ready', data: result.data } : { kind: 'error', failure: readFailure(result.error) }
}

/**
 * One U1 queue. Any failed read REPLACES the rows with an error (never a stale
 * or partial queue); every refresh starts from the loading state.
 */
function WaitingQueue({ kind }: { kind: WorkKind }) {
  const [page, setPage] = useState(1)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(() => {
    setState({ kind: 'loading' })
    void fetchQueue(kind, page).then(setState)
  }, [kind, page])

  useEffect(() => {
    let cancelled = false
    void fetchQueue(kind, page).then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [kind, page])

  const goTo = (next: number) => {
    setState({ kind: 'loading' }) // never show the previous page's rows as this page
    setPage(next)
  }

  const title = kind === 'REPAIR' ? 'งานซ่อมที่รอมอบหมายช่าง' : 'งาน PM ที่รอมอบหมายช่าง'
  const totalPages = state.kind === 'ready' ? Math.max(1, Math.ceil(state.data.total_items / PAGE_SIZE)) : 1
  return (
    <Card className="v2-waiting-queue">
      <section aria-label={title} data-testid={`v2-waiting-${kind}`}>
        <h2>{title}</h2>
        <button type="button" className="button button--secondary" onClick={() => load()} disabled={state.kind === 'loading'}>
          รีเฟรช
        </button>
        {state.kind === 'loading' && <LoadingState message="กำลังโหลดคิวงาน..." />}
        {state.kind === 'error' && (
          <ErrorState
            title="โหลดคิวงานไม่สำเร็จ"
            message={state.failure.message}
            code={state.failure.code}
            requestId={state.failure.requestId}
            onRetry={() => load()}
          />
        )}
        {state.kind === 'ready' && (
          <>
            <p className="form-field__hint">ทั้งหมด {state.data.total_items} รายการ</p>
            <ResponsiveTable<WaitingItem>
              rows={state.data.items}
              getRowKey={(item) => item.job_id}
              emptyTitle="ไม่มีงานที่รอมอบหมายช่าง"
              emptyDescription="งานที่เปิดอยู่ทั้งหมดมีทีมช่างแล้ว"
              columns={[
                {
                  key: 'job',
                  header: 'งาน',
                  render: (item) => <Link to={jobDetailRoute(kind, item.job_id)}>{item.job_id}</Link>,
                },
                { key: 'asset', header: 'สินทรัพย์', render: (item) => `${item.asset_type} ${item.asset_id}` },
                { key: 'opened', header: 'เปิดเมื่อ', render: (item) => formatThaiDateTime(item.opened_at) },
                { key: 'status', header: 'สถานะการมอบหมาย', render: (item) => <WaitingStatusBadge item={item} /> },
              ]}
            />
            {totalPages > 1 && (
              <div className="status-card__actions">
                <button type="button" className="button button--secondary" disabled={page <= 1} onClick={() => goTo(page - 1)}>
                  ก่อนหน้า
                </button>
                <span>
                  หน้า {page} / {totalPages}
                </span>
                <button
                  type="button"
                  className="button button--secondary"
                  disabled={page >= totalPages}
                  onClick={() => goTo(page + 1)}
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
 * "รอมอบหมายช่าง" — R2 Batch R2f-h4 B5 navigation cutover: the U1 Technician V2
 * waiting-assignment queues (A1-§24 routes only; the legacy
 * `/repairs/waiting-assignment` read is no longer used). Repair and PM are
 * separate queues, each shown only to a holder of that kind's management
 * capability (the backend still decides).
 */
export function WaitingAssignmentQueuePage() {
  const { loading, hasCapability } = useCapabilities()
  const repair = hasCapability(CAN_MANAGE_REPAIR)
  const pm = hasCapability(CAN_MANAGE_PM)
  return (
    <section className="page">
      <h1>รอมอบหมายช่าง</h1>
      <V2ContextBanner />
      {loading && <LoadingState message="กำลังตรวจสอบสิทธิ์..." />}
      {!loading && !repair && !pm && <PermissionDeniedState />}
      {!loading && repair && <WaitingQueue kind="REPAIR" />}
      {!loading && pm && <WaitingQueue kind="PM" />}
    </section>
  )
}
