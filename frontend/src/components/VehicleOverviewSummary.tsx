import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiGet, type ApiResult } from '../lib/apiClient'
import { counterTypeLabel, formatThaiDateTime, pmDueVehicleStateLabel } from '../lib/labels'
import type {
  Alert,
  AssetPartLifetime,
  FindingDetail,
  Page,
  RepairSummary,
  VehicleMachineState,
  VehiclePmDue,
} from '../lib/types'
import { Card } from './Card'

/**
 * R8 (R8-03 / R8-04, Owner source approval 2026-11-18) — the vehicle page's
 * summary, composed in the browser from EXISTING authoritative reads only (no
 * backend aggregate, no recalculation of PM or lifetime): meters (the guarded,
 * GPS-free GET /vehicles/{id}/machine-state), PM due, open repairs, finding
 * follow-up, part lifetime and alerts. Each section loads on its own: a failed,
 * refused or truncated read shows "ไม่ทราบ" with a retry and never a zero, and
 * never blocks another section. Certificates are a LINK ONLY — their list read
 * updates expired statuses on read (R7 A-5), so this summary never calls it.
 * Each count links to the page that owns it.
 */

type Section<T> =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'failed' }
  | { kind: 'ready'; data: T }

function sectionOf<T>(result: ApiResult<T>, valid: (data: unknown) => boolean): Section<T> {
  // A response of the wrong shape is never rendered (it is "unknown", not a crash or a zero).
  if (result.ok) return valid(result.data) ? { kind: 'ready', data: result.data } : { kind: 'failed' }
  if (result.error instanceof ApiError && result.error.status === 403) return { kind: 'denied' }
  return { kind: 'failed' }
}

const OPEN_ALERT_STATUSES = new Set(['ACTIVE', 'ACKNOWLEDGED', 'MUTED'])

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const VALID = {
  meters: (v: unknown) => isObject(v) && Array.isArray(v.readings),
  pm: (v: unknown) => isObject(v) && typeof v.state === 'string',
  page: (v: unknown) => isObject(v) && typeof v.total_items === 'number',
  list: (v: unknown) => Array.isArray(v),
  parts: (v: unknown) => isObject(v) && Array.isArray(v.instances) && Array.isArray(v.positions),
}

function useSection<T>(path: string, reloadToken: number, valid: (data: unknown) => boolean): Section<T> {
  // The result is tied to its own request key, so a new path or a retry shows "loading"
  // (derived during render) until its own answer arrives; a late answer is ignored.
  const key = `${path}#${reloadToken}`
  const [loaded, setLoaded] = useState<{ key: string; state: Section<T> } | null>(null)
  useEffect(() => {
    let cancelled = false
    void apiGet<T>(path).then((result) => {
      if (!cancelled) setLoaded({ key, state: sectionOf(result, valid) })
    })
    return () => {
      cancelled = true
    }
  }, [path, key, valid])
  return loaded && loaded.key === key ? loaded.state : { kind: 'loading' }
}

function Unknown({ state }: { state: Section<unknown> }) {
  if (state.kind === 'loading') return <span className="vehicle-overview__muted">กำลังโหลด...</span>
  if (state.kind === 'denied') return <span className="vehicle-overview__muted">ไม่มีสิทธิ์ดูข้อมูลส่วนนี้</span>
  return <span className="vehicle-overview__unknown">ไม่ทราบ (โหลดไม่สำเร็จ)</span>
}

