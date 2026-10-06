/**
 * Phase 7 Batch 7O2b — the registration editor on the vehicle detail page
 * (contract Final Rev2 §4.4, §4.6, §10.1-§10.4; Outcome Classification
 * Addendum A.2-A.3). Rendered only for `can_edit_vehicle_registration`
 * holders; the server re-checks every request.
 *
 * - Inputs are prefilled with the stored text EXACTLY and sent as typed (no
 *   trimming). Clearing is an explicit action that sends null/null.
 * - Every request is first written to the page-level intent store
 *   (`registryPending`), then sent once with its own X-Request-Id. There is no
 *   automatic resend; "ส่งคำขอเดิมอีกครั้ง" resends the stored body with the
 *   same id.
 * - Proven refusals (allowlisted codes) are shown inline and keep the typed
 *   values. Uncertain outcomes are a persistent banner from the store, never
 *   "not saved"; they leave only by history settlement or acknowledgement.
 * - A response that arrives after this view is gone still updates the store
 *   (bookkeeping), but never this or another view's state.
 */
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { Link } from 'react-router-dom'
import { isLinkableVehicleId } from '../lib/certificateReportLinks'
import {
  describeErrorCode,
  formatRegistryInstant,
  registrationAcceptedExceptionLabel,
  registrationIntentStateLabel,
  registrationWriteText,
} from '../lib/labels'
import { type ReferenceLoad, resolveCode } from '../lib/referenceResolution'
import {
  bannerState,
  type Classification,
  type PendingIntent,
  type PendingStore,
  registryPendingStore,
  resendRegistryIntent,
  submitRegistryIntent,
} from '../lib/registryPending'
import type { RegistrationHistory, VehicleRegistry } from '../lib/types'
import { FormField } from './FormField'
import { type ReconcileMode, RegistrationReconcileDialog } from './RegistrationReconcileDialog'

interface Props {
  vehicleId: string
  registry: VehicleRegistry | undefined
  provinces: ReferenceLoad
  /** The latest SUCCESSFUL registration-history read of this vehicle (null until one succeeds). */
  history: RegistrationHistory | null
  userId: string | null
  /** The page's route epoch, recorded on each intent (read when sending). */
  getRouteEpoch: () => number
  /** Re-read the vehicle detail and the registration history (settlement). */
  onRefresh: () => void
  store?: PendingStore
}

type Message =
  | { tone: 'success' | 'info'; text: string }
  | { tone: 'error'; text: string; code?: string; conflictIds?: string[] }

const W1_FAILED = 'REGISTRATION_HISTORY_WRITE_FAILED'

function useStoreVersion(store: PendingStore): number {
  const subscribe = useCallback((listener: () => void) => store.subscribe(listener), [store])
  const snapshot = useCallback(() => store.snapshotVersion, [store])
  return useSyncExternalStore(subscribe, snapshot)
}

function bodySummary(intent: PendingIntent): string {
  const body = intent.body
  if (intent.operation === 'registration_reconcile') {
    return body.mode === 'ACCEPT_MASTER' ? 'ยอมรับค่าในข้อมูลทะเบียนรถ' : 'ใช้ค่าตามประวัติล่าสุด'
  }
  const no = typeof body.registration_no === 'string' ? body.registration_no : null
  const province = typeof body.registration_province_code === 'string' ? body.registration_province_code : null
  if (no === null) return 'ล้างทะเบียน'
  return province === null ? `${no} (ยังไม่ระบุจังหวัด)` : `${no} · ${province}`
}

