import { useState } from 'react'
import { ApiError, apiGet } from '../lib/apiClient'
import { describeErrorCode } from '../lib/labels'
import { CAN_TEST_MANAGE_PARTS } from '../lib/capabilityNames'
import { preuatSend, useRetainedRequestId, useTestGrantControlVisible } from '../lib/masterRecords'

/**
 * R8 PRE-UAT (workstream F) — UI for the EXISTING part-set routes (create a set, add a dated
 * revision with REQUIRED / OPTIONAL / ALTERNATIVE items, add model applicability), which had
 * no screen. Standard expectation only: it is not issued or installed stock, and not an
 * approved bill of materials. Google Sheets refuses alternative links (501).
 */
interface ItemRow { part_id: string; requirement: 'REQUIRED' | 'OPTIONAL' | 'ALTERNATIVE'; quantity: string; unit: string;
  alternative_for_index: string }

interface RevisionView { revision?: { revision_id: string; revision_number: number; effective_date: string }
  items?: { part_id: string; requirement: string; quantity: number | null; unit: string | null }[] }

function errorText(error: Error): string {
  return error instanceof ApiError ? describeErrorCode(error.code) : 'ไม่ได้รับคำตอบ ส่งอีกครั้งได้อย่างปลอดภัย'
}

/** Independent review 2026-11-18: the existing create-set and add-revision routes have NO server replay
 * (outside the PRE-UAT allowlist), so after a lost answer a resend could create a duplicate. The editor
 * says so instead of promising a safe resend, and reloads what is on the server first. */
const NO_REPLAY_TEXT = 'ไม่ทราบผล (ไม่ได้รับคำตอบ) — ระบบส่วนนี้ไม่มีการกันบันทึกซ้ำ: ตรวจรายการบนหน้าก่อน แล้วจึงส่งใหม่หากยังไม่มี'


