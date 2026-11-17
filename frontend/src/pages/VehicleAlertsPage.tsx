import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPostWithRequestId } from '../lib/apiClient'
import { CAN_ACT_ON_TEST_ALERT, CAN_RUN_TEST_ALERT_EVALUATION } from '../lib/capabilityNames'
import { useCapabilities } from '../lib/capabilities'
import {
  alertProvenanceLabel,
  alertSeverityLabel,
  alertSeverityTone,
  alertStatusLabel,
  alertStatusTone,
  describeErrorCode,
  formatThaiDateTime,
  missingAlertMessageLabel,
  missingAlertSourceLabel,
  r7AlertTypeLabel,
  unknownAlertFieldLabel,
  unknownAlertTypeLabel,
} from '../lib/labels'
import { newRequestId } from '../lib/registryPending'
import type { Alert, AlertActionResult, AlertEvaluationResult, AlertPage, AlertProvenance } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; alerts: Alert[]; provenance: AlertProvenance | null; total: number | null }

/** One explicit action attempt. The request id is kept so a lost or ambiguous answer
 * can be repeated with the SAME id (the server replays or completes it exactly once);
 * nothing is ever repeated automatically. */
interface Attempt {
  key: string
  requestId: string
  body: unknown
  path: string
}

type Feedback = { tone: 'error' | 'ok'; message: string; retry?: Attempt } | null

