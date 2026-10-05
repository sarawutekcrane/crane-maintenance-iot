/**
 * Phase 7 Batch 7O2a — read-only registry history panels on the vehicle
 * detail page (contract Final Rev2 §4.5, §7.4, §10.1, §10.2).
 *
 * - The two panels load and fail independently: one failing never empties
 *   or hides the other, or the detail page.
 * - A failed read is a coded error with a retry, NEVER an empty history:
 *   "ยังไม่มีประวัติ" appears only for a successful response with no rows.
 *   A response that is not the expected shape is treated as a failure.
 * - Each panel guards its reads: a late response after a retry, a route
 *   change (the parent view is keyed by vehicle id) or unmount never applies.
 * - Nothing here writes. No edit, correction, cancellation or reconciliation
 *   control is rendered (those arrive with later batches).
 * - Phase 7 Batch 7O2b: the registration panel reports every completed read
 *   (the data, or null for a failure) so the page can settle pending
 *   registration intents (contract §10.4), and re-reads when
 *   `registrationReloadToken` changes. It still renders no write control.
 */
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  branchConsistencyLabel,
  branchCurrentSourceLabel,
  branchEntryOperationLabel,
  branchEventNoteLabel,
  branchRecordKindLabel,
  describeErrorCode,
  formatRegistryInstant,
  registrationChangeKindLabel,
  registrationConsistencyLabel,
} from '../lib/labels'
import { type ReferenceLoad, resolveOptionalCode } from '../lib/referenceResolution'
import type { BranchHistory, BranchHistoryEvent, BranchHistoryRecord, RegistrationHistory, RegistrationHistoryItem } from '../lib/types'
import { Card } from './Card'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { LoadingState } from './LoadingState'
import { ResponsiveTable } from './ResponsiveTable'

type PanelState<T> =
  | { kind: 'loading' }
  | { kind: 'ready'; data: T }
  | { kind: 'error'; message: string; requestId?: string | null }

export const HISTORY_EMPTY_TITLE = 'ยังไม่มีประวัติ'
const MALFORMED_MESSAGE = 'ข้อมูลประวัติที่ได้รับมีรูปแบบไม่ถูกต้อง จึงไม่แสดงประวัติ กรุณาลองใหม่อีกครั้ง'

// Runtime shape guards (7O2a review fix). A 200 body is shown only when every
// field the panels read has the contracted type and, for finite vocabularies,
// a known value (contract Final Rev2 §4.5, §5.4, §7.4). Anything else is the
// MALFORMED_MESSAGE error state: never coerced, never shown as empty history.
type Obj = Record<string, unknown>

const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const isStr = (v: unknown): v is string => typeof v === 'string'
const isStrOrNull = (v: unknown) => v === null || isStr(v)
const isInt = (v: unknown) => typeof v === 'number' && Number.isInteger(v)
const oneOf = (values: readonly string[]) => (v: unknown) => isStr(v) && values.includes(v)
const orNull = (check: (v: unknown) => boolean) => (v: unknown) => v === null || check(v)
const arrayOf = (check: (v: unknown) => boolean) => (v: unknown) => Array.isArray(v) && v.every(check)

function fields(v: unknown, spec: Record<string, (value: unknown) => boolean>): boolean {
  return isObj(v) && Object.entries(spec).every(([key, check]) => key in v && check(v[key]))
}

const isRegistryField = (v: unknown) =>
  fields(v, { state: oneOf(['NOT_IN_SCHEMA', 'NOT_RECORDED', 'RECORDED']), value: isStrOrNull })
const isIssues = (v: unknown) => isObj(v) && Object.values(v).every((n) => isInt(n))
const isRecordedSource = orNull(oneOf(['EVENT', 'BASELINE', 'NONE']))
const isPrecision = orNull(oneOf(['DATE', 'DATETIME']))

const isBranchEvent = (v: unknown) =>
  fields(v, {
    event_id: isStr,
    in_force: (x) => typeof x === 'boolean',
    head_record_id: isStr,
    revision_no: (x) => isInt(x) && (x as number) >= 1,
    to_branch_id: isStrOrNull,
    effective_at: isStrOrNull,
    effective_precision: isPrecision,
    derived_from_branch_id: isStrOrNull,
    original_entry_from_branch_id: isStrOrNull,
    original_entry_from_source: isRecordedSource,
    head_entry_from_branch_id: isStrOrNull,
    head_entry_from_source: isRecordedSource,
    derived_end_at: isStrOrNull,
    notes: arrayOf(oneOf(['RECORDED_SOURCE_DIFFERS', 'REDUNDANT', 'SAME_INSTANT', 'CANCELLED'])),
  })

