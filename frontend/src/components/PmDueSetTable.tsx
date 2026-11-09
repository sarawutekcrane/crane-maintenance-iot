import { Link } from 'react-router-dom'
import { ResponsiveTable } from './ResponsiveTable'
import { StatusBadge } from './StatusBadge'
import {
  counterTypeLabel,
  formatThaiDateTime,
  pmDueAssemblyLabel,
  pmDueAssignmentSourceLabel,
  pmDueStatusLabel,
  pmDueStatusTone,
  pmDueVehicleStateLabel,
} from '../lib/labels'
import { jobDetailRoute } from '../lib/technicianV2'
import type { PmDueSet, VehiclePmDue } from '../lib/types'

/** A backend number shown as-is (no rounding into a different value, no arithmetic). */
function meter(value: number | null, unit?: string): string {
  if (value === null) return '—'
  const text = value.toLocaleString('th-TH', { maximumFractionDigits: 3 })
  return unit ? `${text} ${unit}` : text
}

function unitOf(set: PmDueSet): string {
  return set.interval_unit
}

const NO_PLANNED_TIME = 'ไม่มีข้อมูลเวลาตามแผน'
const PLANNED_TIME_HINT = 'เวลาที่ทีมใช้ทำงานตามแผน ไม่ใช่ชั่วโมงคน'

/**
 * R4 RT4-C: the server's planned TEAM elapsed minutes of ONE Set, formatted as hours and
 * minutes. Only a whole number of minutes above zero is a value; anything else (null, a
 * field missing from an older response, 0, a negative or fractional number, a non-number)
 * is "no data", never 0 and never rounded. One Set only: nothing is summed or multiplied.
 */
function plannedTeamTime(minutes: unknown): { text: string; minutes: number | null } {
  if (typeof minutes !== 'number' || !Number.isSafeInteger(minutes) || minutes <= 0) {
    return { text: NO_PLANNED_TIME, minutes: null }
  }
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours === 0) return { text: `${minutes} นาที`, minutes }
  const span = rest === 0 ? `${hours} ชม.` : `${hours} ชม. ${rest} นาที`
  return { text: `${span} (${minutes} นาที)`, minutes }
}

/**
 * R4 / TASK-010 Fleet PM Due B1 — the Sets of one vehicle exactly as the backend's
 * PM Due read model gives them. Status, next Due and explanation are the server's;
 * nothing is recalculated, an UNKNOWN is never replaced, and no meter is entered here.
 */
export function PmDueSetTable({ sets }: { sets: PmDueSet[] }) {
  return (
    <ResponsiveTable<PmDueSet>
      rows={sets}
      getRowKey={(set) => `${set.plan_code}|${set.revision_number}|${set.set_key}`}
      emptyTitle="ไม่มีชุดงาน PM ที่ใช้กับรถคันนี้"
      emptyDescription="ดูสถานะแผนด้านบนเพื่อดูเหตุผล"
      columns={[
        {
          key: 'set',
          header: 'ชุดงาน',
          render: (set) => (
            <span>
              {set.set_code} · {set.section}
              <span className="form-field__hint">
                {' '}
                {set.plan_code} ฉบับที่ {set.revision_number}
              </span>
            </span>
          ),
        },
        {
          key: 'meter',
          header: 'มิเตอร์',
          render: (set) => (
            <span>
              {counterTypeLabel[set.meter_type] ?? set.meter_type}
              {set.component_id && <span className="form-field__hint"> {set.component_id}</span>}
            </span>
          ),
        },
        { key: 'interval', header: 'รอบ', render: (set) => meter(set.interval_value, unitOf(set)) },
        {
          key: 'planned',
          header: 'เวลาทีมตามแผน',
          render: (set) => {
            const planned = plannedTeamTime(set.planned_team_minutes)
            return (
              <span
                data-testid="pm-due-planned"
                data-minutes={planned.minutes === null ? undefined : String(planned.minutes)}
              >
                {planned.text}
                <span className="form-field__hint"> {PLANNED_TIME_HINT}</span>
              </span>
            )
          },
        },
        {
          key: 'last',
          header: 'ทำ PM ครั้งล่าสุด (ยืนยันแล้ว)',
          render: (set) =>
            set.last_completed_meter === null ? (
              'ไม่มีหลักฐานที่ยืนยันได้'
            ) : (
              <span data-testid="pm-due-last">
                {meter(set.last_completed_meter, unitOf(set))}
                {set.last_completed_at && (
                  <span className="form-field__hint"> {formatThaiDateTime(set.last_completed_at)}</span>
                )}
                {set.last_completed_pm_work_order_id && (
                  <span className="form-field__hint">
                    {' '}
                    <Link to={jobDetailRoute('PM', set.last_completed_pm_work_order_id)}>
                      {set.last_completed_pm_work_order_id}
                    </Link>
                  </span>
                )}
              </span>
            ),
        },
        {
          key: 'current',
          header: 'ค่าปัจจุบัน (IoT ยืนยันแล้ว)',
          render: (set) =>
            set.current_meter === null ? (
              'ไม่มีค่าที่ยืนยันได้'
            ) : (
              <span>
                {meter(set.current_meter, unitOf(set))}
                {set.current_observed_at && (
                  <span className="form-field__hint"> {formatThaiDateTime(set.current_observed_at)}</span>
                )}
              </span>
            ),
        },
        { key: 'next', header: 'ครบกำหนดที่', render: (set) => meter(set.next_due, unitOf(set)) },
        {
          key: 'status',
          header: 'สถานะ',
          render: (set) => (
            <span data-testid="pm-due-status" data-status={set.status}>
              <StatusBadge
                label={pmDueStatusLabel[set.status] ?? pmDueStatusLabel.UNKNOWN}
                tone={pmDueStatusTone[set.status] ?? 'neutral'}
              />
              <span className="form-field__hint"> {set.explanation}</span>
            </span>
          ),
        },
      ]}
    />
  )
}

/** One vehicle's PM Due: availability, explicit Plan assignments, Plan states and Sets. */
export function VehiclePmDueSummary({ vehicle }: { vehicle: VehiclePmDue }) {
  const notActive = vehicle.state === 'MASTER_NOT_ACTIVE'
  return (
    <div data-testid="pm-due-vehicle" data-state={vehicle.state}>
      <div className="status-card__row">
        <span>สถานะข้อมูลกำหนด PM</span>
        <StatusBadge
          label={pmDueVehicleStateLabel[vehicle.state] ?? vehicle.state}
          tone={vehicle.state === 'AVAILABLE' ? 'info' : 'warning'}
        />
      </div>
      <p className="form-field__hint">{vehicle.explanation}</p>
      {!notActive && vehicle.assignments.length > 0 && (
        <ul>
          {vehicle.assignments.map((a) => (
            <li key={a.assembly}>
              {pmDueAssemblyLabel[a.assembly] ?? a.assembly}: {pmDueAssignmentSourceLabel[a.source] ?? a.source}
              {a.plan_code ? ` — ${a.plan_code}` : ''}
            </li>
          ))}
        </ul>
      )}
      {vehicle.plans.map((plan) => (
        <p key={plan.plan_code} className="form-field__hint" data-testid="pm-due-plan" data-state={plan.state}>
          แผน {plan.plan_code}
          {plan.revision_number !== null ? ` ฉบับที่ ${plan.revision_number}` : ''}: {plan.explanation}
        </p>
      ))}
      {vehicle.sets.length > 0 && <PmDueSetTable sets={vehicle.sets} />}
    </div>
  )
}