const R7_TYPES = ['PM_DUE', 'PART_LIFETIME_DUE', 'CERTIFICATE_EXPIRED']
/** Only server-generated links to known application routes are rendered (P-10). */
const SAFE_LINK = /^\/(vehicle\/[^/?#]+\/(pm\/due|parts|certificates)|part-instances\/[^/?#]+)$/

function renderSource(alert: Alert): string {
  if (alert.source_type && alert.source_id) return `${alert.source_type} / ${alert.source_id}`
  if (alert.source_type) return alert.source_type
  if (alert.source_id) return alert.source_id
  return missingAlertSourceLabel
}

function provenanceFrom(data: unknown): AlertProvenance | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const value = data as AlertProvenance
  return value.types && typeof value.types === 'object' ? value : null
}

function describeActionError(error: ApiError | Error): { message: string; ambiguous: boolean } {
  if (error instanceof ApiError) {
    if (error.status >= 500 && error.code !== 'ALERT_ACTION_AUDIT_UNAVAILABLE') {
      return { message: describeErrorCode(error.code), ambiguous: true }
    }
    return { message: describeErrorCode(error.code), ambiguous: false }
  }
  return { message: 'ไม่ทราบผลการส่งคำขอ (การเชื่อมต่อขัดข้อง) กรุณาส่งคำขอเดิมอีกครั้ง', ambiguous: true }
}

/**
 * Thai alerts (Web/API Phase 6 Batch 6C, extended by R7 Whole-Phase, Owner gate
 * 2026-11-17). Vehicle mode (`/vehicle/:vehicleId/alerts`) and central mode
 * (`/alerts`). Rows are rendered exactly in the backend order; nothing is sorted,
 * counted or derived here (no due formula). Provenance comes from the server only,
 * so an empty list is never presented as a verified zero. The evaluate / acknowledge
 * / mute controls render ONLY for the server-reported TEST grant in the server's TEST
 * context — a display rule; the backend re-checks every action. There is no resolve
 * control: resolution is source-driven only.
 */
export function VehicleAlertsPage() {
  const { vehicleId } = useParams<{ vehicleId: string }>()
  const central = !vehicleId
  const { hasCapability, signals } = useCapabilities()
  const isTest = signals.dataContext === 'TEST'
  const canEvaluate = isTest && hasCapability(CAN_RUN_TEST_ALERT_EVALUATION)
  const canAct = isTest && hasCapability(CAN_ACT_ON_TEST_ALERT)

  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [statusFilter, setStatusFilter] = useState('')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [muteFor, setMuteFor] = useState<string | null>(null)
  const [muteUntil, setMuteUntil] = useState('')
  const [muteReason, setMuteReason] = useState('')
  const inFlight = useRef(false)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    if (central) {
      const query = statusFilter ? `?status=${encodeURIComponent(statusFilter)}&page_size=200` : '?page_size=200'
      const result = await apiGet<AlertPage>(`/alerts${query}`)
      if (!result.ok) {
        const err = result.error
        setState({ kind: 'error', message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
          requestId: err instanceof ApiError ? err.requestId : null })
        return
      }
      setState({ kind: 'ready', alerts: result.data.items ?? [], provenance: null, total: result.data.total_items })
      return
    }
    const id = encodeURIComponent(vehicleId ?? '')
    const result = await apiGet<Alert[]>(`/vehicles/${id}/alerts`)
    if (!result.ok) {
      const err = result.error
      setState({ kind: 'error', message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null })
      return
    }
    const provenance = await apiGet<AlertProvenance>(`/vehicles/${id}/alert-provenance`)
    setState({ kind: 'ready', alerts: result.data, provenance: provenance.ok ? provenanceFrom(provenance.data) : null,
      total: null })
  }, [central, vehicleId, statusFilter])

  useEffect(() => {
    void load()
  }, [load])

  const send = async (attempt: Attempt, onDone: (data: unknown) => void) => {
    if (inFlight.current) return
    inFlight.current = true
    setPending(attempt.key)
    setFeedback(null)
    const result = await apiPostWithRequestId<unknown>(attempt.path, attempt.body, attempt.requestId)
    inFlight.current = false
    setPending(null)
    if (!result.ok) {
      const { message, ambiguous } = describeActionError(result.error)
      setFeedback({ tone: 'error', message, retry: ambiguous ? attempt : undefined })
      return
    }
    onDone(result.data)
    await load()
  }

  const evaluate = () =>
    void send({ key: 'evaluate', requestId: newRequestId(), path: '/alerts/test-evaluations',
      body: central ? {} : { vehicle_id: vehicleId } }, (data) => {
      const totals = (data as AlertEvaluationResult).totals ?? {}
      setFeedback({ tone: 'ok', message: `ประเมินแล้ว: สร้าง ${totals.created ?? 0} คงเดิม ${totals.reused ?? 0} ` +
        `ปิด ${totals.resolved ?? 0} ไม่ทราบสถานะ ${totals.unknown ?? 0} ขัดแย้ง ${totals.conflicts ?? 0}` })
    })

  const acknowledge = (alert: Alert) =>
    void send({ key: `ack:${alert.alert_id}`, requestId: newRequestId(),
      path: `/alerts/${encodeURIComponent(alert.alert_id)}/acknowledge`, body: {} }, (data) => {
      setFeedback({ tone: 'ok', message: `รับทราบแล้ว (${(data as AlertActionResult).outcome})` })
    })

  const mute = (alert: Alert) => {
    const until = muteUntil ? new Date(muteUntil) : null
    if (!until || Number.isNaN(until.getTime()) || !muteReason.trim()) {
      setFeedback({ tone: 'error', message: 'กรุณาระบุเวลาสิ้นสุดการปิดเสียงและเหตุผล' })
      return
    }
    void send({ key: `mute:${alert.alert_id}`, requestId: newRequestId(),
      path: `/alerts/${encodeURIComponent(alert.alert_id)}/mute`,
      body: { muted_until: until.toISOString(), reason_th: muteReason.trim() } }, (data) => {
      setFeedback({ tone: 'ok', message: `ปิดเสียงแล้ว (${(data as AlertActionResult).outcome})` })
      setMuteFor(null)
      setMuteReason('')
      setMuteUntil('')
    })
  }

  const provenanceOf = (t: string) => (state.kind === 'ready' ? state.provenance?.types[t] : undefined) ?? 'NOT_EVALUATED'
  const allNotEvaluated =
    state.kind === 'ready' && state.provenance !== null && R7_TYPES.every((t) => provenanceOf(t) === 'NOT_EVALUATED')
  // Correction C2: an empty list is a verified zero ONLY when every type was evaluated on a
  // complete source with nothing found (EVALUATED_NONE); anything else is said plainly.
  const verifiedZero =
    state.kind === 'ready' && state.provenance !== null && R7_TYPES.every((t) => provenanceOf(t) === 'EVALUATED_NONE')
  const emptyDescription = central
    ? 'ไม่มีรายการในตัวกรองนี้ (รายการว่างไม่ได้ยืนยันว่าไม่มีเหตุแจ้งเตือน หากยังไม่ได้ประเมิน)'
    : allNotEvaluated || (state.kind === 'ready' && state.provenance === null)
      ? 'ยังไม่ได้ประเมินการแจ้งเตือนสำหรับยานพาหนะนี้ — รายการว่างไม่ได้ยืนยันว่าไม่มีเหตุแจ้งเตือน'
      : verifiedZero
        ? 'ยังไม่มีการแจ้งเตือนสำหรับยานพาหนะนี้ (ประเมินแล้วจากแหล่งข้อมูลครบ)'
        : 'ไม่มีการแจ้งเตือนที่เปิดอยู่ แต่ยังยืนยันไม่ได้ว่าไม่มีเหตุแจ้งเตือน (ดูสถานะการประเมินด้านบน)'

  return (
    <section className="page">
      <h1>{central ? 'การแจ้งเตือนทั้งหมด' : 'การแจ้งเตือน'}</h1>
      {!central && <p>รหัสยานพาหนะ: {vehicleId}</p>}
      {central && <p>งานในความรับผิดชอบของฉัน: ยังไม่พร้อมใช้งาน (ยังไม่มีการกำหนดผู้รับการแจ้งเตือนที่อนุมัติ)</p>}

      {central && (
        <label className="form-field">
          <span>สถานะ</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">ทั้งหมด</option>
            {['ACTIVE', 'ACKNOWLEDGED', 'MUTED', 'RESOLVED'].map((s) => (
              <option key={s} value={s}>{alertStatusLabel[s] ?? s}</option>
            ))}
          </select>
        </label>
      )}

      {canEvaluate && (
        <p>
          <button type="button" className="button" disabled={pending !== null} onClick={evaluate}>
            {pending === 'evaluate' ? 'กำลังประเมิน...' : central ? 'ประเมินการแจ้งเตือน (TEST ทุกคัน)' : 'ประเมินการแจ้งเตือน (TEST)'}
          </button>
        </p>
      )}

      {feedback && (
        <div className={feedback.tone === 'error' ? 'form-field__error' : undefined} role={feedback.tone === 'error' ? 'alert' : 'status'}>
          <p>{feedback.message}</p>
          {feedback.retry && (
            <button type="button" className="button button--secondary" disabled={pending !== null}
              onClick={() => feedback.retry && void send(feedback.retry, () => setFeedback({ tone: 'ok',
                message: 'ส่งคำขอเดิมสำเร็จ (บันทึกครั้งเดียว)' }))}>
              ส่งคำขอเดิมอีกครั้ง
            </button>
          )}
        </div>
      )}

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดการแจ้งเตือน..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && state.provenance && (
        <Card>
          <h2>สถานะการประเมิน</h2>
          <ul data-testid="alert-provenance">
            {R7_TYPES.map((t) => (
              <li key={t}>
                {r7AlertTypeLabel[t] ?? t}: {alertProvenanceLabel[state.provenance?.types[t] ?? ''] ?? 'ไม่มีข้อมูล'}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {state.kind === 'ready' && (
        <Card>
          {central && state.total !== null && <p>จำนวนทั้งหมด: {state.total}</p>}
          <ResponsiveTable
            columns={[
              ...(central ? [{ key: 'vehicle_id', header: 'ยานพาหนะ', render: (alert: Alert) => alert.vehicle_id }] : []),
              { key: 'created_at', header: 'วันที่/เวลาที่สร้าง', render: (alert: Alert) => formatThaiDateTime(alert.created_at) },
              { key: 'message_th', header: 'ข้อความแจ้งเตือน', render: (alert: Alert) => alert.message_th ?? missingAlertMessageLabel },
              { key: 'alert_type', header: 'ประเภทการแจ้งเตือน', render: (alert: Alert) => alert.alert_type ?? unknownAlertTypeLabel },
              {
                key: 'severity',
                header: 'ระดับ',
                render: (alert: Alert) =>
                  alert.severity ? (
                    <StatusBadge label={alertSeverityLabel[alert.severity] ?? alert.severity} tone={alertSeverityTone[alert.severity]} />
                  ) : (
                    <StatusBadge label={unknownAlertFieldLabel} tone="neutral" />
                  ),
              },
              {
                key: 'alert_status',
                header: 'สถานะ',
                render: (alert: Alert) => (
                  <>
                    {alert.alert_status ? (
                      <StatusBadge label={alertStatusLabel[alert.alert_status] ?? alert.alert_status} tone={alertStatusTone[alert.alert_status]} />
                    ) : (
                      <StatusBadge label={unknownAlertFieldLabel} tone="neutral" />
                    )}
                    {alert.mute_expired && <span> (หมดเวลาปิดเสียงแล้ว)</span>}
                  </>
                ),
              },
              {
                key: 'source',
                header: 'แหล่งที่มา',
                render: (alert: Alert) =>
                  alert.source_link && SAFE_LINK.test(alert.source_link) ? (
                    <Link to={alert.source_link}>{renderSource(alert)}</Link>
                  ) : (
                    renderSource(alert)
                  ),
              },
              {
                key: 'muted_until',
                header: 'ระงับถึง',
                render: (alert: Alert) => (alert.muted_until ? formatThaiDateTime(alert.muted_until) : '-'),
              },
              ...(canAct
                ? [{
                    key: 'actions',
                    header: 'ดำเนินการ (TEST)',
                    render: (alert: Alert) => {
                      const open = alert.alert_status === 'ACTIVE' || alert.alert_status === 'ACKNOWLEDGED' ||
                        alert.alert_status === 'MUTED'
                      if (!open) return '-'
                      const canAck = alert.alert_status === 'ACTIVE' || alert.mute_expired
                      const canMute = alert.alert_status !== 'MUTED' || alert.mute_expired
                      return (
                        <div>
                          {canAck && (
                            <button type="button" className="button button--secondary" disabled={pending !== null}
                              onClick={() => acknowledge(alert)}>
                              {pending === `ack:${alert.alert_id}` ? 'กำลังบันทึก...' : 'รับทราบ'}
                            </button>
                          )}
                          {canMute && muteFor !== alert.alert_id && (
                            <button type="button" className="button button--secondary" disabled={pending !== null}
                              onClick={() => setMuteFor(alert.alert_id)}>
                              ปิดเสียงชั่วคราว
                            </button>
                          )}
                          {muteFor === alert.alert_id && (
                            <div className="form-grid">
                              <label>
                                ปิดเสียงถึง
                                <input type="datetime-local" value={muteUntil} onChange={(e) => setMuteUntil(e.target.value)} />
                              </label>
                              <label>
                                เหตุผล
                                <input type="text" maxLength={500} value={muteReason} onChange={(e) => setMuteReason(e.target.value)} />
                              </label>
                              <button type="button" className="button" disabled={pending !== null} onClick={() => mute(alert)}>
                                {pending === `mute:${alert.alert_id}` ? 'กำลังบันทึก...' : 'ยืนยันปิดเสียง'}
                              </button>
                              <button type="button" className="button button--secondary" disabled={pending !== null}
                                onClick={() => setMuteFor(null)}>
                                ยกเลิก
                              </button>
                            </div>
                          )}
                        </div>
                      )
                    },
                  }]
                : []),
            ]}
            rows={state.alerts}
            getRowKey={(alert) => alert.alert_id}
            emptyTitle="ไม่มีการแจ้งเตือน"
            emptyDescription={emptyDescription}
          />
        </Card>
      )}
    </section>
  )
}