const isBranchRecord = (v: unknown) =>
  fields(v, {
    record_id: isStr,
    record_kind: oneOf(['ASSIGNMENT', 'CORRECTION', 'CANCELLATION', 'PROJECTION_RECONCILIATION']),
    entry_operation: oneOf(['TRANSFER', 'INSERTION', 'CORRECTION', 'CANCELLATION', 'PROJECTION_RECONCILIATION']),
    event_id: isStrOrNull,
    revision_no: orNull((x) => isInt(x) && (x as number) >= 1),
    supersedes_record_id: isStrOrNull,
    branch_id: isStrOrNull,
    effective_at: isStrOrNull,
    recorded_from_branch_id: isStrOrNull,
    recorded_from_source: isRecordedSource,
    recorded_at: isStr,
    recorded_by: isStr,
    request_id: isStr,
    related_request_id: isStrOrNull,
    reason_th: isStrOrNull,
    reconciled_old_master_branch_id: isStrOrNull,
  })

function isBranchHistory(data: unknown): data is BranchHistory {
  return fields(data, {
    asset_type: oneOf(['VEHICLE']),
    asset_id: isStr,
    timeline_status: oneOf(['VALID', 'AMBIGUOUS_ORDER']),
    current: (v) =>
      fields(v, {
        branch_id: isStrOrNull,
        source: oneOf(['EVENT', 'BASELINE', 'IMPORTED_MASTER', 'NONE', 'UNDETERMINED']),
      }),
    master: isRegistryField,
    consistency: oneOf(['CONSISTENT', 'NO_HISTORY', 'PROJECTION_MISMATCH', 'UNDETERMINED']),
    history_revision: isStr,
    baseline: orNull((v) => fields(v, { branch_id: isStrOrNull, source: oneOf(['IMPORTED_MASTER', 'NONE']) })),
    events: arrayOf(isBranchEvent),
    records: arrayOf(isBranchRecord),
    excluded_test_rows: isInt,
    issues: isIssues,
  })
}

const isRegistrationItem = (v: unknown) =>
  fields(v, {
    change_id: isStr,
    change_kind: oneOf(['CHANGE', 'RECONCILIATION_APPLY_RECORDED', 'RECONCILIATION_ACCEPT_MASTER']),
    old_registration_no: isStrOrNull,
    old_registration_province_code: isStrOrNull,
    new_registration_no: isStrOrNull,
    new_registration_province_code: isStrOrNull,
    recorded_at: isStr,
    recorded_by: isStr,
    request_id: isStr,
    related_request_id: isStrOrNull,
    accepted_exceptions: arrayOf(
      oneOf(['REFERENCE_UNKNOWN_ACCEPTED', 'REFERENCE_INACTIVE_ACCEPTED', 'EXISTING_DUPLICATE_PAIR']),
    ),
    note_th: isStrOrNull,
  })

function isRegistrationHistory(data: unknown): data is RegistrationHistory {
  return fields(data, {
    vehicle_id: isStr,
    current: (v) => fields(v, { registration_no: isRegistryField, registration_province: isRegistryField }),
    consistency: oneOf(['CONSISTENT', 'NO_HISTORY', 'MISMATCH', 'UNDETERMINED']),
    history_revision: isStr,
    items: arrayOf(isRegistrationItem),
    excluded_test_rows: isInt,
    issues: isIssues,
  })
}

async function readPanel<T>(path: string, accept: (data: unknown) => data is T): Promise<PanelState<T>> {
  const result = await apiGet<unknown>(path)
  if (!result.ok) {
    const err = result.error
    return {
      kind: 'error',
      message: err instanceof ApiError ? describeErrorCode(err.code) : 'โหลดประวัติไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
      requestId: err instanceof ApiError ? err.requestId : null,
    }
  }
  return accept(result.data) ? { kind: 'ready', data: result.data } : { kind: 'error', message: MALFORMED_MESSAGE }
}

/** One guarded GET per panel (the initial state is already `loading`);
 * `retry` shows loading again and starts a new generation. A result applies
 * only while its generation is current; unmount advances it. */
