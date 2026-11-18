import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { isLinkableVehicleId } from '../lib/certificateReportLinks'
import { bangkokToday, formatE2Date, formatE2Span } from '../lib/e2Assignments'
import {
  calendarViewLabel,
  crewRoleLabel,
  describeCrewErrorCode,
  resourceStatusLabel,
  resourceStatusTone,
} from '../lib/labels'
import {
  CALENDAR_SCALES,
  CALENDAR_VIEWS,
  calendarWindow,
  entriesByDay,
  groupEntries,
  moveAnchor,
  readCalendarParams,
  type CalendarScale,
} from '../lib/resourceCalendar'
import type { CalendarEntry, CalendarView, ResourceCalendar } from '../lib/types'

/**
 * R8 early workstream — "ปฏิทินทรัพยากร" (Owner addendum 2026-11-11; OD-7 = A).
 * Calendar-first view of who is ASSIGNED where and when: switch VEHICLES /
 * PERSONNEL / BOTH, move by month / week / day, and click a day to see each
 * person, their own start–end (Asia/Bangkok), vehicle, role and status. Drivers
 * come from E2, crew from the crew assignments. An empty day means no recorded
 * assignment — never a verified free person. "Assigned" is not attendance.
 * Reading needs a trusted actor holding can_assign_crane_driver or
 * can_assign_crane_crew (the backend enforces it).
 */

const SCALE_LABEL: Record<CalendarScale, string> = { MONTH: 'เดือน', WEEK: 'สัปดาห์', DAY: 'วัน' }
const WEEKDAYS = ['อา.', 'จ.', 'อ.', 'พ.', 'พฤ.', 'ศ.', 'ส.']

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; calendar: ResourceCalendar }

function calendarErrorState(err: ApiError | Error): LoadState {
  if (err instanceof ApiError && err.status === 403) return { kind: 'denied' }
  return {
    kind: 'error',
    message: describeCrewErrorCode(err instanceof ApiError ? err.code : undefined),
    requestId: err instanceof ApiError ? err.requestId : null,
  }
}

function entryTitle(entry: CalendarEntry): string {
  if (entry.kind === 'UNKNOWN') return 'ไม่ทราบผู้ได้รับมอบหมาย (ช่วงหลังการส่งมอบที่แก้ไขย้อนหลัง)'
  const who = entry.personnel_name ?? entry.driver_name ?? entry.personnel_id ?? entry.driver_id ?? '-'
  const role = crewRoleLabel[entry.role ?? ''] ?? entry.role ?? ''
  const note = entry.role_note_th ? ` (${entry.role_note_th})` : ''
  return `${who} · ${role}${note}`
}

export function CalendarEntryRow({ entry }: { entry: CalendarEntry }) {
  return (
    <li className="calendar-entry">
      <div className="calendar-entry__who">{entryTitle(entry)}</div>
      <div className="calendar-entry__when">{formatE2Span(entry.effective_start, entry.effective_end, entry.label_date)}</div>
      <div className="calendar-entry__where">
        รถ:{' '}
        {isLinkableVehicleId(entry.vehicle_id) ? (
          <Link to={`/vehicle/${entry.vehicle_id}`}>{entry.machine_no ?? entry.vehicle_id}</Link>
        ) : (
          entry.vehicle_id
        )}
      </div>
      <StatusBadge label={resourceStatusLabel[entry.status] ?? entry.status} tone={resourceStatusTone[entry.status]} />
    </li>
  )
}

