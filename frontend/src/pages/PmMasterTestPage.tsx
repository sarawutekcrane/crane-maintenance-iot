import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_TEST_PM_MASTER_ASSIGN, CAN_TEST_PM_MASTER_PUBLISH } from '../lib/capabilityNames'
import { describeErrorCode } from '../lib/labels'
import { useRetainedRequestId } from '../lib/masterRecords'
import {
  approvePmMasterTestVariant,
  assignPmMasterTest,
  getPmMasterTestPreview,
  getPmMasterTestStatus,
  METER_DECISIONS,
  publishPmMasterTest,
  registerPmMasterTestPreview,
  resolvePmMasterTestReview,
  type PmMasterTestPreview,
  type PmMasterTestStatus,
} from '../lib/pmMasterTest'

/**
 * R8 PRE-UAT SG-PM — "แผน PM หลัก (ทดสอบ)": the PM Master TEST profile, step by step:
 * 1 register the built-in SYNTHETIC source → 2 resolve REVIEW entries → 3 publish → 4 approve the
 * model variant → 5 assign a vehicle → then open a PM Work Order from the vehicle's PM Due page.
 * TEST only; every step is re-checked by the backend (per-employee TEST grants, D6, replay).
 */

const EVIDENCE = 'ตรวจทานกับเอกสารต้นฉบับสังเคราะห์แล้ว (TEST)'

function errorText(error: Error): string {
  return error instanceof ApiError ? `${describeErrorCode(error.code)} (${error.code})`
    : 'ไม่ได้รับคำตอบจากเซิร์ฟเวอร์ ส่งอีกครั้งได้อย่างปลอดภัย (ระบบจะไม่บันทึกซ้ำ)'
}

