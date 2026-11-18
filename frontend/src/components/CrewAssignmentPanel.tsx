import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, apiGet } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_ASSIGN_CRANE_CREW, CAN_VIEW } from '../lib/capabilityNames'
import { useCrewWrites } from '../lib/crewWrites'
import { formatE2Date, formatE2Span } from '../lib/e2Assignments'
import { crewRoleLabel, describeCrewErrorCode, resourceStatusLabel, resourceStatusTone } from '../lib/labels'
import type { CrewInterval, Page, VehicleCrew } from '../lib/types'
import { Card } from './Card'
import { CrewOperationDialog, type CrewOperation, type PersonnelOption } from './CrewOperationDialog'
import { StatusBadge } from './StatusBadge'

/**
 * R8 early workstream — the vehicle's crew members (Rigger, Signalman and other
 * roles; variable size, OD-1 = A), each with their OWN assigned interval, which may
 * differ from the operational driver's (CC-06). Reads need a trusted can_view
 * actor; actions appear only for a holder of the per-employee TEST grant
 * `can_assign_crane_crew` (OD-3 = A) and the backend enforces every rule again.
 * An empty list means no recorded crew assignment, not a verified free crew.
 */

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; crew: VehicleCrew }

function crewState(data: VehicleCrew): LoadState {
  // A 200 whose body is not the expected shape is an error, never an empty crew.
  return Array.isArray((data as Partial<VehicleCrew> | null)?.intervals)
    ? { kind: 'ready', crew: data }
    : { kind: 'error', message: describeCrewErrorCode(undefined) }
}

function crewErrorState(err: ApiError | Error): LoadState {
  if (err instanceof ApiError && err.status === 403) return { kind: 'denied' }
  return { kind: 'error', message: describeCrewErrorCode(err instanceof ApiError ? err.code : undefined) }
}

