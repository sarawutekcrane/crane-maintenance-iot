import { useCallback, useState } from 'react'
import { useCapabilities } from '../lib/capabilities'
import {
  formatRegistryInstant,
  linkConsistencyLabel,
  linkEventKindLabel,
  linkResolutionLabel,
  R2_PANEL_TITLES,
} from '../lib/labels'
import {
  LINK_KINDS,
  parseDriverPage,
  parseLinkHistory,
  parseRelationships,
  parseTechnicianPage,
  technicianName,
  useR2Read,
  type LinkEvent,
  type LinkHistory,
  type LinkKind,
  type LinkKindSpec,
  type LinkResolution,
} from '../lib/r2History'
import { useR2Writes, type R2Family } from '../lib/r2HistoryWrites'
import { Card } from './Card'
import { FormField } from './FormField'
import { LoadingState } from './LoadingState'
import { ResponsiveTable } from './ResponsiveTable'
import { R2WriteNotice } from './TimelineEventDialog'
import { R2ReadFailureView } from './TimelineHistoryTable'
import { V2ContextBanner } from './V2ContextBanner'

/**
 * R2 Batch R2-C2a — the personnel's three R2f identity links (Technician,
 * login Account, Driver): the current resolution, each link's history, and —
 * with the link's own capability — LINK / UNLINK / RELINK and, only when the
 * link no longer matches its history, RECONCILE. Every target id is chosen
 * or typed by the user and proven by the backend; nothing is auto-selected.
 * There is no account list endpoint, so an account is linked by typing its
 * user_id. Without can_link_personnel_account the server omits every account
 * user_id; it is shown as hidden and never reconstructed here.
 */
const FAMILY: Record<LinkKind, R2Family> = {
  technician: 'technician-link',
  account: 'account-link',
  driver: 'driver-link',
}

type LinkOperation = 'LINK' | 'UNLINK' | 'RELINK' | 'RECONCILE'

const OPERATION_TITLE: Record<LinkOperation, string> = {
  LINK: 'เชื่อมโยง',
  UNLINK: 'ยกเลิกการเชื่อมโยง',
  RELINK: 'เปลี่ยนการเชื่อมโยง',
  RECONCILE: 'ปรับข้อมูลให้ตรงกับประวัติ',
}

const HIDDEN = 'ซ่อนไว้ (ไม่มีสิทธิ์ดูรหัสบัญชีผู้ใช้)'

export function PersonnelLinksPanel({ personnelId }: { personnelId: string }) {
  const [state, reload] = useR2Read(`/personnel/${encodeURIComponent(personnelId)}/relationships`, parseRelationships)
  return (
    <Card className="r2-panel">
      <h2>{R2_PANEL_TITLES.personnelLinks}</h2>
      <V2ContextBanner />
      {state.kind === 'loading' && <LoadingState message="กำลังโหลดความเชื่อมโยงข้อมูลบุคลากร..." />}
      {state.kind === 'error' && (
        <R2ReadFailureView failure={state.failure} title="โหลดความเชื่อมโยงข้อมูลบุคลากรไม่สำเร็จ" onRetry={reload} />
      )}
      {state.kind === 'ready' && (
        <div data-testid="personnel-links">
          {(['technician', 'account', 'driver'] as const).map((kind) => (
            <LinkSection
              key={kind}
              personnelId={personnelId}
              spec={LINK_KINDS[kind]}
              resolution={state.data[kind]}
              onChanged={reload}
            />
          ))}
        </div>
      )}
    </Card>
  )
}

function shownId(id: string | null, visible: boolean): string {
  if (!visible) return HIDDEN
  return id === null ? '-' : id
}