export function VehicleOverviewSummary({ vehicleId }: { vehicleId: string }) {
  const [reloadToken, setReloadToken] = useState(0)
  const id = encodeURIComponent(vehicleId)
  const meters = useSection<VehicleMachineState>(`/vehicles/${id}/machine-state`, reloadToken, VALID.meters)
  const pm = useSection<VehiclePmDue>(`/pm/due/vehicles/${id}`, reloadToken, VALID.pm)
  const repairs = useSection<Page<RepairSummary>>(
    `/repairs?asset_type=VEHICLE&asset_id=${id}&status=OPEN&page_size=1`,
    reloadToken,
    VALID.page,
  )
  const findings = useSection<FindingDetail[]>(
    `/findings/follow-up?asset_type=VEHICLE&asset_id=${id}`,
    reloadToken,
    VALID.list,
  )
  const parts = useSection<AssetPartLifetime>(`/vehicles/${id}/part-lifetime`, reloadToken, VALID.parts)
  const alerts = useSection<Alert[]>(`/vehicles/${id}/alerts`, reloadToken, VALID.list)
  const anyFailed = [meters, pm, repairs, findings, parts, alerts].some((s) => s.kind === 'failed')

  const lifetimeItems =
    parts.kind === 'ready'
      ? [
          ...parts.data.instances,
          ...parts.data.instances.flatMap((i) => i.hosted_positions ?? []),
          ...parts.data.positions,
        ]
      : []
  const lifetimeDue = lifetimeItems.filter((item) => item.rules.some((r) => r.status === 'DUE')).length

  return (
    <Card>
      <h2>สรุปข้อมูลรถ</h2>
      <p className="vehicle-overview__note">
        ข้อมูลแต่ละส่วนอ่านจากหน้าที่เป็นเจ้าของข้อมูลนั้นโดยตรง หากส่วนใดโหลดไม่สำเร็จจะแสดง “ไม่ทราบ” ไม่ใช่ศูนย์
      </p>

      <h3>มาตรวัด</h3>
      {meters.kind === 'ready' ? (
        meters.data.readings.length === 0 ? (
          <p>ยังไม่มีค่ามาตรวัดที่ระบบทราบ</p>
        ) : (
          <ul className="vehicle-overview__list">
            {meters.data.readings.map((r) => (
              <li key={`${r.component_id ?? '-'}:${r.counter_type}`}>
                {counterTypeLabel[r.counter_type] ?? r.counter_type}
                {r.component_id ? ` (${r.component_id})` : ''}:{' '}
                {r.value === null ? (
                  <span className="vehicle-overview__unknown">ไม่ทราบ</span>
                ) : (
                  <strong>{r.value.toLocaleString('th-TH')}</strong>
                )}{' '}
                <span className="vehicle-overview__muted">
                  {r.observed_at ? `อัปเดต ${formatThaiDateTime(r.observed_at)}` : 'ไม่ทราบเวลาอัปเดต'}
                </span>
              </li>
            ))}
          </ul>
        )
      ) : (
        <p>
          <Unknown state={meters} />
        </p>
      )}
      <p className="vehicle-overview__muted">ค่าล่าสุดที่ระบบทราบ ไม่ใช่ค่าแบบเรียลไทม์</p>

      <dl className="vehicle-overview__grid">
        <dt>กำหนด PM</dt>
        <dd>
          {pm.kind === 'ready' ? (
            <Link to={`/vehicle/${vehicleId}/pm/due`}>{pmDueVehicleStateLabel[pm.data.state] ?? pm.data.state}</Link>
          ) : (
            <Unknown state={pm} />
          )}
        </dd>
        <dt>งานซ่อมที่เปิด</dt>
        <dd>
          {repairs.kind === 'ready' ? (
            <Link to={`/vehicle/${vehicleId}/repairs`}>{`${repairs.data.total_items} งาน`}</Link>
          ) : (
            <Unknown state={repairs} />
          )}
        </dd>
        <dt>รายการผิดปกติที่ติดตามอยู่</dt>
        <dd>
          {findings.kind === 'ready' ? (
            <Link to={`/vehicle/${vehicleId}/inspections`}>{`${findings.data.length} รายการ`}</Link>
          ) : (
            <Unknown state={findings} />
          )}
        </dd>
        <dt>อะไหล่ที่ติดตามอายุ</dt>
        <dd>
          {parts.kind === 'ready' ? (
            <Link to={`/vehicle/${vehicleId}/parts`}>
              {`${lifetimeItems.length} รายการ · ถึงกำหนด ${lifetimeDue} รายการ`}
            </Link>
          ) : (
            <Unknown state={parts} />
          )}
        </dd>
        <dt>การแจ้งเตือนที่ยังเปิด</dt>
        <dd>
          {alerts.kind === 'ready' ? (
            <Link to={`/vehicle/${vehicleId}/alerts`}>
              {`${alerts.data.filter((a) => a.alert_status !== null && OPEN_ALERT_STATUSES.has(a.alert_status)).length} รายการ`}
            </Link>
          ) : (
            <Unknown state={alerts} />
          )}
        </dd>
        <dt>ใบรับรอง</dt>
        <dd>
          <Link to={`/vehicle/${vehicleId}/certificates`}>ดูใบรับรอง</Link>{' '}
          <span className="vehicle-overview__muted">(เปิดดูในหน้าใบรับรอง)</span>
        </dd>
        <dt>สถานะอุปกรณ์ IoT</dt>
        <dd>
          <span className="vehicle-overview__muted">รอเชื่อมต่ออุปกรณ์ (Phase 8) — ยังไม่ใช่สถานะออนไลน์/ออฟไลน์</span>
        </dd>
      </dl>
      {anyFailed && (
        <button
          type="button"
          className="button button--secondary button--full-width"
          onClick={() => setReloadToken((t) => t + 1)}
        >
          ลองโหลดสรุปข้อมูลอีกครั้ง
        </button>
      )}
    </Card>
  )
}
