import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import {
  CAN_TEST_STORE_APPROVE,
  CAN_TEST_STORE_ISSUE,
  CAN_TEST_STORE_RECEIVE_RETURN,
} from '../lib/capabilityNames'
import { describeErrorCode, storeBlockerLabel, storeEventTypeLabel } from '../lib/labels'
import { useRetainedRequestId } from '../lib/masterRecords'
import {
  createStoreRequest,
  getStoreReconciliation,
  storeLineStep,
  type StoreLineStep,
  type StoreRequestLineInput,
} from '../lib/storeWorkflow'
import type { StoreLineBalance, StorePartBalance, StoreReconciliation } from '../lib/types'

/**
 * R8 PRE-UAT (Owner Decision 1) — the repair material workflow on the repair page:
 * request → approve/deny → issue → technician confirms actual use → declares unused return →
 * Store accepts the physical return → per-work-order reconciliation. No stock ledger.
 * Issued ≠ installed; a return counts only once accepted. Buttons follow the TEST grants
 * (UX only); the backend enforces grants, V2 membership and every quantity guard.
 */

type Action = { line: StoreLineBalance; step: StoreLineStep } | null

const STEP_LABEL: Record<StoreLineStep, string> = {
  approvals: 'อนุมัติ', denials: 'ปฏิเสธ', issues: 'จ่ายอะไหล่', 'use-confirmations': 'ยืนยันใช้จริง',
  'return-declarations': 'แจ้งคืนส่วนที่ไม่ได้ใช้', 'return-acceptances': 'รับคืนเข้าคลัง',
}

/** Independent review 2026-11-18: use / return name the ACTUAL issued identity (part + instance); the panel
 * offers only identities with quantity left for that step and never preselects among several. */
const identityKey = (p: StorePartBalance) => `${p.part_id}|${p.part_instance_id}`
const remaining = (p: StorePartBalance, step: StoreLineStep): number => {
  const [issued, used, declared, accepted] = [p.issued, p.used, p.return_declared, p.return_accepted].map(Number)
  return step === 'return-acceptances' ? Math.min(declared - accepted, issued - used - accepted) : issued - used - declared
}
const identityOptions = (line: StoreLineBalance, step: StoreLineStep) =>
  (line.issued_parts ?? []).filter((p) => remaining(p, step) > 0)
const identityLabel = (p: StorePartBalance) =>
  `${p.part_id}${p.part_instance_id ? ` · ชิ้น ${p.part_instance_id}` : ''}`
const IDENTITY_STEPS: StoreLineStep[] = ['use-confirmations', 'return-declarations', 'return-acceptances']

function errorText(error: Error): string {
  return error instanceof ApiError ? describeErrorCode(error.code)
    : 'ไม่ได้รับคำตอบจากเซิร์ฟเวอร์ ส่งอีกครั้งได้อย่างปลอดภัย (ระบบจะไม่บันทึกซ้ำ)'
}

