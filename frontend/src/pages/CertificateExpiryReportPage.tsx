import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import { certificateReportLinks } from '../lib/certificateReportLinks'
import {
  certificateExpiryPositionLabel,
  certificateReportDefectLabel,
  certificateReportFlagLabel,
  certificateStatusLabel,
  certificateStatusTone,
  describeErrorCode,
  formatReportCalendarDate,
} from '../lib/labels'
import type {
  CertificateEffectiveStatus,
  CertificateExpiryReport,
  CertificateExpiryReportFilter,
  CertificateExpiryReportItem,
  CertificateExpiryReportPopulation,
  CertificateReportMode,
} from '../lib/types'

const PAGE_SIZE = 50

type StatusFilter = CertificateEffectiveStatus | ''

/** Filter criteria as the user edits them (draft) or as last submitted
 * (applied). Neither is ever filled from a response: a blank end date
 * stays blank (dynamic "today" per request) even after the backend echoes
 * the date it resolved. */
interface Criteria {
  mode: CertificateReportMode
  expiryFrom: string
  expiryTo: string
  effectiveStatus: StatusFilter
}

interface AppliedRequest extends Criteria {
  page: number
}

const INITIAL_CRITERIA: Criteria = { mode: 'RANGE', expiryFrom: '', expiryTo: '', effectiveStatus: '' }

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; title: string; message: string; requestId?: string | null; retry: boolean }
  | { kind: 'ready'; report: CertificateExpiryReport; asOfShift: { from: string; to: string } | null }

/** One displayed row. `position` (1-based within the whole result) is the
 * render key — a page position, never a certificate id (ids may repeat or
 * be blank). */
interface ReportRow {
  item: CertificateExpiryReportItem
  position: number
}

const MODE_OPTIONS: { value: CertificateReportMode; label: string }[] = [
  { value: 'RANGE', label: 'ตามช่วงวันหมดอายุ' },
  { value: 'MISSING_EXPIRY_DATE', label: 'ใบรับรองที่ไม่มีวันหมดอายุในระบบ' },
]

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: '', label: 'ทั้งหมด' },
  { value: 'ACTIVE', label: certificateStatusLabel.ACTIVE },
  { value: 'EXPIRED', label: certificateStatusLabel.EXPIRED },
]

const SCOPE_NOTES = [
  'นับเป็นรายการใบรับรอง (1 แถว = 1 ใบรับรอง) ไม่ใช่จำนวนรถ',
  'ไม่รวมใบรับรองที่บันทึกว่าถูกแทนที่แล้ว และใบรับรองที่ไม่ได้ระบุสถานะ (แสดงจำนวนไว้ด้านล่าง)',
  `สถานะที่คำนวณ: ใบที่บันทึกว่า “${certificateStatusLabel.ACTIVE}” จะแสดงเป็น “${certificateStatusLabel.EXPIRED}” เฉพาะเมื่อวันหมดอายุอยู่ก่อนวันที่อ้างอิงของรายงาน ใบที่บันทึกว่า “${certificateStatusLabel.EXPIRED}” แสดงเป็น “${certificateStatusLabel.EXPIRED}” เสมอ และใบที่ไม่มีวันหมดอายุในระบบจะแสดงตามสถานะที่บันทึกไว้`,
  'รายงานนี้ไม่ได้ระบุว่ารถคันใดต้องมีใบรับรองประเภทใด ไม่ใช่การยืนยันความถูกต้องตามกฎหมาย และรถที่ไม่มีรายการในรายงานไม่ได้แปลว่ามีใบรับรองครบ',
  'หมายเหตุข้อมูลเป็นเพียงข้อสังเกตจากข้อมูลที่อ่านได้ ไม่ได้ยืนยันว่าใบใดเป็นใบแทนหรือใช้ได้ตามกฎหมาย',
]

const CERTIFICATE_DESTINATION_NOTE =
  "หน้าใบรับรองของรถเป็นหน้าที่มีอยู่เดิม เมื่อเปิด ระบบอาจบันทึกสถานะใบรับรองที่วันหมดอายุอยู่ก่อนวันนี้ให้เป็น 'หมดอายุ'"
