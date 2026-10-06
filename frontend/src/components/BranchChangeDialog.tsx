import { useMemo, useState } from 'react'
import { bangkokDateTimeToIso, bangkokWallClock } from '../lib/branchEffectiveTime'
import { formatRegistryInstant } from '../lib/labels'
import { type ReferenceLoad, resolveCode, resolveOptionalCode } from '../lib/referenceResolution'
import type { BranchOperation } from '../lib/registryPending'
import type { BranchHistory, BranchHistoryEvent } from '../lib/types'
import { FormField } from './FormField'

/**
 * Phase 7 Batch 7O2c — one dialog for the five responsible-branch operations
 * (contract Final Rev2 §6.2-§6.6). The request body is built here from the
 * branch history the page last read successfully: its revision, and (for
 * transfer) the derived current branch or (for corrections, cancellations and
 * reconciliation) the master value, are the expected values the server
 * re-checks.
 *
 * - Effective time: "ตอนนี้" (transfer only), a Bangkok calendar date, or a
 *   Bangkok date and time sent with the explicit +07:00 offset.
 * - Reason (insertion, correction, cancellation, reconciliation) is required
 *   and kept exactly as typed (no trimming); at most 500 characters.
 * - The transfer note is optional and kept exactly; empty is omitted.
 * - `related_request_id` is an audit link only: it never settles anything.
 */
type EffectiveMode = 'NOW' | 'DATE' | 'DATETIME'

interface Props {
  operation: BranchOperation
  history: BranchHistory
  branches: ReferenceLoad
  initialRelatedRequestId?: string
  submitting: boolean
  onCancel: () => void
  onSubmit: (body: Record<string, unknown>, eventId: string | null) => void
}

const TITLE: Record<BranchOperation, string> = {
  transfer: 'ย้ายสาขา',
  insertion: 'เพิ่มประวัติย้อนหลัง',
  correction: 'แก้ไขประวัติ',
  cancellation: 'ยกเลิกรายการ',
  reconcile: 'ปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติ',
}

function eventLabel(event: BranchHistoryEvent, branches: ReferenceLoad): string {
  return `${formatRegistryInstant(event.effective_at, event.effective_precision)} → ${resolveOptionalCode(event.to_branch_id, branches)}`
}

