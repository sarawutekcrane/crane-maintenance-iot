import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useCapabilities } from '../lib/capabilities'
import { CAN_ASSIGN_CRANE_DRIVER } from '../lib/capabilityNames'
import {
  assignmentStates,
  bangkokToday,
  defaultE2Window,
  formatE2Date,
  formatE2Instant,
  formatE2Range,
  formatE2Shift,
  formatE2Span,
  operationPath,
  parseVehicleHistory,
  parseVehicleSchedule,
  validateE2Filter,
  vehicleHistoryPath,
  vehicleSchedulePath,
  type E2AssignmentState,
  type E2Conflict,
  type E2Filter,
  type E2Interval,
  type E2Operation,
  type E2VehicleHistory,
  type E2Warning,
} from '../lib/e2Assignments'
import { useE2Writes } from '../lib/e2Writes'
import {
  describeE2ErrorCode,
  E2_NOTE,
  E2_PANEL_TITLES,
  e2CurrentStatusLabel,
  e2LifecycleLabel,
  e2ModeLabel,
  e2OperationLabel,
  e2RelationLabel,
  e2TimelineStatusLabel,
  e2WarningLabel,
} from '../lib/labels'
import { parseDriverPage, useR2Read, type ReadFailure } from '../lib/r2History'
import { Card } from './Card'
import { E2HistoryTable } from './E2HistoryTable'
import { E2OperationDialog, E2WriteNotice } from './E2OperationDialog'
import { FormField } from './FormField'
import { LoadingState } from './LoadingState'
import { ResponsiveTable } from './ResponsiveTable'
import { R2ReadFailureView } from './TimelineHistoryTable'

/**
 * R2 Batch R2-C2b — the E2 operational driver assignments of ONE vehicle:
 * current status, the schedule in a date / mode window, conflicts, UNKNOWN
 * spans, warnings, the full stored history and — with can_assign_crane_driver
 * — the five operations with all their variants.
 *
 * Three authorities stay separate: this panel reads and writes only E2. It
 * never reads the R2f-f permanent responsible driver (its own panel) or the
 * legacy Phase 6 vehicle-driver page (left unchanged). An assignment is not
 * proof of actual driving. E2 is Mock/TEST only before R11: the backend
 * answers 501 in Google Sheets mode and refuses REAL writes (409).
 */
