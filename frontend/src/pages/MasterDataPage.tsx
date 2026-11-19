import { useCallback, useEffect, useRef, useState } from 'react'
import { MasterRecordForm } from '../components/MasterRecordForm'
import { ApiError } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_TEST_MANAGE_MASTER_RECORDS } from '../lib/capabilityNames'
import { describeErrorCode } from '../lib/labels'
import { MASTER_ENTITY_LABEL, MASTER_FIELDS, MASTER_ID_COLUMN, listMasterRecords } from '../lib/masterRecords'
import type { MasterEntityPath, MasterRecordList } from '../lib/types'

const TABS: MasterEntityPath[] = ['models', 'branches', 'technicians']

type LoadState = { kind: 'loading' } | { kind: 'denied' } | { kind: 'error'; message: string }
  | { kind: 'ready'; data: MasterRecordList }

function loadError(error: Error): LoadState {
  if (error instanceof ApiError && error.status === 403) return { kind: 'denied' }
  return { kind: 'error', message: describeErrorCode(error instanceof ApiError ? error.code : undefined) }
}

/**
 * R8 PRE-UAT (workstream A) — "ข้อมูลหลัก": models, branches and technicians (the masters
 * that had no page of their own). Everyone with can_view reads; a TEST row can be created or
 * edited only with the per-employee TEST grant (Mock/TEST only). REAL rows are read-only.
 */
export function MasterDataPage() {
  const { hasCapability } = useCapabilities()
  const canWrite = hasCapability(CAN_TEST_MANAGE_MASTER_RECORDS)
  const [tab, setTab] = useState<MasterEntityPath>('models')
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [mode, setMode] = useState<{ kind: 'none' } | { kind: 'create' } | { kind: 'edit'; row: Record<string, string> }>(
    { kind: 'none' })
  const [notice, setNotice] = useState<string | null>(null)

  const generation = useRef(0)
  const load = useCallback(async (entity: MasterEntityPath) => {
    const current = ++generation.current
    const result = await listMasterRecords(entity)
    if (current !== generation.current) return // a slower answer for an older tab never wins
    setState(result.ok ? { kind: 'ready', data: result.data } : loadError(result.error))
  }, [])

  useEffect(() => {
    void load(tab)
  }, [load, tab])

  const idColumn = MASTER_ID_COLUMN[tab]
  const columns = [idColumn, ...MASTER_FIELDS[tab].map((f) => f.name), 'scope']

  return (
    <section className="page">
      <h1>ข้อมูลหลัก</h1>
      <p>รุ่นรถ สาขา และช่าง — เพิ่ม/แก้ไขได้เฉพาะข้อมูลทดสอบ (TEST) โดยผู้ได้รับสิทธิ์ TEST รายบุคคล</p>
      <div className="tab-bar" role="tablist" aria-label="ประเภทข้อมูลหลัก">
        {TABS.map((t) => (
          <button key={t} role="tab" type="button" aria-selected={tab === t}
            className={tab === t ? 'button' : 'button button--secondary'}
            onClick={() => { setTab(t); setMode({ kind: 'none' }); setNotice(null); setState({ kind: 'loading' }) }}>
            {MASTER_ENTITY_LABEL[t]}
          </button>
        ))}
      </div>
      {notice && <p role="status" className="master-data__notice">{notice}</p>}
      {canWrite && mode.kind === 'none' && (
        <button type="button" className="button" onClick={() => setMode({ kind: 'create' })}>
          เพิ่ม{MASTER_ENTITY_LABEL[tab]} (TEST)
        </button>
      )}
      {mode.kind !== 'none' && (
        <MasterRecordForm key={`${tab}-${mode.kind}-${mode.kind === 'edit' ? mode.row[idColumn] : ''}`} entity={tab}
          recordId={mode.kind === 'edit' ? mode.row[idColumn] : null}
          initial={mode.kind === 'edit' ? mode.row : {}}
          onCancel={() => setMode({ kind: 'none' })}
          onSaved={(o) => {
            setMode({ kind: 'none' })
            setNotice(o.action === 'NO_CHANGE' ? 'ไม่มีการเปลี่ยนแปลง' : `บันทึกแล้ว: ${o.record_id}${o.replayed ? ' (คำขอเดิม)' : ''}`)
            void load(tab)
          }} />
      )}
      {state.kind === 'loading' && <p>กำลังโหลด…</p>}
      {state.kind === 'denied' && <p role="alert">ไม่มีสิทธิ์ดูข้อมูลนี้</p>}
      {state.kind === 'error' && <p role="alert">{state.message}</p>}
      {state.kind === 'ready' && (
        <div className="responsive-table">
          <table>
            <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}<th aria-label="การทำงาน" /></tr></thead>
            <tbody>
              {state.data.items.map((row) => (
                <tr key={row[idColumn]}>
                  {columns.map((c) => <td key={c} data-label={c}>{row[c] ?? ''}</td>)}
                  <td>
                    {canWrite && row.scope === 'TEST' && MASTER_FIELDS[tab].some((f) => f.editable) && (
                      <button type="button" className="button button--secondary" onClick={() => setMode({ kind: 'edit', row })}>
                        แก้ไข
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="fleet-status__scope">{state.kind === 'ready' ? state.data.note_th : ''}</p>
    </section>
  )
}