function usePanel<T>(path: string, accept: (data: unknown) => data is T) {
  const [state, setState] = useState<PanelState<T>>({ kind: 'loading' })
  const generation = useRef(0)

  const start = useCallback(() => {
    const mine = ++generation.current
    void readPanel(path, accept).then((next) => {
      if (mine === generation.current) setState(next)
    })
  }, [path, accept])

  useEffect(() => {
    const reads = generation
    start()
    return () => {
      reads.current += 1
    }
  }, [start])

  const retry = useCallback(() => {
    setState({ kind: 'loading' })
    start()
  }, [start])

  return { state, retry }
}

interface PanelsProps {
  vehicleId: string
  branches: ReferenceLoad
  provinces: ReferenceLoad
  /** 7O2b: a change re-reads the registration history. */
  registrationReloadToken?: number
  /** 7O2b: called after every completed registration-history read (null = failed). */
  onRegistrationHistoryRead?: (history: RegistrationHistory | null) => void
}

export function RegistryHistoryPanels({
  vehicleId,
  branches,
  provinces,
  registrationReloadToken = 0,
  onRegistrationHistoryRead,
}: PanelsProps) {
  const id = encodeURIComponent(vehicleId)
  return (
    <>
      {/* Keyed by path: another vehicle gets a fresh panel, never the previous rows. */}
      <BranchHistoryPanel key={`b:${id}`} path={`/vehicles/${id}/branch-history`} branches={branches} />
      <RegistrationHistoryPanel
        key={`r:${id}`}
        path={`/vehicles/${id}/registration-history`}
        provinces={provinces}
        reloadToken={registrationReloadToken}
        onRead={onRegistrationHistoryRead}
      />
    </>
  )
}

function PanelBody<T>({
  title,
  state,
  retry,
  children,
}: {
  title: string
  state: PanelState<T>
  retry: () => void
  children: (data: T) => ReactNode
}) {
  if (state.kind === 'loading') return <LoadingState message={`กำลังโหลด${title}...`} />
  if (state.kind === 'error') {
    // A panel-specific retry name: several retries can be on this page at once.
    return (
      <>
        <ErrorState title={`โหลด${title}ไม่สำเร็จ`} message={state.message} requestId={state.requestId} />
        <button type="button" className="button button--secondary button--full-width" onClick={retry}>
          ลองโหลด{title}อีกครั้ง
        </button>
      </>
    )
  }
  return <>{children(state.data)}</>
}

function BranchHistoryPanel({ path, branches }: { path: string; branches: ReferenceLoad }) {
  const { state, retry } = usePanel<BranchHistory>(path, isBranchHistory)
  const branch = (code: string | null, none?: string) => resolveOptionalCode(code, branches, none)
  return (
    <section aria-label="ประวัติสาขาที่รับผิดชอบ" data-testid="branch-history-panel">
      <Card>
        <h2>ประวัติสาขาที่รับผิดชอบ</h2>
        <PanelBody title="ประวัติสาขา" state={state} retry={retry}>
          {(history) => (
            <>
              <div className="status-card__row">
                <span>สาขาปัจจุบันตามประวัติ</span>
                <span>
                  {branch(history.current.branch_id, 'ไม่มี/ไม่ทราบ')}{' '}
                  ({branchCurrentSourceLabel[history.current.source] ?? history.current.source})
                </span>
              </div>
              <div className="status-card__row">
                <span>เทียบกับข้อมูลทะเบียนรถ</span>
                <span>{branchConsistencyLabel[history.consistency] ?? history.consistency}</span>
              </div>
              {history.baseline && (
                <div className="status-card__row">
                  <span>สาขาเดิมก่อนมีประวัติ</span>
                  <span>{branch(history.baseline.branch_id, 'ไม่มี')}</span>
                </div>
              )}
              {history.timeline_status === 'AMBIGUOUS_ORDER' && (
                <p className="form-field__error" role="status">
                  มีการย้ายสาขาที่มีผลเวลาเดียวกัน จึงระบุลำดับและสาขาปัจจุบันไม่ได้ กรุณาแจ้งผู้ดูแลข้อมูล
                </p>
              )}
              {history.records.length === 0 ? (
                <EmptyState title={HISTORY_EMPTY_TITLE} description="ยังไม่มีการบันทึกการย้ายสาขาสำหรับยานพาหนะนี้" />
              ) : (
                <>
                  <ResponsiveTable<BranchHistoryEvent>
                    columns={[
                      {
                        key: 'effective',
                        header: 'มีผลตั้งแต่',
                        render: (e) => formatRegistryInstant(e.effective_at, e.effective_precision),
                      },
                      { key: 'to', header: 'ย้ายไปสาขา', render: (e) => branch(e.to_branch_id) },
                      {
                        key: 'from',
                        header: 'ย้ายจากสาขา',
                        render: (e) => (e.in_force ? branch(e.derived_from_branch_id) : '-'),
                      },
                      {
                        key: 'notes',
                        header: 'หมายเหตุ',
                        render: (e) =>
                          e.notes.length ? e.notes.map((n) => branchEventNoteLabel[n] ?? n).join(' · ') : '-',
                      },
                      { key: 'revision', header: 'ฉบับที่', render: (e) => String(e.revision_no) },
                    ]}
                    rows={history.events}
                    getRowKey={(e) => e.event_id}
                  />
                  <details>
                    <summary>รายการที่บันทึกทั้งหมด ({history.records.length} รายการ)</summary>
                    <ResponsiveTable<BranchHistoryRecord>
                      columns={[
                        { key: 'recorded_at', header: 'บันทึกเมื่อ', render: (r) => formatRegistryInstant(r.recorded_at) },
                        {
                          key: 'kind',
                          header: 'ประเภท',
                          render: (r) =>
                            `${branchRecordKindLabel[r.record_kind] ?? r.record_kind} (${branchEntryOperationLabel[r.entry_operation] ?? r.entry_operation})`,
                        },
                        { key: 'branch', header: 'สาขา', render: (r) => branch(r.branch_id, '-') },
                        { key: 'reason', header: 'เหตุผล', render: (r) => r.reason_th ?? '-' },
                        { key: 'by', header: 'ผู้บันทึก', render: (r) => r.recorded_by },
                        { key: 'request', header: 'รหัสคำขอ', render: (r) => r.request_id },
                      ]}
                      rows={history.records}
                      getRowKey={(r) => r.record_id}
                    />
                  </details>
                </>
              )}
            </>
          )}
        </PanelBody>
      </Card>
    </section>
  )
}

