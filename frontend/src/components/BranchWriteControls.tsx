/**
 * Phase 7 Batch 7O2c — responsible-branch actions on the vehicle detail page
 * (contract Final Rev2 §6, §10.1-§10.4; Outcome Classification Addendum A.2;
 * review clarification C-c3). Rendered OUTSIDE the read-only branch-history
 * panel; the server re-checks every request.
 *
 * - "ย้ายสาขา" and "ปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติ" need
 *   `can_transfer_vehicle_branch`; the reconciliation button appears only
 *   when the history says PROJECTION_MISMATCH.
 * - "จัดการประวัติสาขา" (`can_correct_branch_history`) is a separate area,
 *   closed at first; only once it is opened are "เพิ่มประวัติย้อนหลัง",
 *   "แก้ไขประวัติ" and "ยกเลิกรายการ" rendered.
 * - Every request is first written to the page-level intent store (same key
 *   as registration intents), then sent once. Outcomes follow the store's
 *   classification; a NOT_DETERMINED success is kept as "recorded, not yet
 *   consistent", never shown as a completed change. Only branch-family
 *   intents are shown and settled here.
 * - A response after this view is gone updates only the store.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  branchOperationLabel,
  branchWriteText,
  describeErrorCode,
  formatRegistryInstant,
  registrationIntentStateLabel,
} from '../lib/labels'
import type { ReferenceLoad } from '../lib/referenceResolution'
import {
  bannerState,
  type BranchOperation,
  type Classification,
  type PendingStore,
  registryPendingStore,
  resendRegistryIntent,
  submitRegistryIntent,
} from '../lib/registryPending'
import type { BranchHistory } from '../lib/types'
import { BranchChangeDialog } from './BranchChangeDialog'

interface Props {
  vehicleId: string
  /** The latest SUCCESSFUL branch-history read of this vehicle (null until one succeeds). */
  history: BranchHistory | null
  branches: ReferenceLoad
  userId: string | null
  canTransfer: boolean
  canCorrect: boolean
  getRouteEpoch: () => number
  /** Re-read the vehicle detail and the branch history (settlement). */
  onRefresh: () => void
  store?: PendingStore
}

type Message = { tone: 'success' | 'info'; text: string } | { tone: 'error'; text: string; code?: string }

function useStoreVersion(store: PendingStore): number {
  const subscribe = useCallback((listener: () => void) => store.subscribe(listener), [store])
  const snapshot = useCallback(() => store.snapshotVersion, [store])
  return useSyncExternalStore(subscribe, snapshot)
}

