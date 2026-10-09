import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiGet } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { describeErrorCode, formatThaiDateTime } from '../lib/labels'
import {
  pendingLifecycleIntent,
  resendLifecycleAction,
  startLifecycleAction,
  type LifecycleEntity,
  type LifecycleIntent,
  type LifecycleOperation,
  type LifecycleResult,
} from '../lib/lifecycle'
import type { LifecycleConsistency, LifecycleEventKind } from '../lib/types'
import { Card } from './Card'
import { ErrorState } from './ErrorState'
import { LifecycleActionDialog, type LifecycleDialogMode } from './LifecycleActionDialog'
import { LoadingState } from './LoadingState'
import { ResponsiveTable } from './ResponsiveTable'

/** A known lifecycle state, or UNKNOWN (blank / not a known value). */
export type LifecycleStateKey = 'ACTIVE' | 'INACTIVE' | 'UNKNOWN'

interface NormalizedEvent {
  id: string
  kind: LifecycleEventKind
  previous: LifecycleStateKey
  next: LifecycleStateKey
  recordedAt: string
  recordedBy: string
  reason: string
}

interface NormalizedHistory {
  current: LifecycleStateKey
  currentRaw: string | null
  consistency: LifecycleConsistency
  events: NormalizedEvent[]
}

export interface LifecycleAdapter {
  entity: LifecycleEntity
  /** "บุคลากร" / "แผนก" */
  entityLabel: string
  capability: string
  normalize: (json: unknown) => NormalizedHistory
  /** The request's expected-current field for a known state. */
  expectedBody: (current: 'ACTIVE' | 'INACTIVE') => Record<string, unknown>
  stateLabel: (state: LifecycleStateKey, raw?: string | null) => string
  dialogNote?: string
}

const EVENT_LABELS: Record<LifecycleEventKind, string> = {
  DEACTIVATE: 'ปิดใช้งาน',
  REACTIVATE: 'เปิดใช้งานอีกครั้ง',
  RECONCILIATION: 'ซิงก์สถานะให้ตรงกับประวัติล่าสุด',
}

const OPERATIONS: Record<LifecycleDialogMode, LifecycleOperation> = {
  deactivate: 'deactivations',
  reactivate: 'reactivations',
  reconcile: 'lifecycle-reconciliations',
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; history: NormalizedHistory }

type Message =
  | { tone: 'success'; text: string }
  | { tone: 'stale'; text: string }
  | { tone: 'error'; text: string; requestId?: string | null }
  | { tone: 'unknown'; text: string; requestId: string }
  | null

async function fetchHistory(adapter: LifecycleAdapter, entityId: string): Promise<LoadState> {
  const result = await apiGet<unknown>(`/${adapter.entity}/${encodeURIComponent(entityId)}/lifecycle-history`)
  if (!result.ok) {
    const err = result.error
    return {
      kind: 'error',
      message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
      requestId: err instanceof ApiError ? err.requestId : null,
    }
  }
  return { kind: 'ready', history: adapter.normalize(result.data) }
}

interface LifecyclePanelProps {
  adapter: LifecycleAdapter
  entityId: string
  displayName: string
  /** Called after any proven outcome so the page reloads its own record. */
  onChanged: () => void
}

/**
 * R2 Batch R2e — lifecycle status, actions and history of one personnel /
 * department record. The backend is authoritative: controls are only hidden
 * for usability; a 403 is still shown as a permission error. A stale write is
 * an explicit conflict with a reload action, never retried. An unknown outcome
 * is neither success nor failure, and can only be resent with the SAME
 * request id. A failed read is an error, never "no history".
 */