export function StoreRequestPanel({ repairId, repairOpen, onChanged }: { repairId: string; repairOpen: boolean;
  /** ISS-01: tells the repair page that Store events changed (read-only views refresh). */
  onChanged?: () => void }) {
  const { hasCapability } = useCapabilities()
  const [loaded, setLoaded] = useState<{ data: StoreReconciliation | null; error: string | null; hidden?: boolean }>(
    { data: null, error: null })
  const data = loaded.data
  const loadError = loaded.error
  const [lines, setLines] = useState<StoreRequestLineInput[]>([{ part_description: '', quantity: '1', unit: 'ชิ้น' }])
  const [action, setAction] = useState<Action>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const requestIntent = useRetainedRequestId()
  const actionIntent = useRetainedRequestId()
  // Independent review: after an uncertain (network) failure the same line + step keeps its request id and
  // values, even if the form is cancelled and reopened, so a resend is the same intent (never a 2nd ISSUED).
  const uncertain = useRef<Record<string, { id: string; form: Record<string, string> }>>({})
  const actionId = useRef<string | null>(null)

  const generation = useRef(0)
  const load = useCallback(async () => {
    const current = ++generation.current
    const result = await getStoreReconciliation(repairId)
    if (current !== generation.current) return
    // Independent review: a repository without the feature (501, e.g. Google Sheets) or a reader without
    // permission (403) gets no panel at all instead of an error on every repair page.
    const unavailable = !result.ok && result.error instanceof ApiError && [403, 501].includes(result.error.status)
    // A 2xx whose body is not a reconciliation (old backend, proxy page) is an error, never rendered as data.
    const malformed = result.ok && !(Array.isArray(result.data?.lines) && Array.isArray(result.data?.events))
    setLoaded((prev) => (malformed ? { data: prev.data, error: 'ข้อมูลที่ได้รับไม่ใช่รูปแบบที่คาดไว้ (MALFORMED_RESPONSE)' }
      : result.ok ? { data: result.data, error: null }
      : unavailable ? { data: null, error: null, hidden: true } : { data: prev.data, error: errorText(result.error) }))
  }, [repairId])

  useEffect(() => {
    void load()
  }, [load])

  const editLine = (index: number, patch: Partial<StoreRequestLineInput>) => {
    requestIntent.reset()
    setLines((ls) => ls.map((l, i) => (i === index ? { ...l, ...patch } : l)))
  }

  const submitRequest = async () => {
    const id = requestIntent.current()
    if (!id) return setMessage('สร้างรหัสคำขอที่ปลอดภัยไม่ได้ จึงยังไม่ส่ง')
    const clean = lines.map((l) => ({ ...(l.part_id ? { part_id: l.part_id } : {}), part_description: l.part_description,
      quantity: l.quantity.trim(), unit: l.unit }))
    setBusy(true)
    const result = await createStoreRequest(repairId, clean, id)
    setBusy(false)
    if (result.ok) {
      requestIntent.reset()
      setLines([{ part_description: '', quantity: '1', unit: 'ชิ้น' }])
      setMessage(result.data.replayed ? 'คำขอนี้บันทึกไว้แล้ว (ไม่สร้างซ้ำ)' : 'ส่งคำขอเบิกแล้ว')
      void load()
      onChanged?.()
    } else setMessage(errorText(result.error))
  }

  const openAction = (line: StoreLineBalance, step: StoreLineStep) => {
    const pending = uncertain.current[`${line.requisition_line_id}:${step}`]
    actionIntent.reset()
    actionId.current = pending?.id ?? null
    setAction({ line, step })
    const options = identityOptions(line, step)
    setForm(pending ? pending.form : IDENTITY_STEPS.includes(step)
      ? { identity: options.length === 1 ? identityKey(options[0]) : '' }
      : step === 'issues' ? { part_id: line.part_id } : {})
    if (pending) setMessage('คำขอก่อนหน้านี้ยังไม่ทราบผล — กดบันทึกเพื่อส่งคำขอเดิมซ้ำอย่างปลอดภัย')
  }

  const setField = (name: string, value: string) => {
    if (action) delete uncertain.current[`${action.line.requisition_line_id}:${action.step}`]
    actionIntent.reset()
    actionId.current = null
    setForm((f) => ({ ...f, [name]: value }))
  }

  const submitAction = async () => {
    if (!action) return
    const id = actionId.current ?? actionIntent.current()
    if (!id) return setMessage('สร้างรหัสคำขอที่ปลอดภัยไม่ได้ จึงยังไม่ส่ง')
    actionId.current = id
    const key = `${action.line.requisition_line_id}:${action.step}`
    const body: Record<string, unknown> = {}
    if (action.step === 'denials') body.reason = form.reason ?? ''
    else {
      body.quantity = form.quantity ?? ''
      if (action.step === 'issues') {
        body.part_id = form.part_id ?? ''
        if (form.part_instance_id?.trim()) body.part_instance_id = form.part_instance_id.trim()
      }
      if (IDENTITY_STEPS.includes(action.step)) {
        if (!form.identity) return setMessage('เลือกอะไหล่ตามที่จ่ายจริงก่อน (ระบบไม่เดาให้)')
        const [partId, instanceId] = form.identity.split('|')
        body.part_id = partId
        if (instanceId) body.part_instance_id = instanceId
      }
      if (action.step === 'use-confirmations') body.position_code = form.position_code ?? ''
      if (action.step === 'return-declarations' && form.reason) body.reason = form.reason
    }
    setBusy(true)
    const result = await storeLineStep(repairId, action.line.requisition_line_id, action.step, body, id)
    setBusy(false)
    if (result.ok || result.error instanceof ApiError) delete uncertain.current[key]
    else uncertain.current[key] = { id, form }
    if (result.ok) {
      actionIntent.reset()
      actionId.current = null
      setAction(null)
      setMessage(result.data.replayed ? 'รายการนี้บันทึกไว้แล้ว (ไม่บันทึกซ้ำ)' : `${STEP_LABEL[action.step]}แล้ว`)
      void load()
      onChanged?.()
    } else {
      if (result.error instanceof ApiError) actionId.current = null // a definite refusal: a new attempt is a new intent
      else onChanged?.() // unknown outcome: the write may have landed, so read-only views re-read (no write)
      setMessage(errorText(result.error))
    }
  }

  const steps = (line: StoreLineBalance): StoreLineStep[] => {
    const list: StoreLineStep[] = []
    if (line.decision === 'AWAITING' && hasCapability(CAN_TEST_STORE_APPROVE)) list.push('approvals', 'denials')
    if (line.decision === 'APPROVED' && Number(line.awaiting_issue) > 0 && hasCapability(CAN_TEST_STORE_ISSUE)) list.push('issues')
    if (Number(line.issued) - Number(line.used) - Number(line.return_declared) > 0) list.push('use-confirmations', 'return-declarations')
    if (Number(line.pending_return) > 0 && hasCapability(CAN_TEST_STORE_RECEIVE_RETURN)) list.push('return-acceptances')
    return list
  }

  if (loaded.hidden) return null
  return (
    <section className="card store-panel" aria-labelledby="store-panel-title">
      <h2 id="store-panel-title">อะไหล่ของใบงาน (ขอเบิก / จ่าย / ใช้จริง / คืน)</h2>
      <p className="store-panel__note">{data?.scope_note ?? 'ไม่ใช่บัญชีสต็อกคลัง'} — จ่ายแล้วไม่เท่ากับติดตั้ง</p>
      {loadError && <p role="alert">{loadError}</p>}
      {data && (
        <p role="status" className={data.state === 'RECONCILED' ? 'store-panel__ok' : 'store-panel__blocked'}>
          สถานะกระทบยอด: {data.state === 'RECONCILED' ? 'ครบแล้ว' : 'ยังไม่ครบ'}
          {data.blockers.length > 0 && ` (${data.blockers.map((b) => storeBlockerLabel[b] ?? b).join(', ')})`}
        </p>
      )}
      {message && <p role="status" className="store-panel__message">{message}</p>}
      {data && data.lines.length > 0 && (
        <div className="responsive-table">
          <table>
            <thead>
              <tr><th>รายการ</th><th>ขอ</th><th>อนุมัติ</th><th>จ่าย</th><th>ใช้จริง</th><th>แจ้งคืน</th><th>รับคืน</th>
                <th>ค้างกระทบยอด</th><th aria-label="การทำงาน" /></tr>
            </thead>
            <tbody>
              {data.lines.map((line) => (
                <tr key={line.requisition_line_id}>
                  <td data-label="รายการ">{line.part_description}{line.part_id ? ` (${line.part_id})` : ''}
                    {line.decision === 'DENIED' && ' — ปฏิเสธ'}</td>
                  <td data-label="ขอ">{line.requested} {line.unit}</td>
                  <td data-label="อนุมัติ">{line.decision === 'AWAITING' ? 'รอ' : line.approved}</td>
                  <td data-label="จ่าย">{line.issued}</td>
                  <td data-label="ใช้จริง">{line.used}</td>
                  <td data-label="แจ้งคืน">{line.return_declared}</td>
                  <td data-label="รับคืน">{line.return_accepted}</td>
                  <td data-label="ค้างกระทบยอด">{line.unreconciled}</td>
                  <td>
                    {steps(line).map((s) => (
                      <button key={s} type="button" className="button button--secondary" onClick={() => openAction(line, s)}>
                        {STEP_LABEL[s]}
                      </button>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {action && (
        <form className="store-panel__action" aria-label={STEP_LABEL[action.step]}
          onSubmit={(e) => { e.preventDefault(); void submitAction() }}>
          <h3>{STEP_LABEL[action.step]}: {action.line.part_description}</h3>
          {action.step === 'denials' ? (
            <div className="form-field"><label htmlFor="store-reason">เหตุผล *</label>
              <input id="store-reason" value={form.reason ?? ''} maxLength={300} onChange={(e) => setField('reason', e.target.value)} /></div>
          ) : (
            <div className="form-field"><label htmlFor="store-qty">จำนวน ({action.line.unit}) *</label>
              <input id="store-qty" inputMode="decimal" value={form.quantity ?? ''} onChange={(e) => setField('quantity', e.target.value)} /></div>
          )}
          {action.step === 'issues' && (
            <>
              <div className="form-field"><label htmlFor="store-part">รหัสอะไหล่ที่จ่ายจริง *</label>
                <input id="store-part" value={form.part_id ?? ''} onChange={(e) => setField('part_id', e.target.value)} /></div>
              <div className="form-field"><label htmlFor="store-instance">รหัสชิ้นงาน (ถ้าติดตามรายชิ้น — จ่ายทีละ 1)</label>
                <input id="store-instance" value={form.part_instance_id ?? ''}
                  onChange={(e) => setField('part_instance_id', e.target.value)} /></div>
            </>
          )}
          {IDENTITY_STEPS.includes(action.step) && (
            <div className="form-field"><label htmlFor="store-identity">อะไหล่ (ตามที่จ่ายจริง) *</label>
              <select id="store-identity" value={form.identity ?? ''} onChange={(e) => setField('identity', e.target.value)}>
                <option value="">— เลือก —</option>
                {identityOptions(action.line, action.step).map((p) => (
                  <option key={identityKey(p)} value={identityKey(p)}>
                    {identityLabel(p)} (คงเหลือ {String(remaining(p, action.step))} {action.line.unit})
                  </option>
                ))}
              </select></div>
          )}
          {action.step === 'use-confirmations' && (
            <div className="form-field"><label htmlFor="store-position">ตำแหน่งที่ติดตั้ง *</label>
              <input id="store-position" value={form.position_code ?? ''} maxLength={60}
                onChange={(e) => setField('position_code', e.target.value)} /></div>
          )}
          {action.step === 'return-declarations' && (
            <div className="form-field"><label htmlFor="store-return-reason">หมายเหตุ</label>
              <input id="store-return-reason" value={form.reason ?? ''} maxLength={300} onChange={(e) => setField('reason', e.target.value)} /></div>
          )}
          <button type="submit" className="button" disabled={busy}>บันทึก</button>
          <button type="button" className="button button--secondary" onClick={() => setAction(null)}>ยกเลิก</button>
        </form>
      )}
      {repairOpen && (
        <form className="store-panel__request" aria-label="ขอเบิกอะไหล่" onSubmit={(e) => { e.preventDefault(); void submitRequest() }}>
          <h3>ขอเบิกอะไหล่ (ขอได้หลายครั้งระหว่างงานยังเปิด)</h3>
          {lines.map((line, index) => (
            <div key={index} className="store-panel__line">
              <input aria-label={`รหัสอะไหล่ (ถ้ามี) แถว ${index + 1}`} placeholder="รหัสอะไหล่ (ถ้ามี)" value={line.part_id ?? ''}
                onChange={(e) => editLine(index, { part_id: e.target.value || undefined })} />
              <input aria-label={`รายละเอียด แถว ${index + 1}`} placeholder="รายละเอียด *" value={line.part_description}
                onChange={(e) => editLine(index, { part_description: e.target.value })} />
              <input aria-label={`จำนวน แถว ${index + 1}`} inputMode="decimal" value={line.quantity}
                onChange={(e) => editLine(index, { quantity: e.target.value })} />
              <input aria-label={`หน่วย แถว ${index + 1}`} value={line.unit} onChange={(e) => editLine(index, { unit: e.target.value })} />
            </div>
          ))}
          <button type="button" className="button button--secondary"
            onClick={() => { requestIntent.reset(); setLines((ls) => [...ls, { part_description: '', quantity: '1', unit: 'ชิ้น' }]) }}>
            เพิ่มแถว
          </button>
          <button type="submit" className="button" disabled={busy}>ส่งคำขอเบิก</button>
        </form>
      )}
      {data && data.events.length > 0 && (
        <details className="store-panel__events">
          <summary>ประวัติเหตุการณ์ ({data.events.length})</summary>
          <ul>
            {data.events.map((e) => (
              <li key={e.event_id}>{storeEventTypeLabel[e.event_type] ?? e.event_type} — {e.part_id || '-'} {e.quantity} {e.unit}
                {e.position_code ? ` @ ${e.position_code}` : ''} · {e.actor_user_id}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="store-panel__note">{data?.exceptions_note}</p>
    </section>
  )
}
