import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { V2ContextBanner } from '../components/V2ContextBanner'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode, formatThaiDateTime } from '../lib/labels'
import { jobDetailRoute, readFailure, type MyWorkItem, type MyWorkResponse, type ReadFailure } from '../lib/technicianV2'
import type { Page, RepairRequest } from '../lib/types'

type LoadState = { kind: 'loading' } | { kind: 'error'; failure: ReadFailure } | { kind: 'ready'; data: MyWorkResponse }

type RequestsState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: RepairRequest[] }

const REQUEST_STATUS_LABEL: Record<string, string> = {
  PENDING: 'รอตรวจรับ',
  CONVERTED: 'เปิดใบงานซ่อมแล้ว',
}

/** The explicit message of every unresolved account → personnel → technician mapping (C1 §25). */
const UNRESOLVED_MESSAGES: Record<string, string> = {
  UNAUTHENTICATED: 'ยังไม่ได้เข้าสู่ระบบ จึงแสดงงานของฉันไม่ได้',
  ACCOUNT_MISSING: 'ไม่พบบัญชีผู้ใช้ของคุณในข้อมูลหลัก',
  ACCOUNT_AMBIGUOUS: 'บัญชีผู้ใช้ของคุณซ้ำกันในข้อมูลหลัก',
  ACCOUNT_SCOPE_UNPROVEN: 'ยืนยันขอบเขตข้อมูลของบัญชีผู้ใช้ของคุณไม่ได้',
  PERSONNEL_UNLINKED: 'บัญชีผู้ใช้ของคุณยังไม่ได้เชื่อมกับข้อมูลบุคลากร',
  PERSONNEL_AMBIGUOUS: 'บัญชีผู้ใช้ของคุณเชื่อมกับบุคลากรมากกว่าหนึ่งรายการ',
  PERSONNEL_SCOPE_MISMATCH: 'ข้อมูลบุคลากรของคุณอยู่คนละขอบเขตข้อมูลกับบัญชีผู้ใช้',
  TECHNICIAN_UNLINKED: 'ข้อมูลบุคลากรของคุณยังไม่ได้เชื่อมกับรหัสช่าง',
  TECHNICIAN_MISSING: 'ไม่พบรหัสช่างที่เชื่อมกับข้อมูลบุคลากรของคุณ',
  TECHNICIAN_AMBIGUOUS: 'รหัสช่างที่เชื่อมกับข้อมูลบุคลากรของคุณซ้ำกันในข้อมูลหลัก',
  TECHNICIAN_SCOPE_UNPROVEN: 'ยืนยันขอบเขตข้อมูลของรหัสช่างของคุณไม่ได้',
}

function WorkTable({ rows, role }: { rows: MyWorkItem[]; role: 'PRIMARY' | 'COLLABORATOR' }) {
  return (
    <ResponsiveTable<MyWorkItem>
      rows={rows}
      getRowKey={(item) => `${item.work_type}:${item.job_id}`}
      emptyTitle={role === 'PRIMARY' ? 'ไม่มีงานที่คุณเป็นช่างหลัก' : 'ไม่มีงานที่คุณเป็นช่างร่วม'}
      emptyDescription="ยังไม่มีรายการในขณะนี้"
      columns={[
        {
          key: 'job',
          header: 'งาน',
          render: (item) => (
            <Link to={jobDetailRoute(item.work_type, item.job_id)}>
              {item.work_type === 'REPAIR' ? 'ซ่อม' : 'PM'} {item.job_id}
            </Link>
          ),
        },
        { key: 'asset', header: 'สินทรัพย์', render: (item) => `${item.asset_type} ${item.asset_id}` },
        { key: 'status', header: 'สถานะ', render: (item) => item.status },
        { key: 'opened', header: 'เปิดเมื่อ', render: (item) => formatThaiDateTime(item.opened_at) },
        { key: 'assigned', header: 'มอบหมายเมื่อ (เวลาที่บันทึก)', render: (item) => formatThaiDateTime(item.assigned_at) },
      ]}
    />
  )
}

async function fetchMyWork(): Promise<LoadState> {
  const result = await apiGet<MyWorkResponse>('/my-work')
  return result.ok ? { kind: 'ready', data: result.data } : { kind: 'error', failure: readFailure(result.error) }
}

/** Web UAT Defect Fix UAT-F2 (retained by the B5 cutover — not an assignment
 * feature): every Repair Request the current actor reported, any status. */
async function fetchMyRequests(): Promise<RequestsState> {
  const result = await apiGet<Page<RepairRequest>>('/repair-requests/mine?page_size=50')
  if (result.ok) return { kind: 'ready', items: result.data.items }
  const err = result.error
  return {
    kind: 'error',
    message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
    requestId: err instanceof ApiError ? err.requestId : null,
  }
}

/**
 * "งานของฉัน" — R2 Batch R2f-h4 B5 navigation cutover: Technician V2 My Work
 * (`GET /my-work` only; the legacy `/repairs/my-work` and
 * `/pm/work-orders/my-work` reads are no longer used, and there is no legacy
 * fallback). The caller's technician is resolved by the server from the
 * signed-in account; an unresolved mapping is an explicit message, never an
 * empty list. The caller's own Repair Requests (UAT-F2) stay on this page.
 */