export function LifecyclePanel({ adapter, entityId, displayName, onChanged }: LifecyclePanelProps) {
  const { hasCapability, userId } = useCapabilities()
  const canManage = hasCapability(adapter.capability)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [dialog, setDialog] = useState<LifecycleDialogMode | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [dialogError, setDialogError] = useState<{ message: string; requestId?: string | null } | null>(null)
  const [message, setMessage] = useState<Message>(null)
  // Re-read on every render (cheap): the user id arrives asynchronously from /me,
  // and every action may store or remove the intent.
  const [, setIntentVersion] = useState(0)
  const pending: LifecycleIntent | null = pendingLifecycleIntent(userId, adapter.entity, entityId)

  const load = useCallback(() => {
    setState({ kind: 'loading' })
    void fetchHistory(adapter, entityId).then(setState)
  }, [adapter, entityId])

  useEffect(() => {
    let cancelled = false
    void fetchHistory(adapter, entityId).then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [adapter, entityId])

  const apply = (result: LifecycleResult | null) => {
    setIntentVersion((v) => v + 1)
    if (!result) return
    if (result.kind === 'changed' || result.kind === 'replayed' || result.kind === 'no-op') {
      setDialog(null)
      setMessage({ tone: 'success', text: result.kind === 'no-op' ? 'สถานะเป็นค่านี้อยู่แล้ว ไม่มีการเปลี่ยนแปลง' : 'บันทึกเรียบร้อยแล้ว' })
      load()
      onChanged()
    } else if (result.kind === 'stale') {
      setDialog(null)
      setMessage({ tone: 'stale', text: result.message })
    } else if (result.kind === 'mismatch') {
      // Proven: the history holds the event but the record's state does not
      // match it. Never a success; reload so the MISMATCH UI offers the
      // explicit reconciliation (nothing reconciles automatically).
      setDialog(null)
      setMessage({ tone: 'error', text: result.message })
      load()
      onChanged()
    } else if (result.kind === 'refused') {
      setDialogError({ message: result.message, requestId: result.requestId })
    } else if (result.kind === 'recorded-state-pending') {
      setDialog(null)
      setMessage({ tone: 'error', text: result.message, requestId: result.requestId })
      load()
    } else if (result.kind === 'unknown') {
      setDialog(null)
      setMessage({ tone: 'unknown', text: result.message, requestId: result.requestId })
    }
  }

  const confirm = async (reason: string) => {
    if (state.kind !== 'ready' || dialog === null) return
    const current = state.history.current
    if (current === 'UNKNOWN') return
    setSubmitting(true)
    setDialogError(null)
    const result = await startLifecycleAction(userId, adapter.entity, entityId, OPERATIONS[dialog], {
      ...adapter.expectedBody(current),
      reason_th: reason,
    })
    setSubmitting(false)
    apply(result)
  }

  const resend = async () => {
    setSubmitting(true)
    const result = await resendLifecycleAction(userId, adapter.entity, entityId)
    setSubmitting(false)
    apply(result)
  }

  const open = (mode: LifecycleDialogMode) => {
    setMessage(null)
    setDialogError(null)
    setDialog(mode)
  }

  return (
    <Card>
      <h2>สถานะและประวัติสถานะ</h2>
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดประวัติสถานะ..." />}
      {state.kind === 'error' && (
        <ErrorState
          title="โหลดประวัติสถานะไม่สำเร็จ"
          message={state.message}
          requestId={state.requestId}
          onRetry={() => load()}
        />
      )}
      {message && (
        <div className={message.tone === 'success' ? 'form-field__hint' : 'form-field__error'} role="alert">
          <p>{message.text}</p>
          {'requestId' in message && message.requestId && (
            <p className="state-panel__meta">รหัสอ้างอิง: {message.requestId}</p>
          )}
          {message.tone === 'stale' && (
            <button type="button" className="button button--secondary" onClick={() => { setMessage(null); load(); onChanged() }}>
              โหลดข้อมูลล่าสุด
            </button>
          )}
        </div>
      )}
      {pending && (
        <div className="form-field__error" role="status">
          <p>มีคำขอเปลี่ยนสถานะที่ยังไม่ทราบผล (รหัสคำขอ {pending.requestId})</p>
          <button type="button" className="button button--secondary" disabled={submitting} onClick={() => void resend()}>
            ส่งคำขอเดิมอีกครั้ง
          </button>
          <button type="button" className="button button--secondary" onClick={() => { load(); onChanged() }}>
            โหลดข้อมูลล่าสุด
          </button>
        </div>
      )}
      {state.kind === 'ready' && (
        <>
          <p>
            สถานะปัจจุบัน: <strong>{adapter.stateLabel(state.history.current, state.history.currentRaw)}</strong>
          </p>
          {state.history.current === 'UNKNOWN' && (
            <p className="form-field__error" role="alert">
              ไม่ทราบสถานะของข้อมูลนี้ (ข้อมูลต้นทางว่างหรือไม่ใช่ค่าที่ระบบรู้จัก) จึงยังเปลี่ยนสถานะไม่ได้
            </p>
          )}
          {state.history.consistency === 'MISMATCH' && (
            <div className="form-field__error" role="alert">
              <p>สถานะปัจจุบันไม่ตรงกับประวัติสถานะล่าสุด ต้องซิงก์สถานะให้ตรงกับประวัติล่าสุดก่อน</p>
              {canManage && state.history.current !== 'UNKNOWN' && !pending && (
                <button type="button" className="button button--secondary" onClick={() => open('reconcile')}>
                  ซิงก์สถานะให้ตรงกับประวัติล่าสุด
                </button>
              )}
            </div>
          )}
          {canManage && state.history.consistency !== 'MISMATCH' && !pending && (
            <div className="dialog__actions">
              {state.history.current === 'ACTIVE' && (
                <button type="button" className="button button--secondary" onClick={() => open('deactivate')}>
                  ปิดใช้งาน
                </button>
              )}
              {state.history.current === 'INACTIVE' && (
                <button type="button" className="button button--secondary" onClick={() => open('reactivate')}>
                  เปิดใช้งานอีกครั้ง
                </button>
              )}
            </div>
          )}
          <ResponsiveTable
            columns={[
              { key: 'kind', header: 'รายการ', render: (e: NormalizedEvent) => EVENT_LABELS[e.kind] },
              {
                key: 'change',
                header: 'สถานะ',
                render: (e: NormalizedEvent) => `${adapter.stateLabel(e.previous)} → ${adapter.stateLabel(e.next)}`,
              },
              { key: 'recorded_at', header: 'เวลาที่บันทึก', render: (e: NormalizedEvent) => formatThaiDateTime(e.recordedAt) },
              { key: 'recorded_by', header: 'ผู้บันทึก', render: (e: NormalizedEvent) => e.recordedBy },
              { key: 'reason', header: 'เหตุผล', render: (e: NormalizedEvent) => e.reason },
            ]}
            rows={state.history.events}
            getRowKey={(e) => e.id}
            emptyTitle="ยังไม่มีประวัติการเปลี่ยนสถานะ"
            emptyDescription="ข้อมูลนี้ยังไม่เคยถูกปิดหรือเปิดใช้งานผ่านระบบ"
          />
          {dialog && state.history.current !== 'UNKNOWN' && (
            <LifecycleActionDialog
              open
              mode={dialog}
              entityLabel={adapter.entityLabel}
              entityId={entityId}
              displayName={displayName}
              currentStateLabel={adapter.stateLabel(state.history.current)}
              targetStateLabel={adapter.stateLabel(
                dialog === 'deactivate' ? 'INACTIVE'
                  : dialog === 'reactivate' ? 'ACTIVE'
                    : (state.history.events.at(-1)?.next ?? state.history.current),
              )}
              note={adapter.dialogNote}
              submitting={submitting}
              error={dialogError}
              onCancel={() => setDialog(null)}
              onConfirm={(reason) => void confirm(reason)}
            />
          )}
        </>
      )}
    </Card>
  )
}
