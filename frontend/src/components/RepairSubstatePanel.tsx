import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, apiGet, apiPostWithRequestId, type ApiResult } from '../lib/apiClient'
import { describeErrorCode } from '../lib/labels'
import { newRequestId } from '../lib/registryPending'
import type { Repair, RepairSubstate, RepairSubstatePeriod, RepairSubstatesResponse } from '../lib/types'
import { Card } from './Card'
import { FormField } from './FormField'

interface RepairSubstatePanelProps {
  repair: Repair
  /** Derived Store indicator (open material request) — a different concept, shown separately. */
  awaitingPartsFlag: boolean
  onChanged?: () => void
}

const SUBSTATE_LABEL: Record<RepairSubstate, string> = { REPAIRING: 'กำลังซ่อม', AWAITING_PARTS: 'รออะไหล่' }
const MESSAGES: Record<string, string> = {
  REPAIR_SUBSTATE_CONFLICT: 'ช่วงเวลานี้ซ้อนกับช่วงสถานะที่บันทึกไว้แล้ว',
  REPAIR_SUBSTATE_WINDOW_CLOSED: 'สถานะใบงานไม่เปิดให้บันทึกสถานะย่อย (ส่งงานแล้วเฉพาะผู้จัดการ หรือปิดงานแล้ว)',
  REPAIR_SUBSTATE_INVALID_INTERVAL: 'ช่วงเวลาไม่ถูกต้อง (ต้องหลังเวลาเปิดใบงาน และไม่เป็นเวลาในอนาคต)',
  WORK_TIME_REVISION_STALE: 'รายการถูกแก้ไขไปแล้ว กรุณาโหลดข้อมูลใหม่',
  WORK_TIME_REASON_REQUIRED: 'การแก้ไขต้องระบุเหตุผล',
}
const UNKNOWN_OUTCOME = 'ไม่ทราบผลการบันทึก (การเชื่อมต่อขัดข้อง) กรุณากดอีกครั้ง ระบบจะไม่บันทึกซ้ำ'

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

function toInstant(local: string): string {
  return `${local}:00+07:00`
}

/** "Now" in whole seconds, a moment in the past so that a slightly fast client clock is never "future". */
function nowInstant(): string {
  const now = new Date(Date.now() - 2000)
  now.setMilliseconds(0)
  return now.toISOString().replace('.000Z', 'Z')
}

/** Fail closed on an unexpected body: never render a partial or coerced substate state. */
function isSubstatesResponse(value: unknown): value is RepairSubstatesResponse {
  const v = value as Partial<RepairSubstatesResponse> | null
  return Boolean(v && Array.isArray(v.periods) && v.durations && typeof v.durations.elapsed_seconds === 'number')
}

/**
 * R5 — Repair substates กำลังซ่อม / รออะไหล่ (RM-2..RM-5, RM-12): recorded periods
 * under an OPEN repair (never a new repair status). Effective time is what the user
 * enters (or "now"); the server records its own time. Durations are elapsed 24-hour
 * days including nights and holidays; the remainder of the Work Order elapsed time is
 * shown as "อื่น ๆ" and never assumed to be zero. Waiting for parts creates no labor.
 */