const LINK_SUPPRESSED_NOTE = '(ลิงก์ใช้ไม่ได้: รหัสมีอักขระที่หน้าปลายทางยังรองรับไม่ได้)'

const POPULATION_LABELS: { key: keyof CertificateExpiryReportPopulation; label: string }[] = [
  { key: 'read_record_count', label: 'รายการใบรับรองที่อ่านได้จากระบบทั้งหมด' },
  { key: 'in_scope_count', label: 'อยู่ในขอบเขตรายงาน (บันทึกว่ายังใช้งานได้หรือหมดอายุ และอ่านได้ครบ)' },
  { key: 'in_scope_with_expiry_date_count', label: 'ในขอบเขต: มีวันหมดอายุ' },
  { key: 'in_scope_without_expiry_date_count', label: 'ในขอบเขต: ไม่มีวันหมดอายุในระบบ' },
  { key: 'excluded_replaced_count', label: 'ไม่รวม: บันทึกว่าถูกแทนที่แล้ว' },
  { key: 'excluded_status_blank_count', label: 'ไม่รวม: ไม่ได้ระบุสถานะ' },
  { key: 'issue_row_count', label: 'อ่านไม่ได้ จึงไม่ได้แสดงในรายงาน' },
  { key: 'excluded_rows_with_other_defects', label: 'รายการที่ไม่รวมซึ่งมีข้อมูลอื่นผิดปกติด้วย' },
  {
    key: 'replaced_link_observations',
    label: 'ใบที่บันทึกว่าถูกแทนที่แต่ไม่มีรหัสใบแทน หรือไม่พบรหัสนั้นในข้อมูล (ข้อสังเกต)',
  },
]

function buildQuery(request: AppliedRequest): string {
  const params = new URLSearchParams({ mode: request.mode })
  if (request.mode === 'RANGE') {
    if (request.expiryFrom) params.set('expiry_from', request.expiryFrom)
    if (request.expiryTo) params.set('expiry_to', request.expiryTo)
  }
  if (request.effectiveStatus) params.set('effective_status', request.effectiveStatus)
  params.set('page', String(request.page))
  params.set('page_size', String(PAGE_SIZE))
  return params.toString()
}

function validationMessage(err: ApiError): string {
  const errors = (err.details as { errors?: Array<Record<string, unknown>> } | null | undefined)?.errors
  const first = errors?.[0]
  if (first?.reason === 'AFTER_EXPIRY_TO' && typeof first.resolved_expiry_to === 'string') {
    const resolved = formatReportCalendarDate(first.resolved_expiry_to)
    const suffix = first.expiry_to_is_default ? ' ซึ่งเป็นวันนี้ตามเวลาประเทศไทย' : ''
    return `วันหมดอายุเริ่มต้นต้องไม่อยู่หลังวันสิ้นสุด (วันสิ้นสุดที่ใช้: ${resolved}${suffix})`
  }
  return 'เงื่อนไขของรายงานไม่ถูกต้อง กรุณาตรวจสอบวันที่และตัวเลือกอีกครั้ง'
}

function toErrorState(err: ApiError | Error): LoadState {
  if (err instanceof ApiError && err.status === 403) return { kind: 'denied' }
  const code = err instanceof ApiError ? err.code : undefined
  const requestId = err instanceof ApiError ? err.requestId : null
  if (err instanceof ApiError && code === 'VALIDATION_ERROR') {
    return { kind: 'error', title: 'เงื่อนไขรายงานไม่ถูกต้อง', message: validationMessage(err), requestId, retry: false }
  }
  return {
    kind: 'error',
    title:
      code === 'VEHICLE_CERTIFICATE_SCHEMA_INVALID' ? 'ไม่แสดงรายงานใบรับรอง' : 'โหลดรายงานใบรับรองไม่สำเร็จ',
    message: describeErrorCode(code),
    requestId,
    retry: true,
  }
}

/** Rows, totals, flags, disclosures, as_of and the filter echo are applied
 * together from one response. `pagedFromAsOf` is the as_of of the page the
 * user paged from (null for submit/refresh/retry). */
function toReadyState(report: CertificateExpiryReport, pagedFromAsOf: string | null): LoadState {
  const asOf = report.as_of_date
  return {
    kind: 'ready',
    report,
    asOfShift: pagedFromAsOf !== null && pagedFromAsOf !== asOf ? { from: pagedFromAsOf, to: asOf } : null,
  }
}

