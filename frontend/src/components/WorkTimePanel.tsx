import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiGet, apiPostWithRequestId, type ApiResult } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { describeErrorCode } from '../lib/labels'
import { newRequestId } from '../lib/registryPending'
import type { WorkKind } from '../lib/technicianV2'
import type { JobWorkTimeResponse, WorkTimeEntry, WorkTimeEntryView } from '../lib/types'
import { Card } from './Card'
import { WorkTimeEntryDialog, type WorkTimeEntryInput } from './WorkTimeEntryDialog'

interface WorkTimePanelProps {
  kind: WorkKind
  jobId: string
  jobStatus: string
  /** The job's manager authority (Repair / Finding round / PM), from the server capabilities. */
  canConfirm: boolean
  onChanged?: () => void
}

const R5_MESSAGES: Record<string, string> = {
  WORK_TIME_OVERLAP: 'ช่างคนนี้มีเวลาทำงานที่บันทึกไว้ในช่วงเวลาเดียวกันแล้ว (อาจเป็นใบงานอื่น) จึงบันทึกซ้อนไม่ได้',
  WORK_TIME_NOT_MEMBER: 'คุณไม่ได้อยู่ (และไม่เคยอยู่) ในทีมช่างของใบงานนี้',
  WORK_TIME_ACTOR_NOT_TECHNICIAN: 'บัญชีของคุณไม่ได้เชื่อมกับข้อมูลช่าง จึงบันทึกเวลาทำงานไม่ได้',
  WORK_TIME_ON_BEHALF_REFUSED: 'ช่างต้องบันทึกเวลาทำงานของตนเองเท่านั้น',
  WORK_TIME_SELF_CONFIRMATION_REFUSED: 'ผู้จัดการไม่สามารถยืนยันเวลาทำงานของตนเองได้',
  WORK_TIME_CONFIRMATION_FORBIDDEN: 'คุณไม่มีสิทธิ์ยืนยันเวลาทำงานของใบงานนี้',
  WORK_TIME_CORRECTION_FORBIDDEN: 'คุณไม่มีสิทธิ์แก้ไขรายการนี้',
  WORK_TIME_REVISION_STALE: 'รายการถูกแก้ไขไปแล้ว กรุณาโหลดข้อมูลใหม่',
  WORK_TIME_WINDOW_CLOSED: 'สถานะใบงานไม่เปิดให้บันทึกเวลาทำงาน',
  WORK_TIME_BREAKS_REQUIRED: 'กรุณาเลือกว่ามีช่วงพักหรือไม่',
  WORK_TIME_BREAK_INVALID: 'ช่วงพักไม่ถูกต้อง (ต้องอยู่ภายในช่วงทำงานและไม่ซ้อนกัน)',
  WORK_TIME_INVALID_INTERVAL: 'ช่วงเวลาไม่ถูกต้อง (เวลาสิ้นสุดต้องหลังเวลาเริ่ม และไม่เป็นเวลาในอนาคต)',
  WORK_TIME_REASON_REQUIRED: 'การแก้ไขต้องระบุเหตุผล',
  WORK_TIME_REQUEST_CONFLICT: 'คำขอนี้ถูกใช้กับข้อมูลอื่นไปแล้ว กรุณาโหลดใหม่แล้วลองอีกครั้ง',
}

const UNKNOWN_OUTCOME = 'ไม่ทราบผลการบันทึก (การเชื่อมต่อขัดข้อง) กรุณากดบันทึกอีกครั้ง ระบบจะไม่บันทึกซ้ำ'

function errorText(err: ApiError | Error): string {
  if (err instanceof ApiError) return R5_MESSAGES[err.code] ?? describeErrorCode(err.code)
  return UNKNOWN_OUTCOME
}

function hours(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return m ? `${h} ชม. ${m} นาที` : `${h} ชม.`
}