export function RepairSubstatePanel({ repair, awaitingPartsFlag, onChanged }: RepairSubstatePanelProps) {
  const [data, setData] = useState<RepairSubstatesResponse | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [retro, setRetro] = useState({ substate: 'REPAIRING' as RepairSubstate, start: '', end: '' })
  // One request id AND body per user intent: an explicit resend after an unknown outcome repeats the
  // identical request (a "now" action keeps its original effective time), so it can only replay.
  const intent = useRef<{ key: string; id: string; body: unknown } | null>(null)
  const path = `/repairs/${repair.repair_id}/substates`

  const apply = useCallback((result: ApiResult<RepairSubstatesResponse>) => {
    if (result.ok && isSubstatesResponse(result.data)) setData(result.data)
    else if (result.ok) setMessage('ข้อมูลสถานะย่อยที่ได้รับไม่ถูกต้อง จึงไม่แสดงผล')
  }, [])

  const load = useCallback(async () => apply(await apiGet<RepairSubstatesResponse>(path)), [path, apply])

  useEffect(() => {
    let cancelled = false
    void apiGet<RepairSubstatesResponse>(path).then((result) => {
      if (!cancelled) apply(result)
    })
    return () => {
      cancelled = true
    }
  }, [path, apply])

  const send = async (key: string, target: string, makeBody: () => unknown) => {
    if (intent.current?.key !== key) intent.current = { key, id: newRequestId(), body: makeBody() }
    setBusy(true)
    setMessage(null)
    const result = await apiPostWithRequestId<RepairSubstatesResponse>(target, intent.current.body, intent.current.id)
    setBusy(false)
    if (result.ok) {
      intent.current = null
      if (isSubstatesResponse(result.data)) setData(result.data)
      else void load()
      onChanged?.()
      return true
    }
    if (result.error instanceof ApiError) {
      intent.current = null
      setMessage(MESSAGES[result.error.code] ?? describeErrorCode(result.error.code))
    } else {
      setMessage(UNKNOWN_OUTCOME)
    }
    return false
  }

  const switchTo = (substate: RepairSubstate) => {
    // started_at omitted = the server's own "now" (never the client clock); a resend repeats the same body.
    void send(`now:${substate}`, path, () => ({ substate, close_ongoing: true }))
  }

  const recordRetro = async () => {
    if (!retro.start) return setMessage('กรุณาระบุเวลาเริ่ม')
    const body = {
      substate: retro.substate,
      started_at: toInstant(retro.start),
      ended_at: retro.end ? toInstant(retro.end) : null,
    }
    if (await send(`retro:${JSON.stringify(body)}`, path, () => body)) setRetro({ substate: 'REPAIRING', start: '', end: '' })
  }

  const revise = (period: RepairSubstatePeriod, action: 'VOID' | 'CLOSE') => {
    const reason = window.prompt(action === 'VOID' ? 'เหตุผลการยกเลิกช่วงนี้' : 'เหตุผลการปิดช่วงนี้')
    if (!reason || !reason.trim()) return
    const body =
      action === 'VOID'
        ? { action: 'VOID', expected_revision: period.revision, reason: reason.trim() }
        : { action: 'CORRECT', expected_revision: period.revision, reason: reason.trim(), started_at: period.started_at, ended_at: nowInstant() }
    void send(`${action}:${period.period_id}:${period.revision}:${reason.trim()}`, `${path}/${period.period_id}/revisions`, () => body)
  }

  const open = repair.status === 'OPEN'
  const ongoing = data?.periods.find((p) => p.record_kind !== 'VOID' && p.ended_at === null) ?? null
  const periods = data?.periods.filter((p) => p.record_kind !== 'VOID') ?? []

  return (
    <Card>
      <h2>สถานะย่อยงานซ่อม</h2>
      <div className="status-card__row">
        <span>สถานะย่อยปัจจุบัน</span>
        <span data-testid="substate-current">{ongoing ? SUBSTATE_LABEL[ongoing.substate] : 'ไม่ได้ระบุ'}</span>
      </div>
      {awaitingPartsFlag && (
        <p className="form-field__hint" data-testid="store-awaiting-flag">
          มีใบขอเบิกอะไหล่จากคลังที่ยังไม่ปิด (ข้อมูลจากคลัง ไม่ใช่ช่วงเวลารออะไหล่ที่บันทึก)
        </p>
      )}
      {data && (
        <dl className="substate-durations" data-testid="substate-durations">
          <dt>กำลังซ่อม</dt>
          <dd>{elapsed(data.durations.repairing_seconds)}</dd>
          <dt>รออะไหล่</dt>
          <dd>{elapsed(data.durations.awaiting_parts_seconds)}</dd>
          <dt>อื่น ๆ (ไม่ได้ระบุสถานะย่อย)</dt>
          <dd>{elapsed(data.durations.other_seconds)}</dd>
          <dt>ระยะเวลาใบงานทั้งหมด</dt>
          <dd>{elapsed(data.durations.elapsed_seconds)}</dd>
        </dl>
      )}
      <ul>
        {periods.map((p) => (
          <li key={p.period_id} data-testid="substate-period">
            {SUBSTATE_LABEL[p.substate]} · {bangkok(p.started_at)} – {p.ended_at ? bangkok(p.ended_at) : 'ยังดำเนินอยู่'} · ฉบับที่{' '}
            {p.revision}
            {p.reason ? ` · เหตุผล: ${p.reason}` : ''}
            {open && (
              <span className="status-card__actions">
                {p.ended_at === null && (
                  <button type="button" className="button button--secondary" disabled={busy} onClick={() => revise(p, 'CLOSE')}>
                    ปิดช่วงนี้
                  </button>
                )}
                <button type="button" className="button button--secondary" disabled={busy} onClick={() => revise(p, 'VOID')}>
                  ยกเลิกช่วงนี้
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
      {open && (
        <>
          <div className="status-card__actions">
            <button type="button" className="button button--primary" disabled={busy || ongoing?.substate === 'REPAIRING'} onClick={() => switchTo('REPAIRING')}>
              เริ่ม/กลับมาซ่อม (ตอนนี้)
            </button>
            <button type="button" className="button button--secondary" disabled={busy || ongoing?.substate === 'AWAITING_PARTS'} onClick={() => switchTo('AWAITING_PARTS')}>
              รออะไหล่ (ตอนนี้)
            </button>
          </div>
          <details>
            <summary>บันทึกช่วงสถานะย้อนหลัง</summary>
            <div className="form-grid">
              <FormField label="สถานะย่อย" htmlFor="substate-retro-kind">
                <select
                  id="substate-retro-kind"
                  value={retro.substate}
                  onChange={(e) => setRetro((r) => ({ ...r, substate: e.target.value as RepairSubstate }))}
                >
                  <option value="REPAIRING">กำลังซ่อม</option>
                  <option value="AWAITING_PARTS">รออะไหล่</option>
                </select>
              </FormField>
              <FormField label="เริ่ม (เวลาที่เกิดขึ้นจริง)" htmlFor="substate-retro-start">
                <input id="substate-retro-start" type="datetime-local" value={retro.start} onChange={(e) => setRetro((r) => ({ ...r, start: e.target.value }))} />
              </FormField>
              <FormField label="สิ้นสุด (เว้นว่างถ้ายังดำเนินอยู่)" htmlFor="substate-retro-end">
                <input id="substate-retro-end" type="datetime-local" value={retro.end} onChange={(e) => setRetro((r) => ({ ...r, end: e.target.value }))} />
              </FormField>
              <button type="button" className="button button--secondary" disabled={busy} onClick={() => void recordRetro()}>
                บันทึกช่วงย้อนหลัง
              </button>
            </div>
          </details>
        </>
      )}
      {message && (
        <p className="form-field__error" role="alert">
          {message}
        </p>
      )}
    </Card>
  )
}