const isBlank = (value: string) => value.trim() === ''

function statusText(status: CertificateEffectiveStatus | null): string {
  return status ? certificateStatusLabel[status] : 'ทั้งหมด'
}

function describeFilter(filter: CertificateExpiryReportFilter): string {
  const status = `สถานะที่คำนวณ: ${statusText(filter.effective_status)}`
  if (filter.mode === 'MISSING_EXPIRY_DATE') return `เงื่อนไข: ใบรับรองที่ไม่มีวันหมดอายุในระบบ · ${status}`
  const from = filter.expiry_from ? formatReportCalendarDate(filter.expiry_from) : 'ไม่จำกัดวันเริ่มต้น'
  const to = filter.expiry_to_resolved ? formatReportCalendarDate(filter.expiry_to_resolved) : '-'
  const toNote = filter.expiry_to_is_default ? ' (วันนี้ตามเวลาประเทศไทย)' : ''
  return `เงื่อนไข: วันหมดอายุตั้งแต่ ${from} ถึง ${to}${toNote} · ${status}`
}

function completeEmptyText(filter: CertificateExpiryReportFilter): string {
  const base =
    filter.mode === 'MISSING_EXPIRY_DATE'
      ? 'ไม่มีใบรับรองที่ไม่มีวันหมดอายุในระบบ'
      : 'ไม่มีใบรับรองที่วันหมดอายุอยู่ในช่วงที่เลือก'
  return filter.effective_status
    ? `${base} และมีสถานะที่คำนวณเป็น “${certificateStatusLabel[filter.effective_status]}”`
    : base
}

function renderCertificateId({ item }: ReportRow) {
  return (
    <span className="certificate-expiry-report__cell certificate-expiry-report__text">
      {isBlank(item.certificate_id) ? '(ไม่มีรหัสใบรับรอง)' : item.certificate_id}
    </span>
  )
}

function renderVehicle({ item }: ReportRow) {
  if (isBlank(item.vehicle_id)) {
    return <span className="certificate-expiry-report__cell">(ไม่มีรหัสรถ)</span>
  }
  const links = certificateReportLinks(item.vehicle_id)
  return (
    <span className="certificate-expiry-report__cell">
      <span className="certificate-expiry-report__text">{item.vehicle_id}</span>
      {links ? (
        <span className="certificate-expiry-report__links">
          <Link to={links.vehicleDetail}>ดูรายละเอียดรถ</Link>
          <Link to={links.vehicleCertificates}>ดูใบรับรองของรถคันนี้</Link>
        </span>
      ) : (
        <span className="certificate-expiry-report__note">{LINK_SUPPRESSED_NOTE}</span>
      )}
    </span>
  )
}

function renderType({ item }: ReportRow) {
  return (
    <span className="certificate-expiry-report__cell">
      <span className="certificate-expiry-report__text">{item.certificate_type_name_th ?? '-'}</span>
      {item.certificate_type_code !== null && (
        <span className="certificate-expiry-report__note certificate-expiry-report__text">
          รหัสประเภท: {item.certificate_type_code}
        </span>
      )}
    </span>
  )
}

function renderExpiry({ item }: ReportRow) {
  return (
    <span className="certificate-expiry-report__cell">
      {item.expiry_date ? formatReportCalendarDate(item.expiry_date) : 'ไม่มีวันหมดอายุในระบบ'}
      {item.expiry_date && (
        <span className="certificate-expiry-report__note">
          {certificateExpiryPositionLabel[item.expiry_position] ?? item.expiry_position}
        </span>
      )}
    </span>
  )
}

function renderStatuses({ item }: ReportRow) {
  return (
    <span className="certificate-expiry-report__cell">
      <StatusBadge
        label={certificateStatusLabel[item.effective_status] ?? item.effective_status}
        tone={certificateStatusTone[item.effective_status]}
      />
      <span className="certificate-expiry-report__note">
        บันทึกไว้: {certificateStatusLabel[item.stored_status] ?? item.stored_status}
      </span>
    </span>
  )
}