export function BranchWriteControls({
  vehicleId,
  history,
  branches,
  userId,
  canTransfer,
  canCorrect,
  getRouteEpoch,
  onRefresh,
  store = registryPendingStore,
}: Props) {
  useStoreVersion(store)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    if (userId) store.settleLatest(userId, vehicleId)
  }, [store, userId, vehicleId])

  const [dialog, setDialog] = useState<{ operation: BranchOperation; related: string } | null>(null)
  const [manageOpen, setManageOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<Message | null>(null)

  const intents = userId ? store.list(userId, vehicleId, 'branch') : []
  const notices = userId ? store.notices(userId, vehicleId, 'branch') : []
  const banner = bannerState(intents)
  const uncertainSubmitting = intents.some((i) => i.state === 'SUBMITTING' && !store.isInflight(i.request_id))

  const handle = useCallback(
    (classification: Classification) => {
      if (!alive.current) return // bookkeeping already happened in the store
      setDialog(null)
      if (classification.action === 'REMOVE') {
        if (classification.notice === 'CONFIRMED_APPLIED') {
          setMessage({ tone: 'success', text: branchWriteText.applied })
          onRefresh()
        } else if (classification.notice === 'CONFIRMED_NO_OP') {
          setMessage({ tone: 'info', text: branchWriteText.noop })
        } else {
          const code = classification.errorCode
          setMessage({
            tone: 'error',
            code,
            text:
              code === 'BRANCH_HISTORY_WRITE_FAILED'
                ? branchWriteText.w1Rejected
                : code === 'RELATED_REQUEST_NOT_FOUND'
                  ? branchWriteText.relatedNotFound
                  : describeErrorCode(code),
          })
        }
        return
      }
      // KEEP: the banner (from the store) carries the uncertainty.
      if (classification.body?.projection_write === 'NOT_DETERMINED') {
        setMessage({ tone: 'info', text: branchWriteText.notDetermined })
      } else if (classification.refused && classification.errorCode) {
        setMessage({
          tone: 'error',
          code: classification.errorCode,
          text: `คำขอที่ส่งซ้ำถูกปฏิเสธ: ${describeErrorCode(classification.errorCode)}`,
        })
      } else {
        setMessage(null)
      }
      onRefresh() // a history read may settle it
    },
    [onRefresh],
  )

  const send = async (operation: BranchOperation, body: Record<string, unknown>, eventId: string | null) => {
    if (!userId) return
    setSaving(true)
    setMessage(null)
    const result = await submitRegistryIntent(store, {
      userId,
      vehicleId,
      operation,
      body,
      eventId,
      routeEpoch: getRouteEpoch(),
    })
    if (!alive.current) return
    setSaving(false)
    handle(result.classification)
  }

  const resend = async (requestId: string) => {
    if (!userId) return
    setSaving(true)
    setMessage(null)
    const result = await resendRegistryIntent(store, userId, vehicleId, requestId)
    if (!alive.current) return
    setSaving(false)
    if (result) handle(result.classification)
  }

  const open = (operation: BranchOperation, related = '') => {
    setMessage(null)
    setDialog({ operation, related })
  }

  if (!canTransfer && !canCorrect) return null

  const masterInSchema = history === null || history.master.state !== 'NOT_IN_SCHEMA'
  const ready = history !== null && userId !== null && masterInSchema
  const hasEvents = history !== null && history.events.some((e) => e.in_force)
  const showReconcile =
    canTransfer && ready && (history.consistency === 'PROJECTION_MISMATCH' || (message?.tone === 'error' && message.code === 'BRANCH_PROJECTION_MISMATCH'))

  const bannerText = (() => {
    if (banner === 'CONFLICT') return branchWriteText.conflict
    if (banner === 'RECORDED_PROJECTION_PENDING') return branchWriteText.pending
    if (banner === 'UNKNOWN' || banner === 'UNCONFIRMED') return branchWriteText.unknown
    if (banner === 'SUBMITTING') return uncertainSubmitting ? branchWriteText.unknown : branchWriteText.submitting
    return null
  })()

  return (
    <section aria-label="การเปลี่ยนแปลงสาขาที่รับผิดชอบ" data-testid="branch-write-controls">
      {bannerText && (
        <div className="form-field__error" role="status" data-testid="branch-intent-banner">
          <p>
            <strong>{bannerText}</strong>
          </p>
          {store.isMemoryOnly && <p>{branchWriteText.memoryOnly}</p>}
          <ul>
            {intents.map((intent) => {
              const inflight = store.isInflight(intent.request_id)
              const state = intent.state === 'SUBMITTING' && !inflight ? 'UNKNOWN' : intent.state
              return (
                <li key={intent.request_id} data-testid="branch-intent">
                  {registrationIntentStateLabel[state] ?? state}: {branchOperationLabel[intent.operation] ?? intent.operation} ·
                  ส่งเมื่อ {formatRegistryInstant(intent.submitted_at)} · รหัสคำขอ {intent.request_id}
                  {state === 'UNCONFIRMED' && <p>{branchWriteText.unconfirmed}</p>}
                  <div className="status-card__actions">
                    {(state === 'UNKNOWN' || state === 'UNCONFIRMED') && !inflight && (
                      <button
                        type="button"
                        className="button button--secondary"
                        disabled={saving}
                        onClick={() => void resend(intent.request_id)}
                      >
                        ส่งคำขอเดิมอีกครั้ง
                      </button>
                    )}
                    {!inflight && (
                      <button
                        type="button"
                        className="button button--secondary"
                        disabled={saving}
                        onClick={() => userId && store.acknowledge(userId, vehicleId, intent.request_id)}
                      >
                        รับทราบ
                      </button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
          <p className="form-field__hint">{branchWriteText.acknowledgeHint}</p>
          <button type="button" className="button button--secondary" onClick={onRefresh} disabled={saving}>
            ตรวจสอบผลจากประวัติสาขาอีกครั้ง
          </button>
        </div>
      )}

      {notices.map((notice) => (
        <p key={notice.request_id} role="status" data-testid="branch-settlement-notice">
          {notice.intent === 'RECORDED_LATER_CHANGED' ? branchWriteText.settledLater : branchWriteText.settled} (
          {notice.request_id})
        </p>
      ))}

      {message && (
        <div role={message.tone === 'error' ? 'alert' : 'status'} data-testid="branch-write-message">
          <p className={message.tone === 'error' ? 'form-field__error' : undefined}>{message.text}</p>
          {message.tone === 'error' && message.code === 'BRANCH_HISTORY_STALE' && (
            <button type="button" className="button button--secondary" onClick={onRefresh}>
              โหลดประวัติสาขาใหม่
            </button>
          )}
        </div>
      )}

      {!masterInSchema ? (
        <p className="form-field__hint">{branchWriteText.masterNotInSchema}</p>
      ) : userId === null ? (
        <p className="form-field__hint">{branchWriteText.noUser}</p>
      ) : history === null ? (
        <p className="form-field__hint">{branchWriteText.historyUnavailable}</p>
      ) : (
        <>
          {canTransfer && (
            <div className="status-card__actions">
              <button
                type="button"
                className="button button--secondary button--full-width"
                disabled={saving}
                onClick={() => open('transfer')}
              >
                ย้ายสาขา
              </button>
            </div>
          )}
          {showReconcile && (
            <div className="status-card__actions">
              <button
                type="button"
                className="button button--secondary button--full-width"
                disabled={saving}
                onClick={() => open('reconcile', intents.find((i) => i.state === 'RECORDED_PROJECTION_PENDING')?.request_id ?? '')}
              >
                ปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติ
              </button>
            </div>
          )}
          {canCorrect && (
            <div className="branch-history-manage">
              <button
                type="button"
                className="button button--secondary button--full-width"
                aria-expanded={manageOpen}
                aria-controls="branch-history-actions"
                onClick={() => setManageOpen((v) => !v)}
              >
                จัดการประวัติสาขา
              </button>
              {manageOpen && (
                <div id="branch-history-actions" data-testid="branch-history-actions" className="status-card__actions">
                  <button type="button" className="button button--secondary" disabled={saving} onClick={() => open('insertion')}>
                    เพิ่มประวัติย้อนหลัง
                  </button>
                  <button
                    type="button"
                    className="button button--secondary"
                    disabled={saving || !hasEvents}
                    onClick={() => open('correction')}
                  >
                    แก้ไขประวัติ
                  </button>
                  <button
                    type="button"
                    className="button button--secondary"
                    disabled={saving || !hasEvents}
                    onClick={() => open('cancellation')}
                  >
                    ยกเลิกรายการ
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {history !== null && dialog && (
        <BranchChangeDialog
          key={dialog.operation}
          operation={dialog.operation}
          history={history}
          branches={branches}
          initialRelatedRequestId={dialog.related}
          submitting={saving}
          onCancel={() => setDialog(null)}
          onSubmit={(body, eventId) => void send(dialog.operation, body, eventId)}
        />
      )}
    </section>
  )
}