export function VehicleRegistrationEditor({
  vehicleId,
  registry,
  provinces,
  history,
  userId,
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
  // A history read that finished before the user id was known is judged now.
  useEffect(() => {
    if (userId) store.settleLatest(userId, vehicleId)
  }, [store, userId, vehicleId])

  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [province, setProvince] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<Message | null>(null)
  const [reconcileOpen, setReconcileOpen] = useState(false)
  const [reconcileRelated, setReconcileRelated] = useState('')

  const numberField = registry?.registration_no
  const provinceField = registry?.registration_province
  const inSchema =
    numberField !== undefined &&
    provinceField !== undefined &&
    numberField.state !== 'NOT_IN_SCHEMA' &&
    provinceField.state !== 'NOT_IN_SCHEMA'
  // The expected pair is exactly what this page shows (null = not recorded).
  const currentNo = numberField?.state === 'RECORDED' ? numberField.value : null
  const currentProvince = provinceField?.state === 'RECORDED' ? provinceField.value : null

  const intents = userId ? store.list(userId, vehicleId, 'registration') : []
  const settlementNotices = userId ? store.notices(userId, vehicleId) : []
  const banner = bannerState(intents)
  const uncertainSubmitting = intents.some((i) => i.state === 'SUBMITTING' && !store.isInflight(i.request_id))

  const handle = useCallback(
    (classification: Classification, { closeOnSuccess }: { closeOnSuccess: boolean }) => {
      if (!alive.current) return // bookkeeping already happened in the store
      if (classification.action === 'REMOVE') {
        if (classification.notice === 'CONFIRMED_APPLIED') {
          const warnings = classification.body?.warnings
          const accepted = Array.isArray(warnings) ? warnings.filter((w): w is string => typeof w === 'string') : []
          setMessage({
            tone: 'success',
            text: accepted.length
              ? `${registrationWriteText.applied} (${accepted.map((w) => registrationAcceptedExceptionLabel[w] ?? w).join(', ')})`
              : registrationWriteText.applied,
          })
          if (closeOnSuccess) setEditing(false)
          setReconcileOpen(false)
          onRefresh()
          return
        }
        if (classification.notice === 'CONFIRMED_NO_OP') {
          const warnings = classification.body?.warnings
          const duplicate = Array.isArray(warnings) && warnings.includes('EXISTING_DUPLICATE_PAIR')
          setMessage({
            tone: 'info',
            text: duplicate ? `${registrationWriteText.noop} ${registrationWriteText.duplicateWarning}` : registrationWriteText.noop,
          })
          if (closeOnSuccess) setEditing(false)
          setReconcileOpen(false)
          return
        }
        // CONFIRMED_ZERO_WRITE: a proven refusal; the editor keeps the typed values.
        setReconcileOpen(false)
        const code = classification.errorCode
        const ids = classification.errorDetails?.conflict_vehicle_ids
        setMessage({
          tone: 'error',
          code,
          text:
            code === W1_FAILED
              ? 'ระบบปลายทางปฏิเสธการบันทึกคำขอนี้ จึงไม่มีการเปลี่ยนแปลงจากคำขอนี้ กรุณาลองใหม่อีกครั้ง'
              : describeErrorCode(code),
          conflictIds: Array.isArray(ids) ? ids.filter((v): v is string => typeof v === 'string') : undefined,
        })
        return
      }
      // KEEP: the banner (from the store) carries the uncertainty.
      if (classification.refused && classification.errorCode) {
        setMessage({
          tone: 'error',
          code: classification.errorCode,
          text: `คำขอที่ส่งซ้ำถูกปฏิเสธ: ${describeErrorCode(classification.errorCode)}`,
        })
      } else {
        setMessage(null)
      }
      setReconcileOpen(false)
      onRefresh() // a history read may settle it
    },
    [onRefresh],
  )

  const send = useCallback(
    async (body: Record<string, unknown>, operation: 'registration' | 'registration_reconcile') => {
      if (!userId) return
      setSaving(true)
      setMessage(null)
      const result = await submitRegistryIntent(store, { userId, vehicleId, operation, body, routeEpoch: getRouteEpoch() })
      if (!alive.current) return
      setSaving(false)
      handle(result.classification, { closeOnSuccess: operation === 'registration' })
    },
    [userId, store, vehicleId, getRouteEpoch, handle],
  )

  const startEditing = () => {
    setText(currentNo ?? '')
    setProvince(currentProvince ?? '')
    setMessage(null)
    setEditing(true)
  }

  const save = () => {
    if (text === '') {
      setMessage({ tone: 'error', text: 'กรุณากรอกทะเบียน หรือใช้ปุ่ม "ล้างทะเบียน"' })
      return
    }
    void send(
      {
        registration_no: text,
        registration_province_code: province === '' ? null : province,
        expected_registration_no: currentNo,
        expected_registration_province_code: currentProvince,
      },
      'registration',
    )
  }

  const clear = () => {
    void send(
      {
        registration_no: null,
        registration_province_code: null,
        expected_registration_no: currentNo,
        expected_registration_province_code: currentProvince,
      },
      'registration',
    )
  }

  const reconcile = (mode: ReconcileMode, reason: string, related: string) => {
    if (!history) return
    void send(
      {
        mode,
        expected_registration_no: currentNo,
        expected_registration_province_code: currentProvince,
        expected_history_revision: history.history_revision,
        reason_th: reason,
        ...(related !== '' ? { related_request_id: related } : {}),
      },
      'registration_reconcile',
    )
  }

  const resend = async (requestId: string) => {
    if (!userId) return
    setSaving(true)
    setMessage(null)
    const result = await resendRegistryIntent(store, userId, vehicleId, requestId)
    if (!alive.current) return
    setSaving(false)
    if (result) handle(result.classification, { closeOnSuccess: false })
  }

  const openReconcile = (related: string) => {
    setReconcileRelated(related)
    setReconcileOpen(true)
  }

  const provinceOptions = useMemo(() => {
    const options: { value: string; label: string; disabled: boolean }[] = [
      { value: '', label: 'ไม่ระบุจังหวัด (รอระบุ)', disabled: false },
    ]
    if (provinces.kind === 'ready') {
      for (const [code, entry] of provinces.byCode) {
        const inactive = !entry.isActive
        options.push({
          value: code,
          label: inactive ? `${entry.name} (${code}) (ไม่ใช้งาน)` : `${entry.name} (${code})`,
          // An inactive province can be kept, never newly assigned.
          disabled: inactive && code !== currentProvince,
        })
      }
      if (currentProvince !== null && !provinces.byCode.has(currentProvince)) {
        options.push({ value: currentProvince, label: resolveCode(currentProvince, provinces).text, disabled: false })
      }
    } else if (currentProvince !== null) {
      // The list is unavailable: only the recorded raw code can stay selected;
      // no new code can be chosen and none is guessed.
      options.push({ value: currentProvince, label: resolveCode(currentProvince, provinces).text, disabled: false })
    }
    return options
  }, [provinces, currentProvince])

  const pendingIntent = intents.find((i) => i.state === 'RECORDED_PROJECTION_PENDING')
  const showReconcile =
    history !== null && (history.consistency === 'MISMATCH' || pendingIntent !== undefined || (message?.tone === 'error' && message.code === 'REGISTRATION_PROJECTION_MISMATCH'))

  const bannerText = (() => {
    if (banner === 'CONFLICT') return registrationWriteText.conflict
    if (banner === 'RECORDED_PROJECTION_PENDING') return registrationWriteText.pending
    if (banner === 'UNKNOWN' || banner === 'UNCONFIRMED') return registrationWriteText.unknown
    if (banner === 'SUBMITTING') return uncertainSubmitting ? registrationWriteText.unknown : registrationWriteText.submitting
    return null
  })()

  return (
    <div className="registration-editor" data-testid="registration-editor">
      {bannerText && (
        <div className="form-field__error" role="status" data-testid="registration-intent-banner">
          <p>
            <strong>{bannerText}</strong>
          </p>
          {store.isMemoryOnly && <p>{registrationWriteText.memoryOnly}</p>}
          <ul>
            {intents.map((intent) => {
              const inflight = store.isInflight(intent.request_id)
              const state = intent.state === 'SUBMITTING' && !inflight ? 'UNKNOWN' : intent.state
              return (
                <li key={intent.request_id} data-testid="registration-intent">
                  {registrationIntentStateLabel[state] ?? state}: {bodySummary(intent)} · ส่งเมื่อ{' '}
                  {formatRegistryInstant(intent.submitted_at)} · รหัสคำขอ {intent.request_id}
                  {state === 'UNCONFIRMED' && <p>{registrationWriteText.unconfirmed}</p>}
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
                    {state === 'RECORDED_PROJECTION_PENDING' && history !== null && (
                      <button
                        type="button"
                        className="button button--secondary"
                        disabled={saving}
                        onClick={() => openReconcile(intent.request_id)}
                      >
                        ปรับข้อมูลให้ตรงกัน
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
          <p className="form-field__hint">{registrationWriteText.acknowledgeHint}</p>
          <button type="button" className="button button--secondary" onClick={onRefresh} disabled={saving}>
            ตรวจสอบผลจากประวัติอีกครั้ง
          </button>
        </div>
      )}

      {settlementNotices.map((notice) => (
        <p key={notice.request_id} role="status" data-testid="registration-settlement-notice">
          {notice.intent === 'RECORDED_LATER_CHANGED' ? registrationWriteText.settledLater : registrationWriteText.settled} (
          {notice.request_id})
        </p>
      ))}

      {message && (
        <div role={message.tone === 'error' ? 'alert' : 'status'} data-testid="registration-editor-message">
          <p className={message.tone === 'error' ? 'form-field__error' : undefined}>{message.text}</p>
          {message.tone === 'error' && message.conflictIds && message.conflictIds.length > 0 && (
            <p>
              รถคันที่ใช้อยู่:{' '}
              {message.conflictIds.map((id, index) => (
                <span key={`${id}:${index}`}>
                  {index > 0 && ', '}
                  {isLinkableVehicleId(id) ? <Link to={`/vehicle/${id}`}>{id}</Link> : id}
                </span>
              ))}
            </p>
          )}
          {message.tone === 'error' &&
            (message.code === 'VEHICLE_REGISTRY_STALE' || message.code === 'REGISTRATION_HISTORY_STALE') && (
              <button type="button" className="button button--secondary" onClick={onRefresh}>
                โหลดใหม่
              </button>
            )}
        </div>
      )}

      {!inSchema ? (
        <p className="form-field__hint">{registrationWriteText.notInSchema}</p>
      ) : userId === null ? (
        <p className="form-field__hint">{registrationWriteText.noUser}</p>
      ) : !editing ? (
        <div className="status-card__actions">
          <button type="button" className="button button--secondary button--full-width" onClick={startEditing}>
            เปลี่ยนทะเบียน
          </button>
        </div>
      ) : (
        <div className="form-grid">
          <FormField
            label="ทะเบียนรถ"
            htmlFor="registration-no-input"
            hint="บันทึกตามที่กรอกทุกตัวอักษร (ไม่ตัดช่องว่าง)"
          >
            <input
              id="registration-no-input"
              type="text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              disabled={saving}
            />
          </FormField>
          <FormField
            label="จังหวัดที่จดทะเบียน"
            htmlFor="registration-province-select"
            hint={provinces.kind === 'ready' ? undefined : registrationWriteText.provincesUnavailable}
          >
            <select
              id="registration-province-select"
              value={province}
              onChange={(event) => setProvince(event.target.value)}
              disabled={saving}
            >
              {provinceOptions.map((option) => (
                <option key={option.value} value={option.value} disabled={option.disabled}>
                  {option.label}
                </option>
              ))}
            </select>
          </FormField>
          <div className="status-card__actions">
            <button type="button" className="button button--secondary" onClick={() => setEditing(false)} disabled={saving}>
              ยกเลิก
            </button>
            <button type="button" className="button button--secondary" onClick={clear} disabled={saving}>
              ล้างทะเบียน
            </button>
            <button type="button" className="button button--primary" onClick={save} disabled={saving}>
              {saving ? 'กำลังบันทึก...' : 'บันทึกทะเบียน'}
            </button>
          </div>
        </div>
      )}

      {inSchema && userId !== null && showReconcile && (
        <div className="status-card__actions">
          <button
            type="button"
            className="button button--secondary button--full-width"
            disabled={saving}
            onClick={() => openReconcile(pendingIntent?.request_id ?? '')}
          >
            ปรับข้อมูลทะเบียนให้ตรงกับประวัติ
          </button>
        </div>
      )}

      {history !== null && reconcileOpen && (
        <RegistrationReconcileDialog
          open
          history={history}
          masterNo={currentNo}
          masterProvince={currentProvince}
          provinces={provinces}
          initialRelatedRequestId={reconcileRelated}
          submitting={saving}
          onCancel={() => setReconcileOpen(false)}
          onSubmit={reconcile}
        />
      )}
    </div>
  )
}