function renderFlags({ item }: ReportRow) {
  if (item.flags.length === 0) return <span className="certificate-expiry-report__cell">-</span>
  return (
    <ul className="certificate-expiry-report__cell certificate-expiry-report__flags">
      {item.flags.map((flag) => (
        <li key={flag}>{certificateReportFlagLabel[flag] ?? flag}</li>
      ))}
    </ul>
  )
}

/**
 * "รายงานใบรับรองตามวันหมดอายุ" — Phase 7 Batch 7D2, read-only
 * GET /reports/certificate-expiry (can_view, enforced server-side).
 *
 * Three separate states: the draft form (editing sends nothing), the
 * applied request (set only by submit — which resets to page 1 — and
 * reused by refresh/paging/retry), and the backend response (rows, totals,
 * flags, disclosures, as_of and the filter echo, applied together). A
 * request-generation guard applies only the newest request's success or
 * error; loading and errors hide every part of an older response.
 */
export function CertificateExpiryReportPage() {
  const [draft, setDraft] = useState<Criteria>(INITIAL_CRITERIA)
  const [applied, setApplied] = useState<AppliedRequest>({ ...INITIAL_CRITERIA, page: 1 })
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const generation = useRef(0)

  // `load` only fetches and applies; `run` (called from event handlers)
  // records the applied request and hides the current response first.
  const load = useCallback(async (request: AppliedRequest, pagedFromAsOf: string | null) => {
    const current = ++generation.current
    const result = await apiGet<CertificateExpiryReport>(`/reports/certificate-expiry?${buildQuery(request)}`)
    if (current !== generation.current) return
    setState(result.ok ? toReadyState(result.data, pagedFromAsOf) : toErrorState(result.error))
  }, [])

  const run = (request: AppliedRequest, pagedFromAsOf: string | null = null) => {
    setApplied(request)
    setState({ kind: 'loading' })
    void load(request, pagedFromAsOf)
  }

  useEffect(() => {
    // Initial state already holds the default request: RANGE, no dates.
    void load({ ...INITIAL_CRITERIA, page: 1 }, null)
  }, [load])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    run({ ...draft, page: 1 })
  }

  const updateDraft = (patch: Partial<Criteria>) => setDraft((current) => ({ ...current, ...patch }))
  const rangeMode = draft.mode === 'RANGE'

  const renderPartial = (report: CertificateExpiryReport) => {
    if (report.complete) return null
    const issues = report.population.issue_row_count
    const defects = Object.entries(report.data_issues.issue_defect_counts)
    return (
      <Card className="state-panel certificate-expiry-report__partial">
        <div role="status">
          <p className="state-panel__title">รายงานอาจไม่ครบ</p>
          <p>
            มีข้อมูลใบรับรอง {issues} รายการที่ระบบอ่านสถานะ วันหมดอายุ หรือข้อมูลอื่นไม่ได้
            จึงไม่ได้แสดงในรายงานนี้ และอาจตรงกับเงื่อนไขที่เลือก ผลรายงานนี้จึงอาจไม่ครบ
            ข้อสังเกตข้อมูลอาจไม่ครบด้วย กรุณาแจ้งผู้ดูแลระบบ
          </p>
        </div>
        {defects.length > 0 && (
          <>
            <p className="certificate-expiry-report__subheading">ประเภทปัญหา (นับตามปัญหา ไม่ใช่จำนวนรายการ)</p>
            <ul className="certificate-expiry-report__list">
              {defects.map(([code, count]) => (
                <li key={code}>
                  {certificateReportDefectLabel[code] ?? code}: {count}
                </li>
              ))}
            </ul>
          </>
        )}
        {report.data_issues.sample_certificate_ids.length > 0 && (
          <p className="certificate-expiry-report__text">
            ตัวอย่างรหัสใบรับรองที่อ่านไม่ได้: {report.data_issues.sample_certificate_ids.join(', ')}
          </p>
        )}
        {report.data_issues.issue_rows_without_usable_id > 0 && (
          <p>รายการที่อ่านไม่ได้และไม่มีรหัสใบรับรอง: {report.data_issues.issue_rows_without_usable_id}</p>
        )}
      </Card>
    )
  }

  const renderPopulation = (population: CertificateExpiryReportPopulation) => (
    <details className="certificate-expiry-report__population">
      <summary>จำนวนที่ใช้ประกอบรายงาน (ข้อมูลทั้งหมดที่อ่าน ไม่ขึ้นกับตัวกรอง และไม่ใช่ตัวชี้วัด)</summary>
      <dl>
        {POPULATION_LABELS.map(({ key, label }) => (
          <div key={key} className="certificate-expiry-report__population-row">
            <dt>{label}</dt>
            <dd>{population[key]}</dd>
          </div>
        ))}
      </dl>
    </details>
  )

  const renderRows = (report: CertificateExpiryReport) => {
    const { items, total_items: totalItems, page_size: pageSize } = report
    const currentPage = report.page
    if (totalItems === 0) {
      return report.complete ? (
        <Card className="state-panel">
          <p className="state-panel__title">{completeEmptyText(report.filter)}</p>
        </Card>
      ) : (
        <Card className="state-panel">
          <p className="state-panel__title">
            ไม่พบรายการที่ตรงเงื่อนไขในข้อมูลที่อ่านได้ แต่มีข้อมูล {report.population.issue_row_count}{' '}
            รายการที่อ่านไม่ได้และอาจตรงเงื่อนไข จึงยืนยันไม่ได้ว่าไม่มีรายการ
          </p>
        </Card>
      )
    }
    if (items.length === 0) {
      return (
        <Card className="state-panel">
          <p className="state-panel__title">ไม่มีรายการในหน้านี้</p>
          <p>ขณะนี้ระบบส่งกลับ {totalItems} รายการตามเงื่อนไขนี้</p>
          <button
            type="button"
            className="button button--secondary button--full-width"
            onClick={() => run({ ...applied, page: 1 })}
          >
            กลับไปหน้าแรก
          </button>
        </Card>
      )
    }
    const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))
    const firstIndex = (currentPage - 1) * pageSize + 1
    const lastIndex = firstIndex + items.length - 1
    const rows = items.map((item, index) => ({ item, position: firstIndex + index }))
    return (
      <>
        <p className="certificate-expiry-report__range" aria-live="polite">
          แสดงรายการที่ {firstIndex}–{lastIndex} จาก {totalItems} รายการใบรับรอง
        </p>
        <ResponsiveTable<ReportRow>
          columns={[
            { key: 'certificate_id', header: 'รหัสใบรับรอง', render: renderCertificateId },
            { key: 'vehicle', header: 'รหัสรถ', render: renderVehicle },
            { key: 'type', header: 'ประเภทใบรับรอง', render: renderType },
            {
              key: 'document_no',
              header: 'เลขที่เอกสาร',
              render: ({ item }) => (
                <span className="certificate-expiry-report__cell certificate-expiry-report__text">
                  {item.document_no ?? '-'}
                </span>
              ),
            },
            { key: 'expiry', header: 'วันหมดอายุ', render: renderExpiry },
            { key: 'status', header: 'สถานะที่คำนวณ', render: renderStatuses },
            { key: 'flags', header: 'หมายเหตุข้อมูล', render: renderFlags },
          ]}
          rows={rows}
          getRowKey={(row) => `position-${row.position}`}
        />
        <nav className="certificate-expiry-report__pager" aria-label="เปลี่ยนหน้ารายงานใบรับรอง">
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage <= 1}
            onClick={() => run({ ...applied, page: currentPage - 1 }, report.as_of_date)}
          >
            ก่อนหน้า
          </button>
          <span className="certificate-expiry-report__page-label">
            หน้า {currentPage} จาก {totalPages}
          </span>
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage >= totalPages}
            onClick={() => run({ ...applied, page: currentPage + 1 }, report.as_of_date)}
          >
            ถัดไป
          </button>
        </nav>
      </>
    )
  }

  const renderResults = () => {
    if (state.kind === 'loading') return <LoadingState message="กำลังโหลดรายงานใบรับรอง..." />
    if (state.kind === 'denied') return <PermissionDeniedState message="ไม่มีสิทธิ์ดูรายงานนี้" />
    if (state.kind === 'error') {
      return (
        <ErrorState
          title={state.title}
          message={state.message}
          requestId={state.requestId}
          onRetry={state.retry ? () => run(applied) : undefined}
        />
      )
    }
    const { report, asOfShift } = state
    return (
      <div className="certificate-expiry-report__result">
        <p className="certificate-expiry-report__as-of">
          ข้อมูล ณ วันที่ {formatReportCalendarDate(report.as_of_date)} (เวลาประเทศไทย)
        </p>
        <p className="certificate-expiry-report__filter-echo">{describeFilter(report.filter)}</p>
        {asOfShift && (
          <Card className="state-panel certificate-expiry-report__shift">
            <div role="status">
              <p className="state-panel__title">วันที่อ้างอิงของรายงานเปลี่ยนระหว่างเปลี่ยนหน้า</p>
              <p>
                หน้าก่อนหน้าอ้างอิงวันที่ {formatReportCalendarDate(asOfShift.from)} แต่หน้านี้อ้างอิงวันที่{' '}
                {formatReportCalendarDate(asOfShift.to)} รายการอาจเลื่อน ซ้ำ หรือหายไประหว่างหน้า
              </p>
            </div>
            <button
              type="button"
              className="button button--secondary button--full-width"
              onClick={() => run({ ...applied, page: 1 })}
            >
              กลับไปหน้าแรก
            </button>
          </Card>
        )}
        {renderPartial(report)}
        {renderRows(report)}
        {renderPopulation(report.population)}
      </div>
    )
  }

  return (
    <section className="page certificate-expiry-report">
      <h1>รายงานใบรับรองตามวันหมดอายุ</h1>
      <ul className="certificate-expiry-report__scope">
        {SCOPE_NOTES.map((note) => (
          <li key={note}>{note}</li>
        ))}
        <li>{CERTIFICATE_DESTINATION_NOTE}</li>
      </ul>

      <form className="certificate-expiry-report__form" onSubmit={submit} aria-label="ตัวกรองรายงานใบรับรอง">
        <fieldset className="certificate-expiry-report__modes">
          <legend>รูปแบบรายงาน</legend>
          {MODE_OPTIONS.map((option) => (
            <label key={option.value} className="certificate-expiry-report__mode">
              <input
                type="radio"
                name="certificate-report-mode"
                value={option.value}
                checked={draft.mode === option.value}
                onChange={() => updateDraft({ mode: option.value })}
              />
              {option.label}
            </label>
          ))}
        </fieldset>
        <div className="certificate-expiry-report__fields">
          <FormField label="วันหมดอายุตั้งแต่" htmlFor="certificate-report-from" hint="เว้นว่าง = ไม่จำกัดวันเริ่มต้น">
            <input
              id="certificate-report-from"
              type="date"
              value={draft.expiryFrom}
              disabled={!rangeMode}
              onChange={(event) => updateDraft({ expiryFrom: event.target.value })}
            />
          </FormField>
          <FormField
            label="วันหมดอายุถึง"
            htmlFor="certificate-report-to"
            hint="เว้นว่าง = วันนี้ตามเวลาประเทศไทย ณ เวลาที่โหลดข้อมูล"
          >
            <input
              id="certificate-report-to"
              type="date"
              value={draft.expiryTo}
              disabled={!rangeMode}
              onChange={(event) => updateDraft({ expiryTo: event.target.value })}
            />
          </FormField>
          <button
            type="button"
            className="button button--secondary certificate-expiry-report__dynamic-end"
            disabled={!rangeMode || draft.expiryTo === ''}
            onClick={() => updateDraft({ expiryTo: '' })}
          >
            ใช้วันนี้อัตโนมัติ
          </button>
          <FormField label="สถานะที่คำนวณ" htmlFor="certificate-report-status">
            <select
              id="certificate-report-status"
              value={draft.effectiveStatus}
              onChange={(event) => updateDraft({ effectiveStatus: event.target.value as StatusFilter })}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value || 'ALL'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </FormField>
        </div>
        <div className="certificate-expiry-report__actions">
          <button type="submit" className="button button--primary">
            แสดงรายงาน
          </button>
          <button type="button" className="button button--secondary" onClick={() => run(applied)}>
            โหลดข้อมูลใหม่
          </button>
        </div>
      </form>

      {renderResults()}
    </section>
  )
}
