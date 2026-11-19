import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, apiGet } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import {
  CAN_MOVE_PERSONNEL_DEPARTMENT,
  CAN_TEST_MANAGE_MASTER_RECORDS,
  CAN_TRANSFER_EQUIPMENT_BRANCH,
} from '../lib/capabilityNames'
import { describeErrorCode } from '../lib/labels'
import {
  MASTER_ENTITY_LABEL,
  MASTER_FIELDS,
  MASTER_ID_COLUMN,
  listMasterRecords,
  preuatSend,
  saveMasterRecord,
  useRetainedRequestId,
} from '../lib/masterRecords'
import type { MasterEntityPath, MasterRecordOutcome } from '../lib/types'

/**
 * R8 PRE-UAT (workstream A) — create or edit ONE TEST master record (Mock/TEST only).
 * Only fields of the existing schema are offered; edit mode offers only the editable ones.
 * The retained request id makes a resend after a lost answer a replay, never a second row.
 */
export function MasterRecordForm({
  entity,
  recordId = null,
  initial = {},
  onSaved,
  onCancel,
}: {
  entity: MasterEntityPath
  recordId?: string | null
  initial?: Record<string, string>
  onSaved: (outcome: MasterRecordOutcome) => void
  onCancel?: () => void
}) {
  const fields = MASTER_FIELDS[entity].filter((f) => (recordId ? f.editable : true))
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, initial[f.name] ?? ''])))
  const [multi, setMulti] = useState<Record<string, string[]>>(() =>
    Object.fromEntries(fields.filter((f) => f.multi).map((f) => [f.name, (initial[f.name] ?? '').split(',').filter(Boolean)])))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestId = useRetainedRequestId()
  const label = MASTER_ENTITY_LABEL[entity]

  const change = (name: string, value: string) => {
    requestId.reset() // a changed form is a new intent
    setValues((v) => ({ ...v, [name]: value }))
  }
  const toggle = (name: string, value: string) => {
    requestId.reset()
    setMulti((m) => ({ ...m, [name]: m[name].includes(value) ? m[name].filter((x) => x !== value) : [...m[name], value] }))
  }

  const submit = async () => {
    const id = requestId.current()
    if (!id) {
      setError('เบราว์เซอร์นี้สร้างรหัสคำขอที่ปลอดภัยไม่ได้ จึงยังไม่ส่งข้อมูล')
      return
    }
    const body: Record<string, unknown> = {}
    for (const f of fields) {
      if (f.multi) body[f.name] = multi[f.name]
      else if (values[f.name].trim() !== '' || recordId) body[f.name] = values[f.name].trim()
    }
    setBusy(true)
    setError(null)
    const result = await saveMasterRecord(entity, recordId, body, id)
    setBusy(false)
    if (result.ok) {
      requestId.reset()
      onSaved(result.data)
    } else if (result.error instanceof ApiError) {
      setError(describeErrorCode(result.error.code))
    } else {
      setError('ไม่ได้รับคำตอบจากเซิร์ฟเวอร์ กด "บันทึก" อีกครั้งได้อย่างปลอดภัย (ระบบจะไม่บันทึกซ้ำ)')
    }
  }

  return (
    <form className="master-record-form card" onSubmit={(e) => { e.preventDefault(); void submit() }}
      aria-label={`${recordId ? 'แก้ไข' : 'เพิ่ม'}${label} (TEST)`}>
      <p className="master-record-form__note">ข้อมูลทดสอบ (TEST) เท่านั้น — ไม่ใช่ข้อมูลจริง</p>
      {fields.map((f) => (
        <div className="form-field" key={f.name}>
          {f.multi ? (
            <fieldset>
              <legend>{f.label}{f.required ? ' *' : ''}</legend>
              {f.choices?.map((c) => (
                <label key={c.value} className="master-record-form__check">
                  <input type="checkbox" checked={multi[f.name].includes(c.value)} onChange={() => toggle(f.name, c.value)} />
                  {c.label}
                </label>
              ))}
            </fieldset>
          ) : (
            <>
              <label htmlFor={`mr-${entity}-${f.name}`}>{f.label}{f.required ? ' *' : ''}</label>
              {f.choices ? (
                <select id={`mr-${entity}-${f.name}`} value={values[f.name]} onChange={(e) => change(f.name, e.target.value)}>
                  <option value="">— เลือก —</option>
                  {f.choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              ) : (
                <input id={`mr-${entity}-${f.name}`} value={values[f.name]} maxLength={120}
                  onChange={(e) => change(f.name, e.target.value)} />
              )}
            </>
          )}
        </div>
      ))}
      {error && <p role="alert" className="form-error">{error}</p>}
      <div className="master-record-form__actions">
        <button type="submit" className="button" disabled={busy}>{busy ? 'กำลังบันทึก…' : 'บันทึก'}</button>
        {onCancel && <button type="button" className="button button--secondary" onClick={onCancel}>ยกเลิก</button>}
      </div>
    </form>
  )
}