export function E2VehicleAssignmentsPanel({ vehicleId }: { vehicleId: string }) {
  const { hasCapability, userId } = useCapabilities()
  const canWrite = hasCapability(CAN_ASSIGN_CRANE_DRIVER)
  const writes = useE2Writes(userId, vehicleId)
  const { settle } = writes

  const [draft, setDraft] = useState<E2Filter>(() => ({ ...defaultE2Window(), mode: '' }))
  const [filter, setFilter] = useState<E2Filter>(draft)
  const [filterError, setFilterError] = useState<string | null>(null)

  const [schedule, reloadSchedule] = useR2Read(vehicleSchedulePath(vehicleId, filter), parseVehicleSchedule)
  const onHistory = useCallback((data: E2VehicleHistory) => settle(data), [settle])
  const [history, reloadHistory] = useR2Read(vehicleHistoryPath(vehicleId), parseVehicleHistory, onHistory)
  const [drivers] = useR2Read('/drivers?page_size=200', parseDriverPage)
  const reload = useCallback(() => {
    reloadSchedule()
    reloadHistory()
  }, [reloadSchedule, reloadHistory])

  const [dialog, setDialog] = useState<{ operation: E2Operation; target: E2AssignmentState | null } | null>(null)

  const names = useMemo(() => {
    const map = new Map<string, string>()
    if (drivers.kind === 'ready') for (const d of drivers.data) map.set(d.driver_id, d.driver_name_th)
    return map
  }, [drivers])
  const driverOptions = drivers.kind === 'ready'
    ? drivers.data.map((d) => ({
      id: d.driver_id,
      label: `${d.driver_name_th} (${d.driver_id})${d.active_status === null ? '' : ` — ${d.active_status}`}`,
    }))
    : null

  const states = useMemo(() => (history.kind === 'ready' ? assignmentStates(history.data) : []), [history])

  const applyFilter = () => {
    const error = validateE2Filter(draft)
    setFilterError(error)
    if (error === null) setFilter({ ...draft })
  }

  const open = (operation: E2Operation, target: E2AssignmentState | null) => {
    writes.setMessage(null)
    writes.setDialogError(null)
    setDialog({ operation, target })
  }

  const submit = async (body: Record<string, unknown>) => {
    if (!dialog) return
    const result = await writes.submit(dialog.operation, body, operationPath(vehicleId), reload)
    if (result && result.kind !== 'refused' && result.kind !== 'blocked') setDialog(null)
  }

  const driverLink = (id: string) => (
    <span>
      <Link to={`/drivers/${encodeURIComponent(id)}`}>{id}</Link>
      {names.get(id) ? ` ${names.get(id)}` : ''}
    </span>
  )

  const unavailable = isUnavailable(schedule) || isUnavailable(history)
  const blocked = writes.intent !== null || writes.inFlight
  const data = schedule.kind === 'ready' ? schedule.data : null

  return (
    <Card className="r2-panel e2-panel">
      <h2>{E2_PANEL_TITLES.vehicle}</h2>
      <p className="form-field__hint" data-testid="e2-note">{E2_NOTE}</p>
      <p className="form-field__hint">
        แยกจากผู้รับผิดชอบรถประจำ และแยกจากหน้าคนขับประจำรถแบบเดิม (ข้อมูลไม่ปะปนกัน)
      </p>
      <E2WriteNotice
        message={writes.message}
        intent={writes.intent}
        inFlight={writes.inFlight}
        onResend={() => void writes.resend(reload)}
        onReload={reload}
      />

      {unavailable ? (
        <E2UnavailableView />
      ) : (
        <>
          <E2FilterBar draft={draft} setDraft={setDraft} onApply={applyFilter} error={filterError} idPrefix="e2-vehicle" />

          {schedule.kind === 'loading' && <LoadingState message="กำลังโหลดการมอบหมายผู้ขับตามวัน/กะ..." />}
          {schedule.kind === 'error' && (
            <E2ReadFailureView failure={schedule.failure} title="โหลดการมอบหมายผู้ขับตามวัน/กะไม่สำเร็จ" onRetry={reloadSchedule} />
          )}
          {data && (
            <div data-testid="e2-vehicle-schedule">
              <div className="status-card__row">
                <span>สถานะการมอบหมายขณะนี้</span>
                <span data-testid="e2-current-status">
                  {data.current !== null
                    ? <>{driverLink(data.current.assigned_driver_id)} — {e2ModeLabel[data.current.mode]} {formatE2Date(data.current.label_date)} {formatE2Span(data.current.effective_start, data.current.effective_end, data.current.label_date)}</>
                    : e2CurrentStatusLabel[data.current_status]}
                </span>
              </div>
              {data.timeline_status !== 'VALID' && (
                <p className="form-field__error" role="alert" data-testid="e2-timeline-conflicted">
                  {e2TimelineStatusLabel[data.timeline_status]} — ระบบไม่เดาผู้ขับให้ ต้องแก้ไขโดยผู้มีสิทธิ์
                </p>
              )}
              <E2Warnings warnings={data.warnings} />
              <E2Conflicts conflicts={data.conflicts} />
              {data.unknown.length > 0 && (
                <div className="form-field__error" role="status" data-testid="e2-unknown">
                  <p>{e2CurrentStatusLabel.UNKNOWN} (ไม่มีผู้ขับที่ยืนยันได้ในช่วงนี้):</p>
                  <ul>
                    {data.unknown.map((u) => (
                      <li key={`${u.handover_event_id}-${u.start}`}>
                        {formatE2Range(u.start, u.end)} (การส่งต่อ <code>{u.handover_event_id}</code>)
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <h3>ตารางการมอบหมายในช่วงที่เลือก</h3>
              <E2IntervalTable intervals={data.intervals} renderTarget={(i) => driverLink(i.assigned_driver_id)}
                targetHeader="ผู้ขับที่ได้รับมอบหมาย" emptyTitle="ไม่มีการมอบหมายในช่วงที่เลือก" />
            </div>
          )}

          {history.kind === 'error' && schedule.kind !== 'error' && (
            <E2ReadFailureView failure={history.failure} title="โหลดประวัติการมอบหมายไม่สำเร็จ" onRetry={reloadHistory} />
          )}
          {history.kind === 'ready' && data && (
            <>
              <h3>รายการมอบหมาย</h3>
              {canWrite && !blocked && (
                <div className="dialog__actions" data-testid="e2-actions">
                  <button type="button" className="button button--primary" onClick={() => open('CREATE', null)}>
                    {e2OperationLabel.CREATE}
                  </button>
                </div>
              )}
              <E2AssignmentList states={states} canWrite={canWrite && !blocked} onOpen={open} driverLink={driverLink} />
              <h3>ประวัติการมอบหมายทั้งหมด</h3>
              <E2HistoryTable records={history.data.records} />
            </>
          )}
        </>
      )}

      {dialog && (
        <E2OperationDialog
          operation={dialog.operation}
          target={dialog.target}
          assignments={states}
          driverOptions={driverOptions}
          today={bangkokToday()}
          submitting={writes.inFlight}
          error={writes.dialogError}
          onCancel={() => setDialog(null)}
          onSubmit={(body) => void submit(body)}
        />
      )}
    </Card>
  )
}

/**
 * A failed E2 read: never shown as "no assignment". An id outside the
 * server's data scope gets its own informational E2 state (role="status"); the
 * page's other panels keep their own states and test ids.
 */
export function E2ReadFailureView({ failure, title, onRetry }: { failure: ReadFailure; title: string; onRetry: () => void }) {
  if (failure.kind === 'scope') {
    return (
      <div className="form-field__hint" role="status" data-testid="e2-scope-unproven">
        <p>{describeE2ErrorCode(failure.code ?? undefined)}</p>
        <p className="state-panel__meta">ระบบแสดงเฉพาะข้อมูลในขอบเขตข้อมูลของเซิร์ฟเวอร์ (TEST/REAL) ที่พิสูจน์ได้เท่านั้น</p>
      </div>
    )
  }
  return <R2ReadFailureView failure={failure} title={title} onRetry={onRetry} />
}

function isUnavailable(state: { kind: string; failure?: ReadFailure }): boolean {
  return state.kind === 'error' && state.failure?.status === 501
}

/** Google Sheets mode answers 501 for every E2 route (Mock/TEST only before R11). */
export function E2UnavailableView() {
  return (
    <div className="form-field__hint" role="status" data-testid="e2-unavailable">
      <p>การมอบหมายผู้ขับตามวัน/กะยังไม่พร้อมใช้งานในโหมดข้อมูลนี้</p>
      <p className="state-panel__meta">
        ใช้ได้เฉพาะข้อมูลทดสอบ (Mock/TEST) จนกว่าจะผ่านขั้น R11 จึงไม่มีการแสดงหรือบันทึกการมอบหมายในโหมดนี้
      </p>
    </div>
  )
}

export function E2FilterBar({ draft, setDraft, onApply, error, idPrefix }: {
  draft: E2Filter
  setDraft: (next: E2Filter) => void
  onApply: () => void
  error: string | null
  idPrefix: string
}) {
  return (
    <fieldset className="form-grid form-grid--two-column" data-testid={`${idPrefix}-filter`}>
      <legend>ช่วงวันที่ (เวลาประเทศไทย) และรูปแบบ</legend>
      <FormField label="ตั้งแต่วันที่" htmlFor={`${idPrefix}-from`}>
        <input id={`${idPrefix}-from`} type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
      </FormField>
      <FormField label="ถึงวันที่" htmlFor={`${idPrefix}-to`}>
        <input id={`${idPrefix}-to`} type="date" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
      </FormField>
      <FormField label="รูปแบบ" htmlFor={`${idPrefix}-mode`} error={error ?? undefined}>
        <select id={`${idPrefix}-mode`} value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value as E2Filter['mode'] })}>
          <option value="">ทุกรูปแบบ</option>
          <option value="FULL_DAY">{e2ModeLabel.FULL_DAY}</option>
          <option value="DAY_SHIFT">{e2ModeLabel.DAY_SHIFT}</option>
          <option value="NIGHT_SHIFT">{e2ModeLabel.NIGHT_SHIFT}</option>
        </select>
      </FormField>
      <div className="dialog__actions">
        <button type="button" className="button button--secondary" onClick={onApply}>แสดงตามช่วงที่เลือก</button>
      </div>
    </fieldset>
  )
}

export function E2Warnings({ warnings }: { warnings: readonly E2Warning[] }) {
  if (warnings.length === 0) return null
  return (
    <div className="form-field__hint" role="status" data-testid="e2-warnings">
      <p>ข้อแจ้งเตือน:</p>
      <ul>
        {warnings.map((w, i) => (
          <li key={`${w.code}-${w.event_id ?? ''}-${i}`}>
            {e2WarningLabel[w.code] ?? w.code}
            {w.event_id && <> (<code>{w.event_id}</code>{w.related_event_id && <> ติดกับ <code>{w.related_event_id}</code></>})</>}
            {w.driver_id && <> ผู้ขับ <code>{w.driver_id}</code></>}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function E2Conflicts({ conflicts }: { conflicts: readonly E2Conflict[] }) {
  if (conflicts.length === 0) return null
  return (
    <div className="form-field__error" role="alert" data-testid="e2-conflicts">
      <p>{e2TimelineStatusLabel.CONFLICTED}:</p>
      <ul>
        {conflicts.map((c, i) => (
          <li key={`${c.axis}-${c.first.event_id}-${c.second.event_id}-${i}`}>
            {c.axis === 'VEHICLE' ? 'รถ' : 'ผู้ขับ'} <code>{c.key}</code>: <code>{c.first.event_id}</code> ({c.first.assigned_driver_id},{' '}
            {formatE2Range(c.first.effective_start, c.first.effective_end)}) ทับกับ <code>{c.second.event_id}</code> ({c.second.assigned_driver_id},{' '}
            {formatE2Range(c.second.effective_start, c.second.effective_end)})
          </li>
        ))}
      </ul>
    </div>
  )
}

export function E2IntervalTable({ intervals, renderTarget, targetHeader, emptyTitle }: {
  intervals: readonly E2Interval[]
  renderTarget: (i: E2Interval) => ReactNode
  targetHeader: string
  emptyTitle: string
}) {
  const rows = [...intervals].sort((a, b) => a.effective_start.localeCompare(b.effective_start))
  return (
    <div data-testid="e2-intervals">
      <ResponsiveTable
        columns={[
          { key: 'date', header: 'วันที่ของวัน/กะ', render: (i: E2Interval) => formatE2Date(i.label_date) },
          { key: 'mode', header: 'รูปแบบ', render: (i: E2Interval) => e2ModeLabel[i.mode] ?? i.mode },
          { key: 'span', header: 'ช่วงเวลาที่มีผล', render: (i: E2Interval) => formatE2Span(i.effective_start, i.effective_end, i.label_date) },
          { key: 'target', header: targetHeader, render: renderTarget },
          { key: 'event', header: 'รายการมอบหมาย', render: (i: E2Interval) => <span><code>{i.event_id}</code> <small>ฉบับ {i.revision_no}</small></span> },
        ]}
        rows={rows}
        getRowKey={(i) => `${i.event_id}-${i.label_date}-${i.effective_start}`}
        emptyTitle={emptyTitle}
      />
    </div>
  )
}

function E2AssignmentList({ states, canWrite, onOpen, driverLink }: {
  states: readonly E2AssignmentState[]
  canWrite: boolean
  onOpen: (operation: E2Operation, target: E2AssignmentState) => void
  driverLink: (id: string) => ReactNode
}) {
  return (
    <div data-testid="e2-assignments">
      <ResponsiveTable
        columns={[
          {
            key: 'driver', header: 'ผู้ขับที่ได้รับมอบหมาย',
            render: (a: E2AssignmentState) => (a.state?.assigned_driver_id ? driverLink(a.state.assigned_driver_id) : '-'),
          },
          { key: 'mode', header: 'รูปแบบ', render: (a: E2AssignmentState) => e2ModeLabel[a.state?.mode ?? ''] ?? a.state?.mode ?? '-' },
          {
            key: 'dates', header: 'วันที่',
            render: (a: E2AssignmentState) => (
              <span>
                {formatE2Date(a.state?.start_date ?? null)} – {formatE2Date(a.state?.end_date ?? null)}
                {a.state && formatE2Shift(a.state.shift_start_time, a.state.shift_end_time, a.state.shift_end_day_offset) !== null && (
                  <><br /><small>กะ {formatE2Shift(a.state.shift_start_time, a.state.shift_end_time, a.state.shift_end_day_offset)}</small></>
                )}
                {a.state && a.state.excluded_dates.length > 0 && (
                  <><br /><small>ตัดออก: {a.state.excluded_dates.map(formatE2Date).join(', ')}</small></>
                )}
                {a.state?.early_end_at && <><br /><small>สิ้นสุดก่อนกำหนด: {formatE2Instant(a.state.early_end_at)}</small></>}
              </span>
            ),
          },
          {
            key: 'lifecycle', header: 'สถานะรายการ',
            render: (a: E2AssignmentState) => (
              <span>
                {e2LifecycleLabel[a.event.lifecycle] ?? a.event.lifecycle} <small>(ฉบับ {a.event.revision_no})</small>
                {a.state?.relation && <><br /><small>{e2RelationLabel[a.state.relation] ?? a.state.relation} <code>{a.state.related_event_id}</code></small></>}
              </span>
            ),
          },
          { key: 'event', header: 'รหัสรายการ', render: (a: E2AssignmentState) => <code>{a.event.event_id}</code> },
          {
            key: 'actions', header: 'ดำเนินการ',
            render: (a: E2AssignmentState) =>
              canWrite && a.event.lifecycle === 'ACTIVE' && a.state !== null ? (
                <div className="dialog__actions" data-testid={`e2-row-actions-${a.event.event_id}`}>
                  {(['REVISE', 'SUBSTITUTE', 'CANCEL', 'EARLY_END'] as const).map((op) => (
                    <button key={op} type="button" className="button button--secondary" onClick={() => onOpen(op, a)}>
                      {e2OperationLabel[op]}
                    </button>
                  ))}
                </div>
              ) : '-',
          },
        ]}
        rows={[...states]}
        getRowKey={(a) => a.event.event_id}
        emptyTitle="ยังไม่มีรายการมอบหมายตามวัน/กะ"
        emptyDescription="ยังไม่เคยบันทึกการมอบหมายผู้ขับตามวัน/กะของรถคันนี้"
      />
    </div>
  )
}