function elapsed(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${d} วัน ${h} ชม. ${m} นาที`
}

function bangkok(iso: string): string {
  return new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Bangkok' }).format(
    new Date(iso),
  )
}

function netSeconds(entry: WorkTimeEntry): number {
  const span = (Date.parse(entry.ended_at) - Date.parse(entry.started_at)) / 1000
  return span - entry.breaks.reduce((sum, b) => sum + (Date.parse(b.ended_at) - Date.parse(b.started_at)) / 1000, 0)
}

/** Fail closed on an unexpected body: never render a partial or coerced work-time state. */
function isWorkTimeResponse(value: unknown): value is JobWorkTimeResponse {
  const v = value as Partial<JobWorkTimeResponse> | null
  return Boolean(v && Array.isArray(v.entries) && v.team && typeof v.team.total_seconds === 'number' && v.technicians)
}

function technicianWindowOpen(kind: WorkKind, status: string): boolean {
  return kind === 'REPAIR' ? status === 'OPEN' : status === 'IN_PROGRESS' || status === 'PENDING_REVIEW'
}

type DialogState = { mode: 'CREATE' } | { mode: 'CORRECT'; entry: WorkTimeEntry } | null

/**
 * R5 — technician work time of one Repair or PM Work Order (RM-6..RM-12, OD-2, OD-4,
 * AMB-2). A technician records their OWN periods (the server resolves who they are);
 * a manager confirms each entry's current revision and may correct with a reason,
 * also after CLOSE. Man-hours (Σ net work per person) and the Work Order's elapsed
 * time are shown separately and never combined; nothing is ever calculated as an
 * 8-hour day. Every write keeps its request id until a definite answer.
 */
export function WorkTimePanel({ kind, jobId, jobStatus, canConfirm, onChanged }: WorkTimePanelProps) {
  const { userId } = useCapabilities()
  const base = kind === 'REPAIR' ? `/repairs/${jobId}` : `/pm/work-orders/${jobId}`
  const [data, setData] = useState<JobWorkTimeResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [dialog, setDialog] = useState<DialogState>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const intent = useRef<{ key: string; id: string } | null>(null)

  const apply = useCallback((result: ApiResult<JobWorkTimeResponse>) => {
    if (result.ok && isWorkTimeResponse(result.data)) {
      setData(result.data)
      setLoadError(null)
    } else if (result.ok) {
      setLoadError('ข้อมูลเวลาทำงานที่ได้รับไม่ถูกต้อง จึงไม่แสดงผล')
    } else {
      setLoadError(result.error instanceof ApiError ? describeErrorCode(result.error.code) : 'โหลดข้อมูลเวลาทำงานไม่สำเร็จ')
    }
  }, [])

  const load = useCallback(async () => apply(await apiGet<JobWorkTimeResponse>(`${base}/work-time`)), [base, apply])

  useEffect(() => {
    let cancelled = false
    void apiGet<JobWorkTimeResponse>(`${base}/work-time`).then((result) => {
      if (!cancelled) apply(result)
    })
    return () => {
      cancelled = true
    }
  }, [base, apply])

  /** One request id per user intent; a transport failure keeps it for the explicit re-send. */
  const send = useCallback(
    async (key: string, path: string, body: unknown): Promise<boolean> => {
      if (intent.current?.key !== key) intent.current = { key, id: newRequestId() }
      setBusy(true)
      setMessage(null)
      const result = await apiPostWithRequestId<JobWorkTimeResponse>(path, body, intent.current.id)
      setBusy(false)
      if (result.ok) {
        intent.current = null
        if (isWorkTimeResponse(result.data)) setData(result.data)
        else void load()
        onChanged?.()
        return true
      }
      if (result.error instanceof ApiError) intent.current = null
      setMessage(errorText(result.error))
      return false
    },
    [onChanged, load],
  )

  const submitDialog = async (input: WorkTimeEntryInput) => {
    if (!dialog) return
    const { reason, ...values } = input
    const ok =
      dialog.mode === 'CREATE'
        ? await send(`create:${JSON.stringify(values)}`, `${base}/work-time`, values)
        : await send(`correct:${dialog.entry.entry_id}:${JSON.stringify(input)}`, `${base}/work-time/${dialog.entry.entry_id}/revisions`, {
            action: 'CORRECT',
            expected_revision: dialog.entry.revision,
            reason,
            ...values,
          })
    if (ok) setDialog(null)
  }

  const voidEntry = async (entry: WorkTimeEntry) => {
    const reason = window.prompt('เหตุผลการยกเลิกรายการนี้')
    if (!reason || !reason.trim()) return
    await send(`void:${entry.entry_id}:${entry.revision}:${reason.trim()}`, `${base}/work-time/${entry.entry_id}/revisions`, {
      action: 'VOID',
      expected_revision: entry.revision,
      reason: reason.trim(),
    })
  }

  const confirmEntries = async (views: WorkTimeEntryView[]) => {
    const entries = views.map((v) => ({ entry_id: v.entry.entry_id, revision: v.entry.revision }))
    await send(`confirm:${JSON.stringify(entries)}`, `${base}/work-time/confirmations`, { entries })
  }

  /** A manager never confirms their own technician time; the first revision's author is the technician. */
  const isOwn = (view: WorkTimeEntryView) => (view.revisions[0]?.recorded_by ?? view.entry.recorded_by) === userId
  const canRecord = technicianWindowOpen(kind, jobStatus)
  const closed = jobStatus === 'CLOSED'
  const pending = data ? data.entries.filter((v) => !v.confirmed) : []
  const confirmable = pending.filter((v) => !isOwn(v))

  return (
    <Card>
      <h2>เวลาทำงานของช่าง</h2>
      {loadError && <p className="form-field__error">{loadError}</p>}
      {data && (
        <>
          <div className="status-card__row">
            <span>รวมชั่วโมงคนของทีม (ทำงานจริง)</span>
            <span data-testid="wt-team-total">
              {hours(data.team.total_seconds)} (ปกติ {hours(data.team.regular_seconds)} / ล่วงเวลา {hours(data.team.overtime_seconds)})
            </span>
          </div>
          <div className="status-card__row">
            <span>ระยะเวลาใบงานทั้งหมด (ไม่ใช่ชั่วโมงคน)</span>
            <span data-testid="wt-elapsed">{elapsed(data.elapsed_seconds)}</span>
          </div>
          {data.unconfirmed_count > 0 && (
            <p className="form-field__hint" data-testid="wt-unconfirmed">
              มีเวลาทำงาน {data.unconfirmed_count} รายการที่ยังไม่ได้รับการยืนยัน
              {closed ? ' (แก้ไขหลังปิดงาน — ใบงานยังคงปิดอยู่)' : ' — ต้องยืนยันทุกรายการก่อนปิดงาน'}
            </p>
          )}
          <table className="responsive-table" data-testid="wt-technicians">
            <thead>
              <tr>
                <th>ช่าง</th>
                <th>เวลาปกติ</th>
                <th>ล่วงเวลา</th>
                <th>รวม</th>
                <th>จำนวนวันที่ทำงานจริง</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.technicians).map(([technicianId, totals]) => (
                <tr key={technicianId}>
                  <td data-label="ช่าง">
                    <Link to={`/work-time/assignees/${technicianId}`}>{technicianId}</Link>
                  </td>
                  <td data-label="เวลาปกติ">{hours(totals.regular_seconds)}</td>
                  <td data-label="ล่วงเวลา">{hours(totals.overtime_seconds)}</td>
                  <td data-label="รวม">{hours(totals.total_seconds)}</td>
                  <td data-label="จำนวนวันที่ทำงานจริง">{totals.workdays.length} วัน</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.entries.length === 0 && <p>ยังไม่มีการบันทึกเวลาทำงาน</p>}
          <ul className="work-time-entries">
            {data.entries.map((view) => {
              const { entry } = view
              return (
                <li key={entry.entry_id} data-testid="wt-entry">
                  <div className="status-card__row">
                    <span>
                      {entry.technician_id} · {bangkok(entry.started_at)} – {bangkok(entry.ended_at)}
                    </span>
                    <span data-testid="wt-entry-class">{entry.time_class === 'OVERTIME' ? 'ล่วงเวลา (OT)' : 'เวลาปกติ'}</span>
                  </div>
                  {entry.record_kind === 'VOID' ? (
                    <p>รายการนี้ถูกยกเลิก (เหตุผล: {entry.reason})</p>
                  ) : (
                    <p>
                      {entry.description} · ทำงานสุทธิ {hours(netSeconds(entry))}
                      {entry.breaks.length === 0
                        ? ' · ไม่มีพัก'
                        : ` · พัก ${entry.breaks.map((b) => `${bangkok(b.started_at)}–${bangkok(b.ended_at)}`).join(', ')}`}
                    </p>
                  )}
                  <p className="form-field__hint">
                    {view.confirmed ? 'ยืนยันแล้ว' : 'รอผู้จัดการยืนยัน'} · ฉบับที่ {entry.revision}
                  </p>
                  {entry.record_kind !== 'VOID' && (
                    <div className="status-card__actions">
                      {((canRecord && isOwn(view)) || canConfirm) && (
                        <button type="button" className="button button--secondary" disabled={busy} onClick={() => setDialog({ mode: 'CORRECT', entry })}>
                          แก้ไข
                        </button>
                      )}
                      {((canRecord && isOwn(view)) || canConfirm) && (
                        <button type="button" className="button button--secondary" disabled={busy} onClick={() => void voidEntry(entry)}>
                          ยกเลิกรายการ
                        </button>
                      )}
                    </div>
                  )}
                  {canConfirm && !view.confirmed && !isOwn(view) && (
                    <button type="button" className="button button--primary" disabled={busy} onClick={() => void confirmEntries([view])}>
                      ยืนยันเวลานี้
                    </button>
                  )}
                  {view.revisions.length > 1 && (
                    <details>
                      <summary>ประวัติการแก้ไข ({view.revisions.length} ฉบับ)</summary>
                      <ul>
                        {view.revisions.map((r) => (
                          <li key={r.revision}>
                            ฉบับที่ {r.revision}: {bangkok(r.started_at)} – {bangkok(r.ended_at)} ·{' '}
                            {r.time_class === 'OVERTIME' ? 'ล่วงเวลา' : 'ปกติ'} · โดย {r.recorded_by} เมื่อ {bangkok(r.recorded_at)}
                            {r.reason ? ` · เหตุผล: ${r.reason}` : ''}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
      {message && !dialog && (
        <p className="form-field__error" role="alert">
          {message}
        </p>
      )}
      <div className="status-card__actions">
        {canRecord && (
          <button type="button" className="button button--primary" disabled={busy} onClick={() => setDialog({ mode: 'CREATE' })}>
            บันทึกเวลาทำงานของฉัน
          </button>
        )}
        {canConfirm && confirmable.length > 1 && (
          <button type="button" className="button button--secondary" disabled={busy} onClick={() => void confirmEntries(confirmable)}>
            ยืนยันทุกรายการที่รอ ({confirmable.length})
          </button>
        )}
      </div>
      {dialog && (
        <WorkTimeEntryDialog
          open
          key={dialog.mode === 'CORRECT' ? `${dialog.entry.entry_id}@${dialog.entry.revision}` : 'create'}
          mode={dialog.mode}
          entry={dialog.mode === 'CORRECT' ? dialog.entry : null}
          submitting={busy}
          error={message}
          onCancel={() => setDialog(null)}
          onSubmit={(input) => void submitDialog(input)}
        />
      )}
    </Card>
  )
}