function LinkSection({
  personnelId, spec, resolution, onChanged,
}: {
  personnelId: string
  spec: LinkKindSpec
  resolution: LinkResolution
  onChanged: () => void
}) {
  const { hasCapability, userId } = useCapabilities()
  const canWrite = hasCapability(spec.capability)
  const family = FAMILY[spec.kind]
  const writes = useR2Writes(userId, family, personnelId)
  const { settle } = writes
  const parse = useCallback((json: unknown) => parseLinkHistory(json, spec), [spec])
  const onData = useCallback((history: LinkHistory) => settle({ kind: 'link', history }), [settle])
  const base = `/personnel/${encodeURIComponent(personnelId)}/${spec.segment}`
  const [history, reloadHistory] = useR2Read(`${base}/history`, parse, onData)
  const [dialog, setDialog] = useState<LinkOperation | null>(null)

  const reload = useCallback(() => {
    reloadHistory()
    onChanged()
  }, [reloadHistory, onChanged])

  const data = history.kind === 'ready' ? history.data : null
  const visible = resolution.visible && (data?.ids_visible ?? true)
  const blocked = writes.intent !== null || writes.inFlight

  const open = (operation: LinkOperation) => {
    writes.setMessage(null)
    writes.setDialogError(null)
    setDialog(operation)
  }

  const submit = async (operation: LinkOperation, body: Record<string, unknown>) => {
    const path = operation === 'RECONCILE' ? `${base}/reconcile` : base
    const result = await writes.submit(path, operation, body, reload)
    if (result && result.kind !== 'refused' && result.kind !== 'blocked') setDialog(null)
  }

  return (
    <section className="r2-link-section" data-testid={`link-${spec.kind}`}>
      <h3>{spec.title}</h3>
      <div className="status-card__row">
        <span>สถานะ</span>
        <span data-testid={`link-${spec.kind}-resolution`}>{linkResolutionLabel[resolution.resolution] ?? resolution.resolution}</span>
      </div>
      <div className="status-card__row">
        <span>{spec.targetName}</span>
        <span data-testid={`link-${spec.kind}-id`}>
          {resolution.visible ? (resolution.id === null ? '-' : <code>{resolution.id}</code>) : HIDDEN}
          {technicianName(resolution.technician) ? ` ${technicianName(resolution.technician)}` : ''}
        </span>
      </div>
      <R2WriteNotice
        message={writes.message}
        intent={writes.intent}
        inFlight={writes.inFlight}
        onResend={() => void writes.resend(reload)}
        onReload={reload}
      />
      {history.kind === 'loading' && <LoadingState message="กำลังโหลดประวัติความเชื่อมโยง..." />}
      {history.kind === 'error' && (
        <R2ReadFailureView failure={history.failure} title="โหลดประวัติความเชื่อมโยงไม่สำเร็จ" onRetry={reloadHistory} />
      )}
      {data && (
        <>
          <div className="status-card__row">
            <span>เทียบกับประวัติ</span>
            <span>{linkConsistencyLabel[data.consistency]}</span>
          </div>
          {data.consistency === 'MISMATCH' && (
            <div className="form-field__error" role="alert">
              <p>ข้อมูลความเชื่อมโยงปัจจุบันไม่ตรงกับประวัติล่าสุด ต้องปรับข้อมูลให้ตรงกับประวัติก่อนเปลี่ยนแปลงอื่น</p>
              {canWrite && !blocked && (
                <button type="button" className="button button--secondary" onClick={() => open('RECONCILE')}>
                  {OPERATION_TITLE.RECONCILE}
                </button>
              )}
            </div>
          )}
          {canWrite && !blocked && data.consistency !== 'MISMATCH' && (
            <div className="dialog__actions" data-testid={`link-${spec.kind}-actions`}>
              {data.current_id === null ? (
                <button type="button" className="button button--secondary" onClick={() => open('LINK')}>{OPERATION_TITLE.LINK}</button>
              ) : (
                <>
                  <button type="button" className="button button--secondary" onClick={() => open('RELINK')}>{OPERATION_TITLE.RELINK}</button>
                  <button type="button" className="button button--secondary" onClick={() => open('UNLINK')}>{OPERATION_TITLE.UNLINK}</button>
                </>
              )}
            </div>
          )}
          <ResponsiveTable
            columns={[
              { key: 'kind', header: 'รายการ', render: (e: LinkEvent) => linkEventKindLabel[e.event_kind] ?? e.event_kind },
              {
                key: 'change',
                header: 'จาก → เป็น',
                render: (e: LinkEvent) => `${shownId(e.previous_id, visible)} → ${shownId(e.new_id, visible)}`,
              },
              { key: 'recorded_at', header: 'บันทึกเมื่อ', render: (e: LinkEvent) => formatRegistryInstant(e.recorded_at) },
              { key: 'recorded_by', header: 'ผู้บันทึก', render: (e: LinkEvent) => e.recorded_by },
              { key: 'reason', header: 'เหตุผล', render: (e: LinkEvent) => e.reason_th },
              { key: 'request', header: 'รหัสคำขอ', render: (e: LinkEvent) => <code>{e.request_id}</code> },
            ]}
            rows={[...data.events].reverse()}
            getRowKey={(e) => e.link_event_id}
            emptyTitle="ยังไม่มีประวัติความเชื่อมโยง"
            emptyDescription="ยังไม่เคยเปลี่ยนความเชื่อมโยงนี้ผ่านระบบ"
          />
          {dialog && (
            <LinkDialog
              operation={dialog}
              spec={spec}
              history={data}
              submitting={writes.inFlight}
              error={writes.dialogError}
              onCancel={() => setDialog(null)}
              onSubmit={(body) => void submit(dialog, body)}
            />
          )}
        </>
      )}
    </section>
  )
}

interface PickerProps {
  value: string
  onChange: (value: string) => void
  disabled: boolean
}

/** A select of loaded choices; while the list is unavailable the id is typed. */
function OptionsPicker<T>({ path, parse, toOption, placeholder, value, onChange, disabled }: PickerProps & {
  path: string
  parse: (json: unknown) => T[] | null
  toOption: (item: T) => { id: string; label: string }
  placeholder: string
}) {
  const [list] = useR2Read(path, parse)
  if (list.kind !== 'ready') {
    return <input id="link-target" type="text" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} />
  }
  return (
    <select id="link-target" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      <option value="">{placeholder}</option>
      {list.data.map(toOption).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
    </select>
  )
}