export function PartSetEditor({ partId }: { partId: string }) {
  const visible = useTestGrantControlVisible(CAN_TEST_MANAGE_PARTS)
  const [setCode, setSetCode] = useState('')
  const [setName, setSetName] = useState('')
  const [setId, setSetId] = useState('')
  const [effective, setEffective] = useState('')
  const [items, setItems] = useState<ItemRow[]>([{ part_id: partId, requirement: 'REQUIRED', quantity: '1', unit: 'ชิ้น',
    alternative_for_index: '' }])
  const [modelId, setModelId] = useState('')
  const [from, setFrom] = useState('')
  const [active, setActive] = useState<RevisionView | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const createIntent = useRetainedRequestId()
  const revisionIntent = useRetainedRequestId()
  const applicabilityIntent = useRetainedRequestId()

  const createSet = async () => {
    const id = createIntent.current()
    if (!id) return
    const r = await preuatSend<{ part_set_id: string }>('/part-sets', 'POST', { set_code: setCode.trim(), name: setName.trim() }, id)
    createIntent.reset() // no server replay on this route: every attempt is its own request
    if (r.ok) { setSetId(r.data.part_set_id); setMessage(`สร้างชุดอะไหล่แล้ว: ${r.data.part_set_id}`) }
    else setMessage(r.error instanceof ApiError ? errorText(r.error) : NO_REPLAY_TEXT)
  }

  const addRevision = async () => {
    const id = revisionIntent.current()
    if (!id || !setId) return
    const body = { effective_date: effective, items: items.map((i) => ({ part_id: i.part_id.trim(), requirement: i.requirement,
      quantity: i.quantity ? Number(i.quantity) : null, unit: i.unit.trim() || null,
      ...(i.requirement === 'ALTERNATIVE' && i.alternative_for_index !== '' ? { alternative_for_index: Number(i.alternative_for_index) } : {}),
    })) }
    const r = await preuatSend(`/part-sets/${encodeURIComponent(setId)}/revisions`, 'POST', body, id)
    revisionIntent.reset() // no server replay on this route: every attempt is its own request
    if (r.ok) { setMessage('บันทึกฉบับปรับปรุงแล้ว'); void loadActive() }
    else if (r.error instanceof ApiError) setMessage(errorText(r.error))
    else { setMessage(NO_REPLAY_TEXT); void loadActive() }
  }

  const addApplicability = async () => {
    const id = applicabilityIntent.current()
    if (!id || !setId) return
    const r = await preuatSend(`/part-sets/${encodeURIComponent(setId)}/applicability`, 'POST',
      { model_id: modelId.trim(), effective_from: from }, id)
    if (r.ok) { applicabilityIntent.reset(); setMessage('บันทึกรุ่นที่ใช้ได้แล้ว') } else setMessage(errorText(r.error))
  }

  const loadActive = async () => {
    if (!setId) return
    const r = await apiGet<RevisionView>(`/part-sets/${encodeURIComponent(setId)}/active-revision`)
    setActive(r.ok ? r.data : null)
    if (!r.ok) setMessage(errorText(r.error))
  }

  const editItem = (index: number, patch: Partial<ItemRow>) => {
    revisionIntent.reset()
    setItems((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  if (!visible) return null
  return (
    <section className="card part-set-editor" aria-labelledby="part-set-title">
      <h2 id="part-set-title">ชุดอะไหล่ (Part Set)</h2>
      <p className="form-field__hint">ค่ามาตรฐานที่คาดว่าใช้ ไม่ใช่ของที่จ่ายหรือติดตั้งจริง และไม่ใช่ BOM ที่อนุมัติ</p>
      {message && <p role="status">{message}</p>}
      <div className="form-grid">
        <label htmlFor="ps-code">รหัสชุด</label>
        <input id="ps-code" value={setCode} onChange={(e) => { createIntent.reset(); setSetCode(e.target.value) }} />
        <label htmlFor="ps-name">ชื่อชุด</label>
        <input id="ps-name" value={setName} onChange={(e) => { createIntent.reset(); setSetName(e.target.value) }} />
        <button type="button" className="button" disabled={!setCode.trim() || !setName.trim()} onClick={() => void createSet()}>สร้างชุดอะไหล่</button>
      </div>
      <div className="form-grid">
        <label htmlFor="ps-id">รหัสชุดอะไหล่ที่จะจัดการ</label>
        <input id="ps-id" value={setId} onChange={(e) => setSetId(e.target.value)} />
        <button type="button" className="button button--secondary" disabled={!setId} onClick={() => void loadActive()}>ดูฉบับที่มีผล</button>
      </div>
      {active?.revision && (
        <p>ฉบับที่ {active.revision.revision_number} มีผล {active.revision.effective_date}:{' '}
          {(active.items ?? []).map((i) => `${i.part_id} (${i.requirement})`).join(', ')}</p>
      )}
      <h3>เพิ่มฉบับปรับปรุง</h3>
      <label htmlFor="ps-effective">วันที่มีผล</label>
      <input id="ps-effective" type="date" value={effective} onChange={(e) => { revisionIntent.reset(); setEffective(e.target.value) }} />
      {items.map((item, index) => (
        <div key={index} className="part-set-editor__item">
          <input aria-label={`รหัสอะไหล่ แถว ${index + 1}`} value={item.part_id} onChange={(e) => editItem(index, { part_id: e.target.value })} />
          <select aria-label={`ความจำเป็น แถว ${index + 1}`} value={item.requirement}
            onChange={(e) => editItem(index, { requirement: e.target.value as ItemRow['requirement'] })}>
            <option value="REQUIRED">จำเป็น</option>
            <option value="OPTIONAL">ไม่บังคับ</option>
            <option value="ALTERNATIVE">ทดแทนได้</option>
          </select>
          <input aria-label={`จำนวน แถว ${index + 1}`} inputMode="decimal" value={item.quantity} onChange={(e) => editItem(index, { quantity: e.target.value })} />
          <input aria-label={`หน่วย แถว ${index + 1}`} value={item.unit} onChange={(e) => editItem(index, { unit: e.target.value })} />
          {item.requirement === 'ALTERNATIVE' && (
            <input aria-label={`ทดแทนแถวที่ (เริ่ม 0) แถว ${index + 1}`} inputMode="numeric" value={item.alternative_for_index}
              onChange={(e) => editItem(index, { alternative_for_index: e.target.value })} />
          )}
        </div>
      ))}
      <button type="button" className="button button--secondary"
        onClick={() => { revisionIntent.reset(); setItems((rows) => [...rows, { part_id: '', requirement: 'OPTIONAL', quantity: '1', unit: 'ชิ้น', alternative_for_index: '' }]) }}>
        เพิ่มรายการ
      </button>
      <button type="button" className="button" disabled={!setId || !effective} onClick={() => void addRevision()}>บันทึกฉบับปรับปรุง</button>
      <h3>รุ่นรถที่ใช้ชุดนี้</h3>
      <label htmlFor="ps-model">รหัสรุ่น</label>
      <input id="ps-model" value={modelId} onChange={(e) => { applicabilityIntent.reset(); setModelId(e.target.value) }} />
      <label htmlFor="ps-from">มีผลตั้งแต่</label>
      <input id="ps-from" type="date" value={from} onChange={(e) => { applicabilityIntent.reset(); setFrom(e.target.value) }} />
      <button type="button" className="button" disabled={!setId || !modelId || !from} onClick={() => void addApplicability()}>บันทึกรุ่นที่ใช้ได้</button>
    </section>
  )
}