export function BranchChangeDialog({
  operation,
  history,
  branches,
  initialRelatedRequestId = '',
  submitting,
  onCancel,
  onSubmit,
}: Props) {
  const events = useMemo(() => history.events.filter((e) => e.in_force), [history])
  const needsEvent = operation === 'correction' || operation === 'cancellation'
  const needsBranch = operation === 'transfer' || operation === 'insertion' || operation === 'correction'
  const needsReason = operation !== 'transfer'
  const allowNow = operation === 'transfer'

  const [eventId, setEventId] = useState('')
  const [branch, setBranch] = useState('')
  const [mode, setMode] = useState<EffectiveMode>(allowNow ? 'NOW' : 'DATE')
  const [date, setDate] = useState('')
  const [dateTime, setDateTime] = useState('')
  const [text, setText] = useState('')
  const [related, setRelated] = useState(initialRelatedRequestId)
  const [error, setError] = useState<string | null>(null)

  const master = history.master.state === 'RECORDED' ? history.master.value : null
  const selected = events.find((e) => e.event_id === eventId)

  const chooseEvent = (id: string) => {
    setEventId(id)
    const event = events.find((e) => e.event_id === id)
    if (operation !== 'correction' || !event) return
    // Prefill the correction with the event as it is now.
    setBranch(event.to_branch_id ?? '')
    const wall = bangkokWallClock(event.effective_at)
    if (event.effective_precision === 'DATE') {
      setMode('DATE')
      setDate(wall.slice(0, 10))
    } else {
      setMode('DATETIME')
      setDateTime(wall)
    }
  }

  const branchOptions = useMemo(() => {
    const options: { value: string; label: string; disabled: boolean }[] = []
    if (branches.kind === 'ready') {
      for (const [code, entry] of branches.byCode) {
        options.push({
          value: code,
          label: entry.isActive ? `${entry.name} (${code})` : `${entry.name} (${code}) (ไม่ใช้งาน)`,
          disabled: !entry.isActive,
        })
      }
    }
    return options
  }, [branches])

  const effective = (): Record<string, string> | null => {
    if (mode === 'NOW') return { mode: 'NOW' }
    if (mode === 'DATE') return date ? { mode: 'DATE', date } : null
    return dateTime ? { mode: 'DATETIME', at: bangkokDateTimeToIso(dateTime) } : null
  }

  const submit = () => {
    if (needsEvent && !selected) return setError('กรุณาเลือกรายการในประวัติ')
    if (needsBranch && branch === '') return setError('กรุณาเลือกสาขา')
    const when = needsBranch ? effective() : null
    if (needsBranch && when === null) return setError('กรุณาระบุเวลาที่มีผล')
    if (needsReason && text.trim() === '') return setError('กรุณาระบุเหตุผล')
    setError(null)
    const revision = { expected_history_revision: history.history_revision }
    let body: Record<string, unknown>
    switch (operation) {
      case 'transfer':
        body = {
          to_branch_id: branch,
          effective: when,
          expected_current_branch_id: history.current.branch_id,
          ...revision,
          ...(text !== '' ? { note_th: text } : {}),
        }
        break
      case 'insertion':
        body = { to_branch_id: branch, effective: when, reason_th: text, ...revision }
        break
      case 'correction':
        body = { to_branch_id: branch, effective: when, reason_th: text, ...revision, expected_master_branch_id: master }
        break
      case 'cancellation':
        body = { reason_th: text, ...revision, expected_master_branch_id: master }
        break
      case 'reconcile':
        body = {
          reason_th: text,
          ...revision,
          expected_master_branch_id: master,
          ...(related !== '' ? { related_request_id: related } : {}),
        }
        break
    }
    onSubmit(body, needsEvent ? (selected?.event_id ?? null) : null)
  }

  const titleId = `branch-${operation}-title`
  return (
    <div className="dialog-overlay" role="presentation" onClick={submitting ? undefined : onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="branch-change-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId}>{TITLE[operation]}</h2>
        <div className="status-card__row">
          <span>สาขาปัจจุบันตามประวัติ</span>
          <span>{resolveOptionalCode(history.current.branch_id, branches, 'ไม่มี/ไม่ทราบ')}</span>
        </div>
        {operation === 'reconcile' && (
          <div className="status-card__row">
            <span>สาขาในข้อมูลทะเบียนรถตอนนี้</span>
            <span>{master === null ? 'ไม่มี' : resolveCode(master, branches).text}</span>
          </div>
        )}
        <div className="form-grid">
          {needsEvent && (
            <FormField label="รายการในประวัติ" htmlFor="branch-event-select">
              <select
                id="branch-event-select"
                value={eventId}
                onChange={(event) => chooseEvent(event.target.value)}
                disabled={submitting}
              >
                <option value="">เลือกรายการ</option>
                {events.map((e) => (
                  <option key={e.event_id} value={e.event_id}>
                    {eventLabel(e, branches)}
                  </option>
                ))}
              </select>
            </FormField>
          )}
          {needsBranch && (
            <>
              <FormField
                label="สาขา"
                htmlFor="branch-target-select"
                hint={branches.kind === 'ready' ? undefined : 'โหลดรายชื่อสาขาไม่ได้ จึงเลือกสาขาไม่ได้จนกว่าจะโหลดสำเร็จ'}
              >
                <select
                  id="branch-target-select"
                  value={branch}
                  onChange={(event) => setBranch(event.target.value)}
                  disabled={submitting}
                >
                  <option value="">เลือกสาขา</option>
                  {branchOptions.map((o) => (
                    <option key={o.value} value={o.value} disabled={o.disabled}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <fieldset className="form-grid">
                <legend>มีผลตั้งแต่ (เวลาประเทศไทย)</legend>
                {allowNow && (
                  <label>
                    <input
                      type="radio"
                      name="branch-effective-mode"
                      checked={mode === 'NOW'}
                      onChange={() => setMode('NOW')}
                      disabled={submitting}
                    />{' '}
                    ตอนนี้
                  </label>
                )}
                <label>
                  <input
                    type="radio"
                    name="branch-effective-mode"
                    checked={mode === 'DATE'}
                    onChange={() => setMode('DATE')}
                    disabled={submitting}
                  />{' '}
                  ระบุวันที่
                </label>
                <label>
                  <input
                    type="radio"
                    name="branch-effective-mode"
                    checked={mode === 'DATETIME'}
                    onChange={() => setMode('DATETIME')}
                    disabled={submitting}
                  />{' '}
                  ระบุวันที่และเวลา
                </label>
                {mode === 'DATE' && (
                  <FormField label="วันที่มีผล" htmlFor="branch-effective-date">
                    <input
                      id="branch-effective-date"
                      type="date"
                      value={date}
                      onChange={(event) => setDate(event.target.value)}
                      disabled={submitting}
                    />
                  </FormField>
                )}
                {mode === 'DATETIME' && (
                  <FormField label="วันที่และเวลาที่มีผล" htmlFor="branch-effective-datetime">
                    <input
                      id="branch-effective-datetime"
                      type="datetime-local"
                      step={1}
                      value={dateTime}
                      onChange={(event) => setDateTime(event.target.value)}
                      disabled={submitting}
                    />
                  </FormField>
                )}
              </fieldset>
            </>
          )}
          <FormField
            label={needsReason ? 'เหตุผล (บังคับ)' : 'หมายเหตุ (ไม่บังคับ)'}
            htmlFor="branch-change-text"
            error={error ?? undefined}
          >
            <textarea
              id="branch-change-text"
              value={text}
              maxLength={needsReason ? 500 : undefined}
              onChange={(event) => setText(event.target.value)}
              disabled={submitting}
            />
          </FormField>
          {operation === 'reconcile' && (
            <FormField
              label="รหัสคำขอที่เกี่ยวข้อง (ไม่บังคับ)"
              htmlFor="branch-reconcile-related"
              hint="ใช้อ้างอิงในประวัติเท่านั้น ไม่ได้ยืนยันผลของคำขอนั้น"
            >
              <input
                id="branch-reconcile-related"
                type="text"
                value={related}
                onChange={(event) => setRelated(event.target.value)}
                disabled={submitting}
              />
            </FormField>
          )}
        </div>
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={submitting}>
            ปิด
          </button>
          <button type="button" className="button button--primary" onClick={submit} disabled={submitting}>
            {submitting ? 'กำลังบันทึก...' : 'ยืนยันการบันทึกสาขา'}
          </button>
        </div>
      </div>
    </div>
  )
}