/** Choices for a technician / driver target, loaded only while the dialog is
 * open (an account is always typed: there is no account list). */
function TargetPicker({ spec, ...props }: PickerProps & { spec: LinkKindSpec }) {
  if (spec.kind === 'technician') {
    return (
      <OptionsPicker
        {...props}
        path="/technicians?page_size=200"
        parse={parseTechnicianPage}
        toOption={(t) => ({ id: t.technician_id, label: `${technicianName(t) ?? '(ไม่มีชื่อ)'} (${t.technician_id})` })}
        placeholder={`เลือก${spec.targetName}`}
      />
    )
  }
  return (
    <OptionsPicker
      {...props}
      path="/drivers?page_size=200"
      parse={parseDriverPage}
      toOption={(d) => ({ id: d.driver_id, label: `${d.driver_name_th} (${d.driver_id})` })}
      placeholder={`เลือก${spec.targetName}`}
    />
  )
}

function LinkDialog({
  operation, spec, history, submitting, error, onCancel, onSubmit,
}: {
  operation: LinkOperation
  spec: LinkKindSpec
  history: LinkHistory
  submitting: boolean
  error: string | null
  onCancel: () => void
  onSubmit: (body: Record<string, unknown>) => void
}) {
  const f = spec.idField
  const latest = history.events.at(-1) ?? null
  const [target, setTarget] = useState('')
  const [reason, setReason] = useState('')
  const [related, setRelated] = useState(latest?.request_id ?? '')
  const [localError, setLocalError] = useState<string | null>(null)
  const needsTarget = operation === 'LINK' || operation === 'RELINK'

  const submit = () => {
    if (needsTarget && target.trim() === '') return setLocalError(`กรุณาเลือกหรือระบุ${spec.targetName}`)
    if (operation === 'RECONCILE' && related.trim() === '') return setLocalError('กรุณาระบุรหัสคำขอที่เกี่ยวข้อง')
    if (reason.trim() === '') return setLocalError('กรุณาระบุเหตุผล')
    setLocalError(null)
    const expected = { [`expected_${f}`]: history.current_id ?? '' }
    if (operation === 'RECONCILE') return onSubmit({ ...expected, related_request_id: related, reason_th: reason })
    const body: Record<string, unknown> = { operation, ...expected }
    if (needsTarget) body[`new_${f}`] = target
    body.reason_th = reason
    onSubmit(body)
  }

  const titleId = `link-${spec.kind}-${operation}-title`
  return (
    <div className="dialog-overlay" role="presentation" onClick={submitting ? undefined : onCancel}>
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="link-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId}>{`${OPERATION_TITLE[operation]} — ${spec.title}`}</h2>
        <div className="status-card__row">
          <span>{spec.targetName}ปัจจุบัน</span>
          <span>{history.current_id ?? 'ไม่มี'}</span>
        </div>
        {operation === 'RECONCILE' && (
          <div className="status-card__row">
            <span>ค่าตามประวัติล่าสุด (ระบบเป็นผู้กำหนด)</span>
            <span>{history.latest_history_id ?? 'ไม่มี (ยกเลิกการเชื่อมโยง)'}</span>
          </div>
        )}
        <div className="form-grid">
          {needsTarget && (
            <FormField
              label={spec.targetName}
              htmlFor="link-target"
              hint={spec.kind === 'account'
                ? 'ระบุรหัสบัญชีผู้ใช้เอง (ไม่มีรายการให้เลือก) ระบบหลังบ้านจะตรวจสอบรหัสนี้'
                : 'ต้องเลือกหรือระบุเอง ระบบไม่เลือกให้ และระบบหลังบ้านจะตรวจสอบอีกครั้ง'}
            >
              {spec.kind === 'account' ? (
                <input id="link-target" type="text" value={target} onChange={(e) => setTarget(e.target.value)} disabled={submitting} />
              ) : (
                <TargetPicker spec={spec} value={target} onChange={setTarget} disabled={submitting} />
              )}
            </FormField>
          )}
          {operation === 'RECONCILE' && (
            <FormField label="รหัสคำขอที่เกี่ยวข้อง" htmlFor="link-related" hint="รหัสคำขอของรายการล่าสุดในประวัติ (ระบบตรวจสอบอีกครั้ง)">
              <input id="link-related" type="text" value={related} onChange={(e) => setRelated(e.target.value)} disabled={submitting} />
            </FormField>
          )}
          <FormField label="เหตุผล (บังคับ)" htmlFor="link-reason" error={localError ?? error ?? undefined}>
            <textarea id="link-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} disabled={submitting} />
          </FormField>
        </div>
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={submitting}>ปิด</button>
          <button type="button" className="button button--primary" onClick={submit} disabled={submitting}>
            {submitting ? 'กำลังบันทึก...' : `ยืนยัน${OPERATION_TITLE[operation]}`}
          </button>
        </div>
      </div>
    </div>
  )
}