function pairText(no: string | null, province: string | null, provinces: ReferenceLoad): string {
  if (no === null) return 'ไม่มีทะเบียน'
  return province === null ? no : `${no} · ${resolveOptionalCode(province, provinces)}`
}

function RegistrationHistoryPanel({
  path,
  provinces,
  reloadToken,
  onRead,
}: {
  path: string
  provinces: ReferenceLoad
  reloadToken: number
  onRead?: (history: RegistrationHistory | null) => void
}) {
  const { state, retry } = usePanel<RegistrationHistory>(path, isRegistrationHistory)
  useEffect(() => {
    if (reloadToken > 0) retry()
  }, [reloadToken, retry])
  useEffect(() => {
    if (state.kind === 'ready') onRead?.(state.data)
    else if (state.kind === 'error') onRead?.(null)
  }, [state, onRead])
  return (
    <section aria-label="ประวัติทะเบียนรถ" data-testid="registration-history-panel">
      <Card>
        <h2>ประวัติทะเบียนรถ</h2>
        <PanelBody title="ประวัติทะเบียนรถ" state={state} retry={retry}>
          {(history) => (
            <>
              <div className="status-card__row">
                <span>เทียบกับข้อมูลทะเบียนรถ</span>
                <span>{registrationConsistencyLabel[history.consistency] ?? history.consistency}</span>
              </div>
              {history.items.length === 0 ? (
                <EmptyState title={HISTORY_EMPTY_TITLE} description="ยังไม่มีการบันทึกการเปลี่ยนทะเบียนสำหรับยานพาหนะนี้" />
              ) : (
                <ResponsiveTable<RegistrationHistoryItem>
                  columns={[
                    { key: 'recorded_at', header: 'บันทึกเมื่อ', render: (i) => formatRegistryInstant(i.recorded_at) },
                    {
                      key: 'kind',
                      header: 'ประเภท',
                      render: (i) => registrationChangeKindLabel[i.change_kind] ?? i.change_kind,
                    },
                    {
                      key: 'old',
                      header: 'เดิม',
                      render: (i) => pairText(i.old_registration_no, i.old_registration_province_code, provinces),
                    },
                    {
                      key: 'new',
                      header: 'ใหม่',
                      render: (i) => pairText(i.new_registration_no, i.new_registration_province_code, provinces),
                    },
                    { key: 'by', header: 'ผู้บันทึก', render: (i) => i.recorded_by },
                    { key: 'note', header: 'หมายเหตุ', render: (i) => i.note_th ?? '-' },
                  ]}
                  rows={history.items}
                  getRowKey={(i) => i.change_id}
                />
              )}
            </>
          )}
        </PanelBody>
      </Card>
    </section>
  )
}