export function ResourceCalendarPage() {
  const today = bangkokToday()
  const [params, setParams] = useSearchParams()
  const { scale, view, anchor } = readCalendarParams(params, today)
  const range = calendarWindow(scale, anchor)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [picked, setSelected] = useState<string | null>(null)
  // The DAY scale always shows its own day; otherwise the day the user clicked.
  const selected = scale === 'DAY' ? anchor : picked
  const generation = useRef(0)

  const update = (next: Partial<{ scale: CalendarScale; view: CalendarView; anchor: string }>) => {
    const merged = { scale, view, anchor, ...next }
    setState({ kind: 'loading' })
    setParams({ scale: merged.scale, view: merged.view, date: merged.anchor })
  }

  const load = useCallback(async (from: string, to: string, v: CalendarView) => {
    const current = ++generation.current
    const result = await apiGet<ResourceCalendar>(`/resource-calendar?from=${from}&to=${to}&view=${v}`)
    if (current !== generation.current) return
    setState(result.ok ? { kind: 'ready', calendar: result.data } : calendarErrorState(result.error))
  }, [])

  useEffect(() => {
    void load(range.from, range.to, view)
  }, [load, range.from, range.to, view])

  const byDay = state.kind === 'ready' ? entriesByDay(state.calendar.entries) : new Map<string, CalendarEntry[]>()
  const selectedEntries = selected ? byDay.get(selected) ?? [] : []

  return (
    <section className="page">
      <h1>ปฏิทินทรัพยากร</h1>
      <p>ดูการมอบหมายคนขับและทีมงานประจำเครนตามวัน (เวลาประเทศไทย) แตะวันเพื่อดูรายละเอียดของแต่ละคน</p>

      <Card>
        <div className="calendar-toolbar">
          <div className="calendar-toolbar__group" role="group" aria-label="มุมมอง">
            {CALENDAR_VIEWS.map((v) => (
              <button key={v} type="button" aria-pressed={v === view}
                className={`button ${v === view ? 'button--primary' : 'button--secondary'}`}
                onClick={() => update({ view: v })}>
                {calendarViewLabel[v]}
              </button>
            ))}
          </div>
          <div className="calendar-toolbar__group" role="group" aria-label="ช่วงเวลา">
            {CALENDAR_SCALES.map((s) => (
              <button key={s} type="button" aria-pressed={s === scale}
                className={`button ${s === scale ? 'button--primary' : 'button--secondary'}`}
                onClick={() => update({ scale: s })}>
                {SCALE_LABEL[s]}
              </button>
            ))}
          </div>
          <div className="calendar-toolbar__group">
            <button type="button" className="button button--secondary" onClick={() => update({ anchor: moveAnchor(scale, anchor, -1) })}>
              ก่อนหน้า
            </button>
            <button type="button" className="button button--secondary" onClick={() => update({ anchor: today })}>
              วันนี้
            </button>
            <button type="button" className="button button--secondary" onClick={() => update({ anchor: moveAnchor(scale, anchor, 1) })}>
              ถัดไป
            </button>
          </div>
        </div>
        <p className="calendar-toolbar__range" aria-live="polite">
          {formatE2Date(range.from)} – {formatE2Date(range.to)} · {calendarViewLabel[view]}
        </p>
      </Card>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดปฏิทิน..." />}
      {state.kind === 'denied' && <PermissionDeniedState />}
      {state.kind === 'error' && (
        <ErrorState title="โหลดปฏิทินไม่สำเร็จ" message={state.message} requestId={state.requestId}
          onRetry={() => void load(range.from, range.to, view)} />
      )}
      {state.kind === 'ready' && (
        <>
          {scale !== 'DAY' && (
            <div className={`calendar-grid calendar-grid--${scale.toLowerCase()}`}>
              {WEEKDAYS.map((d) => (
                <div key={d} className="calendar-grid__weekday" aria-hidden="true">
                  {d}
                </div>
              ))}
              {range.days.map((day) => {
                const entries = byDay.get(day) ?? []
                const drivers = entries.filter((e) => e.kind === 'DRIVER').length
                const crew = entries.filter((e) => e.kind === 'CREW').length
                const flagged = entries.some((e) => e.status !== 'VALID')
                const outside = scale === 'MONTH' && day.slice(0, 7) !== anchor.slice(0, 7)
                return (
                  <button key={day} type="button"
                    className={`calendar-day${day === selected ? ' calendar-day--selected' : ''}${outside ? ' calendar-day--outside' : ''}${day === today ? ' calendar-day--today' : ''}`}
                    aria-label={`${formatE2Date(day)}: คนขับ ${drivers} ทีมงาน ${crew}${flagged ? ' มีรายการที่ต้องตรวจสอบ' : ''}`}
                    aria-pressed={day === selected}
                    onClick={() => setSelected(day)}>
                    <span className="calendar-day__date">{Number(day.slice(8, 10))}</span>
                    {drivers > 0 && <span className="calendar-day__count">คนขับ {drivers}</span>}
                    {crew > 0 && <span className="calendar-day__count">ทีม {crew}</span>}
                    {flagged && <span className="calendar-day__flag">ตรวจสอบ</span>}
                  </button>
                )
              })}
            </div>
          )}
          <Card>
            <h2>{selected ? `รายละเอียด ${formatE2Date(selected)}` : 'แตะวันในปฏิทินเพื่อดูรายละเอียด'}</h2>
            {selected && selectedEntries.length === 0 && (
              <p>ไม่มีการมอบหมายที่บันทึกไว้ในวันนี้ (ไม่ได้ยืนยันว่าบุคคลว่าง)</p>
            )}
            {selected &&
              groupEntries(selectedEntries, view).map((group) => (
                <section key={group.key} className="calendar-group">
                  <h3>{group.label}</h3>
                  <ul className="calendar-group__list">
                    {group.entries.map((entry) => (
                      <CalendarEntryRow key={`${entry.kind}:${entry.event_id}:${entry.effective_start}`} entry={entry} />
                    ))}
                  </ul>
                </section>
              ))}
          </Card>
          <p className="vehicle-overview__muted">
            แสดงการ “มอบหมาย” เท่านั้น ไม่ใช่การยืนยันการมาทำงาน การขับจริง หรือการจองงานลูกค้า
          </p>
        </>
      )}
    </section>
  )
}