/** The create entry point on an existing list page: shown only to a holder of the TEST grant
 * (the backend enforces it); a created record opens its own existing page. */
export function MasterCreatePanel({ entity, detailPath }: { entity: MasterEntityPath; detailPath: (id: string) => string }) {
  const { hasCapability } = useCapabilities()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  if (!hasCapability(CAN_TEST_MANAGE_MASTER_RECORDS)) return null
  return (
    <div className="master-create-panel">
      {!open && (
        <button type="button" className="button" onClick={() => setOpen(true)}>
          เพิ่ม{MASTER_ENTITY_LABEL[entity]} (TEST)
        </button>
      )}
      {/* Independent review: the form stays mounted while hidden, so cancel + reopen keeps its values and its
          retained request id; a resend after a lost answer is then a replay, never a second record. */}
      <div hidden={!open}>
        <MasterRecordForm entity={entity} onCancel={() => setOpen(false)}
          onSaved={(o) => navigate(detailPath(o.record_id))} />
      </div>
    </div>
  )
}

/** Edit entry point on an existing detail page: offered only for a TEST row and to a holder of
 * the TEST grant; REAL rows stay read-only here. */
export function MasterEditPanel({ entity, recordId }: { entity: MasterEntityPath; recordId: string }) {
  const { hasCapability } = useCapabilities()
  const [row, setRow] = useState<Record<string, string> | null>(null)
  const [open, setOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const allowed = hasCapability(CAN_TEST_MANAGE_MASTER_RECORDS)
  useEffect(() => {
    if (!allowed) return
    let live = true
    void listMasterRecords(entity).then((r) => {
      if (live) setRow(r.ok ? r.data.items.find((i) => i[MASTER_ID_COLUMN[entity]] === recordId) ?? null : null)
    })
    return () => { live = false }
  }, [allowed, entity, recordId, notice])
  if (!allowed || !row || row.scope !== 'TEST') return null
  return (
    <div className="master-edit-panel">
      {notice && <p role="status">{notice}</p>}
      {!open && <button type="button" className="button button--secondary" onClick={() => setOpen(true)}>แก้ไขข้อมูล (TEST)</button>}
      {open && (
        <MasterRecordForm entity={entity} recordId={recordId} initial={row} onCancel={() => setOpen(false)}
          onSaved={(o) => { setOpen(false); setNotice(o.action === 'NO_CHANGE' ? 'ไม่มีการเปลี่ยนแปลง' : 'บันทึกแล้ว — โหลดหน้าใหม่เพื่อดูข้อมูลล่าสุด') }} />
      )}
    </div>
  )
}

interface BranchHistoryLite { history_revision: string; current: { branch_id: string | null } }

/** Equipment branch assignment through the EXISTING audited route (R2d), which had no UI. */
export function EquipmentBranchAssignPanel({ equipmentId }: { equipmentId: string }) {
  const { hasCapability } = useCapabilities()
  const allowed = hasCapability(CAN_TRANSFER_EQUIPMENT_BRANCH)
  const [loaded, setLoaded] = useState<{ history: BranchHistoryLite | null; branches: { branch_id: string; branch_name: string }[] }>(
    { history: null, branches: [] })
  const { history, branches } = loaded
  const [branch, setBranch] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const requestId = useRetainedRequestId()
  const generation = useRef(0)
  const reload = useCallback(async () => {
    const current = ++generation.current
    const [h, b] = await Promise.all([
      apiGet<BranchHistoryLite>(`/equipment/${encodeURIComponent(equipmentId)}/branch-history`),
      apiGet<{ items: { branch_id: string; branch_name: string }[] }>('/branches'),
    ])
    if (current !== generation.current) return
    setLoaded((prev) => ({ history: h.ok ? h.data : prev.history, branches: b.ok ? b.data.items : prev.branches }))
  }, [equipmentId])
  useEffect(() => {
    if (allowed) void reload()
  }, [allowed, reload])
  if (!allowed) return null
  const submit = async () => {
    const id = requestId.current()
    if (!id || !history || !branch) return
    setBusy(true)
    const result = await preuatSend(`/equipment/${encodeURIComponent(equipmentId)}/branch-assignments`, 'POST', {
      to_branch_id: branch, effective: { mode: 'NOW' }, expected_current_branch_id: history.current.branch_id,
      expected_history_revision: history.history_revision }, id)
    setBusy(false)
    if (result.ok) { requestId.reset(); setMessage('บันทึกสาขาแล้ว'); void reload() }
    else setMessage(describeErrorCode(result.error instanceof ApiError ? result.error.code : undefined))
  }
  return (
    <div className="card equipment-branch-assign">
      <h2>กำหนด/ย้ายสาขาเครื่องมือ</h2>
      <p>สาขาปัจจุบัน: {history?.current.branch_id ?? 'ยังไม่ระบุ'}</p>
      <label htmlFor="eq-branch">สาขาใหม่</label>
      <select id="eq-branch" value={branch} onChange={(e) => { requestId.reset(); setBranch(e.target.value) }}>
        <option value="">— เลือกสาขา —</option>
        {branches.map((b) => <option key={b.branch_id} value={b.branch_id}>{b.branch_name}</option>)}
      </select>
      <button type="button" className="button" disabled={busy || !branch || !history} onClick={() => void submit()}>
        บันทึกสาขา (มีผลตอนนี้)
      </button>
      {message && <p role="status">{message}</p>}
    </div>
  )
}

/** Personnel department movement through the EXISTING audited route (R2f-g), which had no UI. */
export function PersonnelDepartmentMovePanel({ personnelId }: { personnelId: string }) {
  const { hasCapability } = useCapabilities()
  const allowed = hasCapability(CAN_MOVE_PERSONNEL_DEPARTMENT)
  const [loaded, setLoaded] = useState<{ current: string | null | undefined;
    departments: { department_id: string; department_name_th: string }[] }>({ current: undefined, departments: [] })
  const { current, departments } = loaded
  const [target, setTarget] = useState('')
  const [reason, setReason] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const requestId = useRetainedRequestId()
  const generation = useRef(0)
  const reload = useCallback(async () => {
    const current = ++generation.current
    const [h, d] = await Promise.all([
      apiGet<{ current_department_id: string | null }>(`/personnel/${encodeURIComponent(personnelId)}/department-history`),
      apiGet<{ items: { department_id: string; department_name_th: string }[] }>('/departments?page_size=200'),
    ])
    if (current !== generation.current) return
    setLoaded((prev) => ({ current: h.ok ? h.data.current_department_id : prev.current,
      departments: d.ok ? d.data.items : prev.departments }))
  }, [personnelId])
  useEffect(() => {
    if (allowed) void reload()
  }, [allowed, reload])
  if (!allowed || current === undefined) return null
  const submit = async () => {
    const id = requestId.current()
    if (!id || !target) return
    const result = await preuatSend(`/personnel/${encodeURIComponent(personnelId)}/department-events`, 'POST', {
      operation: 'TRANSFER', department_id: target, effective: { mode: 'NOW' },
      expected_current_department_id: current, ...(reason.trim() ? { reason_th: reason.trim() } : {}) }, id)
    if (result.ok) { requestId.reset(); setMessage('บันทึกการย้ายแผนกแล้ว'); void reload() }
    else setMessage(describeErrorCode(result.error instanceof ApiError ? result.error.code : undefined))
  }
  return (
    <div className="card personnel-department-move">
      <h2>ย้ายแผนก</h2>
      <p>แผนกปัจจุบัน: {current ?? 'ยังไม่มีแผนก'}</p>
      <label htmlFor="pd-target">แผนกใหม่</label>
      <select id="pd-target" value={target} onChange={(e) => { requestId.reset(); setTarget(e.target.value) }}>
        <option value="">— เลือกแผนก —</option>
        {departments.map((d) => <option key={d.department_id} value={d.department_id}>{d.department_name_th}</option>)}
      </select>
      <label htmlFor="pd-reason">เหตุผล (ไม่บังคับ)</label>
      <input id="pd-reason" value={reason} maxLength={300} onChange={(e) => { requestId.reset(); setReason(e.target.value) }} />
      <button type="button" className="button" disabled={!target} onClick={() => void submit()}>บันทึกการย้าย (มีผลตอนนี้)</button>
      {message && <p role="status">{message}</p>}
    </div>
  )
}
