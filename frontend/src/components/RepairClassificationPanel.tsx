import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_TEST_CLASSIFY_REPAIR } from '../lib/capabilityNames'
import { classificationStateLabel, describeErrorCode, storeBlockerLabel } from '../lib/labels'
import { useRetainedRequestId } from '../lib/masterRecords'
import {
  finalizeClassification,
  getRepairCatalogue,
  getRepairClassification,
  stageClassification,
} from '../lib/repairClassification'
import type { ClassificationRow, RepairCatalogue, RepairClassification } from '../lib/types'

/**
 * R8 PRE-UAT (Owner Decision 2) — TEST repair classification on the repair page.
 * Closure → Store reconciliation → waiting → classification. SYSTEM → ASSEMBLY → POINT
 * dependent dropdowns come ONLY from the TEST-CANDIDATE-R1 subset. Symptoms (allowed per
 * point) and repair actions (A01–A15) are separate selections, with several failure points
 * per repair and position as separate fields. Labelled "TEST candidate — not for REAL";
 * the backend validates every code fail-closed.
 */

const POSITION_LABEL: Record<string, string> = { side: 'ซ้าย/ขวา', end: 'หน้า/หลัง', axle: 'เพลา', level: 'บน/ล่าง',
  hoist: 'รอกหลัก/เสริม' }
const CHOICE_LABEL: Record<string, string> = { LEFT: 'ซ้าย', RIGHT: 'ขวา', FRONT: 'หน้า', REAR: 'หลัง', UPPER: 'บน',
  LOWER: 'ล่าง', MAIN: 'หลัก', AUXILIARY: 'เสริม' }

function errorText(error: Error): string {
  return error instanceof ApiError ? describeErrorCode(error.code)
    : 'ไม่ได้รับคำตอบจากเซิร์ฟเวอร์ ส่งอีกครั้งได้อย่างปลอดภัย (ระบบจะไม่บันทึกซ้ำ)'
}