export function MyWorkPage() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [myRequestsState, setMyRequestsState] = useState<RequestsState>({ kind: 'loading' })

  const load = useCallback(() => {
    setState({ kind: 'loading' })
    void fetchMyWork().then(setState)
  }, [])

  const loadMyRequests = useCallback(() => {
    setMyRequestsState({ kind: 'loading' })
    void fetchMyRequests().then(setMyRequestsState)
  }, [])

  useEffect(() => {
    let cancelled = false
    void fetchMyWork().then((next) => {
      if (!cancelled) setState(next)
    })
    void fetchMyRequests().then((next) => {
      if (!cancelled) setMyRequestsState(next)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="page">
      <h1>งานของฉัน</h1>
      <V2ContextBanner />
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดงานของฉัน..." />}
      {state.kind === 'error' && (
        <ErrorState
          message={state.failure.message}
          code={state.failure.code}
          requestId={state.failure.requestId}
          onRetry={() => load()}
        />
      )}
      {state.kind === 'ready' && state.data.resolution !== 'RESOLVED' && (
        <Card className="state-panel state-panel--denied">
          <div role="alert" data-testid="v2-my-work-unresolved">
            <p className="state-panel__title">ยังระบุรหัสช่างของคุณไม่ได้</p>
            <p>{UNRESOLVED_MESSAGES[state.data.resolution] ?? 'ระบบระบุรหัสช่างของคุณไม่ได้'}</p>
            <p className="state-panel__meta">สถานะการเชื่อมโยง: {state.data.resolution}</p>
            <p>กรุณาติดต่อผู้ดูแลระบบเพื่อตรวจสอบการเชื่อมบัญชีผู้ใช้ บุคลากร และรหัสช่าง</p>
          </div>
        </Card>
      )}
      {state.kind === 'ready' && state.data.resolution === 'RESOLVED' && (
        <>
          <Card>
            <div className="status-card__row">
              <span>รหัสช่างของฉัน</span>
              <strong data-testid="v2-my-technician-id">{state.data.technician_id ?? '-'}</strong>
            </div>
          </Card>
          {(state.data.items ?? []).length === 0 ? (
            <EmptyState title="ยังไม่มีงานที่มอบหมายให้คุณ" description="เมื่อมีการมอบหมายงานให้คุณ งานจะแสดงที่นี่" />
          ) : (
            <>
              <section aria-label="งานที่เป็นช่างหลัก" data-testid="v2-my-work-primary">
                <h2>งานที่ฉันเป็นช่างหลัก (PRIMARY)</h2>
                <WorkTable rows={(state.data.items ?? []).filter((i) => i.assignment_role === 'PRIMARY')} role="PRIMARY" />
              </section>
              <section aria-label="งานที่เป็นช่างร่วม" data-testid="v2-my-work-collaborator">
                <h2>งานที่ฉันเป็นช่างร่วม (COLLABORATOR)</h2>
                <WorkTable
                  rows={(state.data.items ?? []).filter((i) => i.assignment_role === 'COLLABORATOR')}
                  role="COLLABORATOR"
                />
              </section>
            </>
          )}
        </>
      )}

      {/* Web UAT Defect Fix UAT-F2 */}
      <h2>คำขอแจ้งซ่อมของฉัน</h2>
      <p>รายการที่ฉันแจ้งปัญหา/แจ้งซ่อมไว้ ไม่ว่าจะรอตรวจรับหรือเปิดใบงานซ่อมแล้ว</p>

      {myRequestsState.kind === 'loading' && <LoadingState message="กำลังโหลดคำขอแจ้งซ่อมของฉัน..." />}
      {myRequestsState.kind === 'error' && (
        <ErrorState
          message={myRequestsState.message}
          requestId={myRequestsState.requestId}
          onRetry={loadMyRequests}
        />
      )}

      {myRequestsState.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'reported_at',
              header: 'วันที่แจ้ง',
              render: (row) => (
                <Link to={`/repair-requests/${row.repair_request_id}`}>
                  {formatThaiDateTime(row.reported_at)}
                </Link>
              ),
            },
            {
              key: 'vehicle',
              header: 'ยานพาหนะ',
              render: (row) => row.vehicle_id,
            },
            {
              key: 'symptom',
              header: 'อาการ/ปัญหาที่พบ',
              render: (row) => row.symptom_th ?? '-',
            },
            {
              key: 'status',
              header: 'สถานะ',
              render: (row) => (
                <StatusBadge
                  label={REQUEST_STATUS_LABEL[row.request_status] ?? row.request_status}
                  tone={row.request_status === 'CONVERTED' ? 'success' : 'warning'}
                />
              ),
            },
          ]}
          rows={myRequestsState.items}
          getRowKey={(row) => row.repair_request_id}
          emptyTitle="ยังไม่มีคำขอแจ้งซ่อม"
          emptyDescription="เมื่อแจ้งปัญหา/แจ้งซ่อม รายการจะแสดงที่นี่"
        />
      )}
    </section>
  )
}