export function PmMasterTestPage() {
  const { hasCapability } = useCapabilities()
  const canPublish = hasCapability(CAN_TEST_PM_MASTER_PUBLISH)
  const canAssign = hasCapability(CAN_TEST_PM_MASTER_ASSIGN)
  const [loaded, setLoaded] = useState<{ status: PmMasterTestStatus | null; preview: PmMasterTestPreview | null;
    state: 'loading' | 'ready' | 'disabled' | 'denied' | 'error'; error?: string }>({ status: null, preview: null, state: 'loading' })
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [meter, setMeter] = useState<Record<string, string>>({})
  const [assignVehicle, setAssignVehicle] = useState('UAT8-VEH-01')
  const intents = {
    preview: useRetainedRequestId(), review: useRetainedRequestId(), publish: useRetainedRequestId(),
    variant: useRetainedRequestId(), assign: useRetainedRequestId(),
  }

  const generation = useRef(0)
  const load = useCallback(async () => {
    const current = ++generation.current
    const s = await getPmMasterTestStatus()
    const p = s.ok && s.data.latest_preview_id ? await getPmMasterTestPreview(s.data.latest_preview_id) : null
    if (current !== generation.current) return
    const code = !s.ok && s.error instanceof ApiError ? s.error.status : 0
    setLoaded(s.ok ? { status: s.data, preview: p && p.ok ? p.data : null, state: 'ready' }
      : { status: null, preview: null, state: code === 404 ? 'disabled' : code === 403 ? 'denied' : 'error',
        error: errorText(s.error) })
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function run<T>(intent: ReturnType<typeof useRetainedRequestId>, call: (id: string) => Promise<{ ok: true; data: T } | { ok: false; error: Error }>, done: string) {
    const id = intent.current()
    if (!id) return setMessage('สร้างรหัสคำขอที่ปลอดภัยไม่ได้ จึงยังไม่ส่ง')
    setBusy(true)
    const result = await call(id)
    setBusy(false)
    if (result.ok) {
      intent.reset()
      setMessage(done)
      void load()
    } else {
      if (result.error instanceof ApiError) intent.reset() // a definite refusal: the next attempt is a new intent
      setMessage(errorText(result.error))
    }
  }

  if (loaded.state === 'loading') return <section className="page"><h1>แผน PM หลัก (ทดสอบ)</h1><p>กำลังโหลด...</p></section>
  if (loaded.state === 'disabled') {
    return (
      <section className="page">
        <h1>แผน PM หลัก (ทดสอบ)</h1>
        <p role="status">ยังไม่เปิดโปรไฟล์ทดสอบแผน PM หลักบนเซิร์ฟเวอร์นี้ (ต้องเปิด PM_MASTER_TEST_PROFILE ใน Mock/TEST เท่านั้น)</p>
      </section>
    )
  }
  if (loaded.state === 'denied') return <section className="page"><h1>แผน PM หลัก (ทดสอบ)</h1><p role="alert">ไม่มีสิทธิ์ดูข้อมูลนี้</p></section>
  if (loaded.state === 'error' || !loaded.status) {
    return <section className="page"><h1>แผน PM หลัก (ทดสอบ)</h1><p role="alert">{loaded.error}</p></section>
  }

  const { status, preview } = loaded
  const head = status.head_revision
  const openReviews = preview?.ledger.filter((e) => e.action === 'REVIEW' && !e.resolved) ?? []
  const variants = [...new Set(head?.sets.map((s) => s.model_variant) ?? [])]
  const approvals = (variant: string) => status.variant_approvals.filter((a) => a.model_variant === variant)
  const assignment = status.assignments.filter((a) => a.vehicle_id === assignVehicle && a.assembly === '').at(-1)

  return (
    <section className="page pm-master-test">
      <h1>แผน PM หลัก (ทดสอบ)</h1>
      <p className="classification-panel__badge">{status.note_th}</p>
      <p>แผน: <strong>{status.plan_code}</strong> · ต้นทาง: {status.source_file}</p>
      {message && <p role="status" className="pm-master-test__message">{message}</p>}

      <div className="card">
        <h2>1 ลงทะเบียนข้อมูลต้นทาง (สังเคราะห์)</h2>
        {preview ? <p>ตัวอย่างล่าสุด: {preview.preview_id} · digest {preview.source_digest.slice(0, 12)}…</p> : <p>ยังไม่มีตัวอย่าง</p>}
        {canPublish && (
          <button type="button" className="button" disabled={busy}
            onClick={() => void run(intents.preview, (id) => registerPmMasterTestPreview('ลงทะเบียนต้นทางสังเคราะห์สำหรับ UAT', id),
              'ลงทะเบียนตัวอย่างแล้ว')}>
            ลงทะเบียนต้นทางสังเคราะห์
          </button>
        )}
      </div>

      {preview && (
        <div className="card">
          <h2>2 ตรวจทานรายการที่ต้องตัดสินใจ ({openReviews.length} รายการค้าง)</h2>
          <ul aria-label="รายการตรวจทาน">
            {preview.ledger.filter((e) => e.action === 'REVIEW').map((e) => (
              <li key={e.entry_id}>
                {e.issue} · {e.row_or_key} · {e.resolved ? 'ตัดสินใจแล้ว' : 'ค้าง'}
                {!e.resolved && canPublish && (
                  <span className="pm-master-test__review">
                    <label htmlFor={`meter-${e.entry_id}`}>มิเตอร์ที่ใช้</label>
                    <select id={`meter-${e.entry_id}`} value={meter[e.entry_id] ?? ''}
                      onChange={(ev) => { intents.review.reset(); setMeter((m) => ({ ...m, [e.entry_id]: ev.target.value })) }}>
                      <option value="">— เลือก —</option>
                      {METER_DECISIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                    </select>
                    <button type="button" className="button button--secondary" disabled={busy || !meter[e.entry_id]}
                      onClick={() => {
                        const d = METER_DECISIONS.find((x) => x.value === meter[e.entry_id])!
                        void run(intents.review, (id) => resolvePmMasterTestReview(preview.preview_id, {
                          expected_source_digest: preview.source_digest, entry_id: e.entry_id, outcome: 'RESOLVE_METER',
                          evidence: EVIDENCE, values: { meter_type: d.meter_type, driving_component: d.driving_component } }, id),
                        'บันทึกการตัดสินใจแล้ว')
                      }}>
                      ยืนยันมิเตอร์
                    </button>
                    <button type="button" className="button button--secondary" disabled={busy}
                      onClick={() => void run(intents.review, (id) => resolvePmMasterTestReview(preview.preview_id, {
                        expected_source_digest: preview.source_digest, entry_id: e.entry_id, outcome: 'EXCLUDE_ROW',
                        evidence: EVIDENCE }, id), 'ตัดแถวนี้ออกแล้ว')}>
                      ตัดแถวนี้ออก
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
          {canPublish && (
            <>
              <h2>3 เผยแพร่แผน</h2>
              <button type="button" className="button" disabled={busy || openReviews.length > 0}
                onClick={() => void run(intents.publish, (id) => publishPmMasterTest({ preview_id: preview.preview_id,
                  expected_source_digest: preview.source_digest, expected_revision: head?.revision_number ?? 0,
                  reason: 'เผยแพร่แผนทดสอบ UAT' }, id), 'เผยแพร่แล้ว')}>
                เผยแพร่ฉบับที่ {(head?.revision_number ?? 0) + 1}
              </button>
              {openReviews.length > 0 && <p className="form-field__hint">ต้องตัดสินใจรายการค้างก่อน จึงจะเผยแพร่ได้</p>}
            </>
          )}
        </div>
      )}

      {head && (
        <div className="card">
          <h2>ฉบับที่ใช้งาน: {head.revision_number}</h2>
          <table className="responsive-table">
            <thead><tr><th>ชุดงาน (Set)</th><th>มิเตอร์</th><th>รอบ</th><th>รายการ</th></tr></thead>
            <tbody>
              {head.sets.map((s) => (
                <tr key={s.set_key}>
                  <td data-label="ชุดงาน">{s.set_key}</td>
                  <td data-label="มิเตอร์">{s.meter_type}</td>
                  <td data-label="รอบ">{s.interval_value ?? '-'} {s.interval_unit}</td>
                  <td data-label="รายการ">{s.items.map((i) => i.task_text).join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>4 อนุมัติรุ่นที่ใช้แผนนี้</h2>
          {variants.map((variant) => {
            const rows = preview?.mapping_candidates.filter((m) => m.plan_model === variant && m.status === 'MATCHED_PENDING_IMPLEMENTATION') ?? []
            const latest = approvals(variant).at(-1)
            const model = variant === 'UAT8-V-A' ? 'UAT8-MDL-A' : variant === 'UAT8-V-B' ? 'UAT8-MDL-B' : ''
            return (
              <p key={variant}>
                {variant} → {model || 'ไม่มีรุ่นที่จับคู่'} · {latest ? `${latest.state} (ฉบับ ${latest.version})` : 'ยังไม่อนุมัติ'}{' '}
                {canPublish && preview && model && rows.length > 0 && latest?.state !== 'APPROVED' && (
                  <button type="button" className="button button--secondary" disabled={busy}
                    onClick={() => void run(intents.variant, (id) => approvePmMasterTestVariant({ model_id: model,
                      model_variant: variant, expected_version: latest?.version ?? 0, preview_id: preview.preview_id,
                      expected_source_digest: preview.source_digest, source_rows: rows.map((r) => r.source_row),
                      evidence: EVIDENCE, reason: 'อนุมัติรุ่นตามตารางจับคู่สังเคราะห์' }, id), 'อนุมัติรุ่นแล้ว')}>
                    อนุมัติ {variant}
                  </button>
                )}
              </p>
            )
          })}
          <h2>5 กำหนดแผนให้รถ</h2>
          <label htmlFor="pmt-vehicle">รหัสรถ</label>
          <input id="pmt-vehicle" value={assignVehicle} onChange={(e) => { intents.assign.reset(); setAssignVehicle(e.target.value) }} />
          <p>สถานะปัจจุบัน: {assignment ? `${assignment.state} ${assignment.plan_code ?? ''} (ฉบับ ${assignment.version})` : 'ยังไม่กำหนด'}</p>
          {canAssign && (
            <button type="button" className="button" disabled={busy || !assignVehicle.trim()}
              onClick={() => void run(intents.assign, (id) => assignPmMasterTest({ vehicle_id: assignVehicle.trim(),
                assembly: '', plan_code: status.plan_code, expected_version: assignment?.version ?? 0,
                reason: 'กำหนดแผนทดสอบ UAT' }, id), 'กำหนดแผนแล้ว')}>
              กำหนดแผนให้ {assignVehicle}
            </button>
          )}
          {assignment?.state === 'ASSIGNED' && (
            <p><Link to={`/vehicle/${encodeURIComponent(assignVehicle)}/pm/due`}>ดูกำหนด PM และเปิดใบงานจากแผนหลัก →</Link></p>
          )}
        </div>
      )}
      {!canPublish && !canAssign && <p>ดูได้อย่างเดียว — การเปลี่ยนแปลงต้องได้รับสิทธิ์ TEST รายบุคคล</p>}
    </section>
  )
}