export function RepairClassificationPanel({ repairId }: { repairId: string }) {
  const { hasCapability } = useCapabilities()
  const canClassify = hasCapability(CAN_TEST_CLASSIFY_REPAIR)
  const [cls, setCls] = useState<{ view: RepairClassification | null; error: string | null; hidden?: boolean }>(
    { view: null, error: null })
  const view = cls.view
  const loadError = cls.error
  const [catalogue, setCatalogue] = useState<RepairCatalogue | null>(null)
  const [localRows, setRows] = useState<ClassificationRow[] | null>(null)
  const rows = localRows ?? view?.draft_rows ?? []
  const setView = (next: RepairClassification) => {
    setCls({ view: next, error: null })
    setRows(null) // the server draft is the source of truth after every answer
  }
  const [pick, setPick] = useState({ system: '', assembly: '', point: '' })
  const [symptoms, setSymptoms] = useState<string[]>([])
  const [actions, setActions] = useState<string[]>([])
  const [position, setPosition] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const stageIntent = useRetainedRequestId()
  const finalIntent = useRetainedRequestId()

  const generation = useRef(0)
  const load = useCallback(async () => {
    const current = ++generation.current
    const result = await getRepairClassification(repairId)
    if (current !== generation.current) return
    // 501 (repository without the feature) or 403 (no permission): no panel instead of an error alert.
    const unavailable = !result.ok && result.error instanceof ApiError && [403, 501].includes(result.error.status)
    setCls((prev) => (result.ok ? { view: result.data, error: null }
      : unavailable ? { view: null, error: null, hidden: true } : { view: prev.view, error: errorText(result.error) }))
    setRows(null)
  }, [repairId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!canClassify || view?.state !== 'WAITING_FOR_CLASSIFICATION' || catalogue) return
    let live = true
    void getRepairCatalogue().then((r) => {
      if (live && r.ok) setCatalogue(r.data)
    })
    return () => { live = false }
  }, [canClassify, view?.state, catalogue])

  const system = useMemo(() => catalogue?.tree.find((s) => s.code === pick.system), [catalogue, pick.system])
  const assembly = useMemo(() => system?.assemblies.find((a) => a.code === pick.assembly), [system, pick.assembly])
  const point = useMemo(() => assembly?.points.find((p) => p.code === pick.point), [assembly, pick.point])

  const addRow = () => {
    if (!point || symptoms.length === 0 || actions.length === 0) {
      setMessage('เลือกระบบ ชุดอุปกรณ์ จุดเสีย อาการ และวิธีดำเนินงานให้ครบก่อน')
      return
    }
    stageIntent.reset()
    setRows([...rows, { system: pick.system, assembly: pick.assembly, point: pick.point, symptoms, actions,
      position: Object.fromEntries(Object.entries(position).filter(([, v]) => v)) }])
    setPick({ system: '', assembly: '', point: '' })
    setSymptoms([])
    setActions([])
    setPosition({})
    setMessage(null)
  }

  const stage = async () => {
    if (!view) return
    const id = stageIntent.current()
    if (!id) return setMessage('สร้างรหัสคำขอที่ปลอดภัยไม่ได้ จึงยังไม่ส่ง')
    const result = await stageClassification(repairId, view.draft_revision, rows, id)
    if (result.ok) { stageIntent.reset(); setView(result.data); setMessage('บันทึกร่างแล้ว') }
    else setMessage(errorText(result.error))
  }

  const finalize = async () => {
    if (!view) return
    const id = finalIntent.current()
    if (!id) return setMessage('สร้างรหัสคำขอที่ปลอดภัยไม่ได้ จึงยังไม่ส่ง')
    const result = await finalizeClassification(repairId, view.draft_revision, id)
    if (result.ok) { finalIntent.reset(); setView(result.data); setMessage('จัดประเภทเรียบร้อย (TEST)') }
    else setMessage(errorText(result.error))
  }

  const toggle = (list: string[], set: (v: string[]) => void, value: string) => {
    stageIntent.reset()
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value])
  }

  const rowLabel = (r: ClassificationRow) =>
    `${r.system}-${r.assembly}-${r.point} · อาการ ${r.symptoms.join(', ')} · วิธี ${r.actions.join(', ')}` +
    (Object.keys(r.position).length ? ` · ตำแหน่ง ${Object.entries(r.position).map(([k, v]) =>
      `${POSITION_LABEL[k] ?? k}: ${CHOICE_LABEL[v] ?? v}`).join(', ')}` : '')

  if (cls.hidden) return null
  return (
    <section className="card classification-panel" aria-labelledby="classification-title">
      <h2 id="classification-title">จัดประเภทงานซ่อม</h2>
      <p className="classification-panel__badge">{view?.note_th ?? 'TEST candidate — ไม่อนุมัติสำหรับ REAL'}</p>
      {loadError && <p role="alert">{loadError}</p>}
      {view && (
        <p role="status">
          สถานะ: {classificationStateLabel[view.state] ?? view.state}
          {view.blockers.length > 0 && ` (${view.blockers.map((b) => storeBlockerLabel[b] ?? b).join(', ')})`}
        </p>
      )}
      {message && <p role="status" className="classification-panel__message">{message}</p>}
      {view?.state === 'CLASSIFIED' && view.final && (
        <ul aria-label="ผลการจัดประเภท">
          {(view.final.rows ?? []).map((r, i) => <li key={i}>{rowLabel(r)}</li>)}
        </ul>
      )}
      {view?.state === 'WAITING_FOR_CLASSIFICATION' && canClassify && catalogue && (
        <>
          <div className="classification-panel__pick">
            <label htmlFor="cl-system">1 ระบบหลัก</label>
            <select id="cl-system" value={pick.system}
              onChange={(e) => { setPick({ system: e.target.value, assembly: '', point: '' }); setSymptoms([]) }}>
              <option value="">— เลือก —</option>
              {catalogue.tree.map((s) => <option key={s.code} value={s.code}>{s.code} — {s.name}</option>)}
            </select>
            <label htmlFor="cl-assembly">2 ชุดอุปกรณ์</label>
            <select id="cl-assembly" value={pick.assembly} disabled={!system}
              onChange={(e) => { setPick((p) => ({ ...p, assembly: e.target.value, point: '' })); setSymptoms([]) }}>
              <option value="">— เลือก —</option>
              {system?.assemblies.map((a) => <option key={a.code} value={a.code}>{a.code} — {a.name}</option>)}
            </select>
            <label htmlFor="cl-point">3 จุดที่ผิดปกติ</label>
            <select id="cl-point" value={pick.point} disabled={!assembly}
              onChange={(e) => { setPick((p) => ({ ...p, point: e.target.value })); setSymptoms([]) }}>
              <option value="">— เลือก —</option>
              {assembly?.points.map((p) => <option key={p.code} value={p.code}>{p.code} — {p.name}</option>)}
            </select>
          </div>
          {point && (
            <fieldset>
              <legend>อาการ (เฉพาะที่ใช้กับจุดนี้ได้)</legend>
              {point.allowed_symptoms.map((s) => (
                <label key={s} className="classification-panel__check">
                  <input type="checkbox" checked={symptoms.includes(s)} onChange={() => toggle(symptoms, setSymptoms, s)} />
                  {s} — {catalogue.symptoms[s]}
                </label>
              ))}
            </fieldset>
          )}
          <fieldset>
            <legend>วิธีดำเนินงาน</legend>
            {Object.entries(catalogue.actions).map(([code, name]) => (
              <label key={code} className="classification-panel__check">
                <input type="checkbox" checked={actions.includes(code)} onChange={() => toggle(actions, setActions, code)} />
                {code} — {name}
              </label>
            ))}
          </fieldset>
          <fieldset>
            <legend>ตำแหน่ง (แยกจากรหัส ไม่บังคับ)</legend>
            {Object.entries(catalogue.position_fields).map(([key, choices]) => (
              <label key={key} className="classification-panel__position">
                {POSITION_LABEL[key] ?? key}
                {choices ? (
                  <select value={position[key] ?? ''} onChange={(e) => setPosition((p) => ({ ...p, [key]: e.target.value }))}>
                    <option value="">—</option>
                    {choices.map((c) => <option key={c} value={c}>{CHOICE_LABEL[c] ?? c}</option>)}
                  </select>
                ) : (
                  <input value={position[key] ?? ''} maxLength={20} onChange={(e) => setPosition((p) => ({ ...p, [key]: e.target.value }))} />
                )}
              </label>
            ))}
          </fieldset>
          <button type="button" className="button button--secondary" onClick={addRow}>เพิ่มจุดเสียในรายการ</button>
          {rows.length > 0 && (
            <ol aria-label="จุดเสียที่เตรียมจัดประเภท">
              {rows.map((r, i) => (
                <li key={i}>{rowLabel(r)}{' '}
                  <button type="button" className="button button--secondary"
                    onClick={() => { stageIntent.reset(); setRows(rows.filter((_, j) => j !== i)) }}>ลบ</button>
                </li>
              ))}
            </ol>
          )}
          <div className="classification-panel__actions">
            <button type="button" className="button" disabled={rows.length === 0} onClick={() => void stage()}>
              บันทึกร่าง (ฉบับที่ {view.draft_revision + 1})
            </button>
            <button type="button" className="button" disabled={view.draft_revision === 0 || localRows !== null}
              onClick={() => void finalize()}>
              ยืนยันจัดประเภท
            </button>
          </div>
          {localRows !== null && view.draft_revision > 0 && (
            <p role="status" className="classification-panel__note">
              มีการแก้ไขรายการที่ยังไม่ได้บันทึกร่าง — บันทึกร่างก่อน แล้วจึงยืนยันจัดประเภท (ยืนยันจะใช้ร่างที่บันทึกไว้เท่านั้น)
            </p>
          )}
          <p className="classification-panel__note">
            ชุดทดสอบมี {String(catalogue.summary.candidates)} ความสัมพันธ์ จาก {String(catalogue.summary.relationships)} แถวต้นฉบับ
            (ที่เหลือข้อมูลต้นฉบับยังขัดแย้ง/รอยืนยัน จึงเลือกไม่ได้)
          </p>
        </>
      )}
      {view?.state === 'WAITING_FOR_CLASSIFICATION' && !canClassify && (
        <p>รอผู้ได้รับมอบหมายจัดประเภท (สิทธิ์ TEST)</p>
      )}
    </section>
  )
}