export function CrewAssignmentPanel({ vehicleId }: { vehicleId: string }) {
  const { hasCapability, userId } = useCapabilities()
  const canWrite = hasCapability(CAN_ASSIGN_CRANE_CREW) && hasCapability(CAN_VIEW)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [personnel, setPersonnel] = useState<PersonnelOption[]>([])
  const [dialog, setDialog] = useState<{ operation: CrewOperation; target: CrewInterval | null } | null>(null)
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error' | 'unknown'; text: string } | null>(null)
  const writes = useCrewWrites(vehicleId, userId)
  const generation = useRef(0)

  const load = useCallback(async () => {
    const current = ++generation.current
    const result = await apiGet<VehicleCrew>(`/vehicles/${encodeURIComponent(vehicleId)}/crew-assignments`)
    if (current !== generation.current) return
    setState(result.ok ? crewState(result.data) : crewErrorState(result.error))
  }, [vehicleId])

  useEffect(() => {
    void load() // a new vehicle mounts a fresh panel (the detail view is keyed by vehicle id)
  }, [load])

  useEffect(() => {
    if (!canWrite) return
    let cancelled = false
    void apiGet<Page<{ personnel_id: string; first_name: string | null; last_name: string | null; active_status: string | null }>>(
      '/personnel?page_size=200',
    ).then((result) => {
      if (cancelled || !result.ok) return
      setPersonnel(
        result.data.items
          .filter((p) => p.active_status === 'ACTIVE')
          .map((p) => ({ personnel_id: p.personnel_id, name: [p.first_name, p.last_name].filter(Boolean).join(' ') })),
      )
    })
    return () => {
      cancelled = true
    }
  }, [canWrite])

  const submit = async (body: Record<string, unknown>) => {
    const result = await writes.submit(body)
    report(result)
  }

  const report = (result: Awaited<ReturnType<typeof writes.submit>>) => {
    if (result.kind === 'success') {
      setDialog(null)
      const warn = result.warnings.includes('PERSON_ADJACENT_ASSIGNMENT_REST_WARNING')
        ? ' (บุคคลนี้มีงานต่อเนื่องติดกัน โปรดคำนึงถึงการพักและความพร้อม — การบันทึกไม่ใช่การรับรองความปลอดภัย)'
        : ''
      setNotice({ tone: 'ok', text: (result.changed || result.replayed ? 'บันทึกแล้ว' : 'มีการมอบหมายนี้อยู่แล้ว') + warn })
      void load()
    } else if (result.kind === 'unknown') {
      setNotice({ tone: 'unknown', text: result.message })
    } else {
      setNotice({ tone: 'error', text: result.message })
    }
  }

  return (
    <Card>
      <h2>ทีมงานประจำเครน (Crew)</h2>
      <p className="vehicle-overview__muted">
        คนขับปฏิบัติงานแสดงในส่วน “ผู้ขับปฏิบัติงาน” ด้านบน ส่วนนี้คือทีมงานอื่น (Rigger, Signalman และอื่นๆ)
        แต่ละคนมีช่วงเวลาของตนเอง
      </p>
      {state.kind === 'loading' && <p>กำลังโหลดทีมงาน...</p>}
      {state.kind === 'denied' && <p>ไม่มีสิทธิ์ดูทีมงานประจำเครน</p>}
      {state.kind === 'error' && (
        <div role="alert">
          <p>{state.message}</p>
          <button type="button" className="button button--secondary" onClick={() => void load()}>
            ลองใหม่อีกครั้ง
          </button>
        </div>
      )}
      {state.kind === 'ready' && state.crew.intervals.length === 0 && <p>ยังไม่มีการมอบหมายทีมงานที่บันทึกไว้</p>}
      {state.kind === 'ready' && state.crew.intervals.length > 0 && (
        <ul className="crew-panel__list">
          {state.crew.intervals.map((i) => (
            <li key={`${i.event_id}:${i.label_date}`} className="crew-panel__item">
              <div>
                <strong>{i.personnel_name ?? i.personnel_id}</strong> · {crewRoleLabel[i.crew_role] ?? i.crew_role}
                {i.crew_role_note_th ? ` (${i.crew_role_note_th})` : ''}
              </div>
              <div>
                {formatE2Date(i.label_date)} {formatE2Span(i.effective_start, i.effective_end, i.label_date)}
              </div>
              <StatusBadge label={resourceStatusLabel[i.status] ?? i.status} tone={resourceStatusTone[i.status]} />
              {canWrite && (
                <div className="crew-panel__actions">
                  <button type="button" className="button button--secondary" onClick={() => setDialog({ operation: 'REVISE', target: i })}>
                    แก้ไข
                  </button>
                  <button type="button" className="button button--secondary" onClick={() => setDialog({ operation: 'CANCEL', target: i })}>
                    ยกเลิก
                  </button>
                  <button type="button" className="button button--secondary" onClick={() => setDialog({ operation: 'EARLY_END', target: i })}>
                    สิ้นสุดก่อนกำหนด
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {notice && (
        <p role={notice.tone === 'ok' ? 'status' : 'alert'} className={notice.tone === 'ok' ? '' : 'form-field__error'}>
          {notice.text}
        </p>
      )}
      {writes.intent && writes.intent.state === 'UNKNOWN' && (
        <button type="button" className="button button--secondary button--full-width" disabled={writes.inFlight}
          onClick={() => void writes.resend().then(report)}>
          ส่งคำขอเดิมอีกครั้ง (ตรวจผลด้วยรหัสคำขอเดิม)
        </button>
      )}
      {writes.intent && writes.intent.state === 'CONFLICT' && (
        <p className="form-field__error" role="alert">
          {describeCrewErrorCode('REQUEST_ID_REUSED')}
        </p>
      )}
      {canWrite && !dialog && (
        <button type="button" className="button button--primary button--full-width" onClick={() => setDialog({ operation: 'CREATE', target: null })}>
          เพิ่มทีมงาน
        </button>
      )}
      {canWrite && dialog && (
        <CrewOperationDialog
          key={`${dialog.operation}:${dialog.target?.event_id ?? 'new'}`}
          operation={dialog.operation}
          target={dialog.target}
          personnel={personnel}
          busy={writes.inFlight}
          onSubmit={(body) => void submit(body)}
          onClose={() => setDialog(null)}
        />
      )}
    </Card>
  )
}
