import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { ApiError, apiGet } from '../lib/apiClient'
import { assetDetailLink, inspectionDetailLink } from '../lib/inspectionFindingReportLinks'
import {
  assetTypeLabel,
  describeErrorCode,
  formatReportCalendarDate,
  formatReportInstantBangkok,
  inspectionFindingRecordedStatusLabel,
  inspectionFindingReportDefectLabel,
  inspectionFindingReportFlagLabel,
} from '../lib/labels'
import type {
  InspectionFindingReport,
  InspectionFindingReportAssetType,
  InspectionFindingReportFilter,
  InspectionFindingReportItem,
  InspectionFindingReportPopulation,
} from '../lib/types'

const PAGE_SIZE = 50

type AssetTypeFilter = InspectionFindingReportAssetType | ''

/** Filter criteria as the user edits them (draft) or as last submitted
 * (applied). Neither is ever filled from a response. */
interface Criteria {
  assetType: AssetTypeFilter
  createdFrom: string
  createdTo: string
}

interface AppliedRequest extends Criteria {
  page: number
}

const INITIAL_CRITERIA: Criteria = { assetType: '', createdFrom: '', createdTo: '' }

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; title: string; message: string; requestId?: string | null; retry: boolean }
  | { kind: 'ready'; report: InspectionFindingReport }

/** One displayed row. `position` (1-based within the whole result) is the
 * render key — a page position, never a finding id (ids may repeat or be
 * blank). */
interface ReportRow {
  item: InspectionFindingReportItem
  position: number
}

const ASSET_TYPE_OPTIONS: { value: AssetTypeFilter; label: string }[] = [
  { value: '', label: 'ทั้งหมด' },
  { value: 'VEHICLE', label: assetTypeLabel.VEHICLE },
  { value: 'EQUIPMENT', label: assetTypeLabel.EQUIPMENT },
]

const SCOPE_NOTES = [
  "รายงานนี้แสดงข้อบกพร่องที่ระบบบันทึกไว้เมื่อมีรายการตรวจเช็คถูกส่งผลว่า 'ไม่ผ่าน' (รายการที่ไม่ผ่าน 1 รายการ = ข้อบกพร่อง 1 รายการ) เป็นประวัติ ไม่ใช่รายการงานค้าง",
  'สถานะ OPEN คือค่าที่บันทึกไว้ตอนสร้าง ระบบยังไม่มีขั้นตอนปิดหรือแก้ไขข้อบกพร่อง จึงไม่ได้ยืนยันว่ายังชำรุดอยู่',
  'การแจ้งซ่อม การปิดงานซ่อม หรือผลตรวจครั้งหลังที่ผ่าน ไม่เปลี่ยนรายการในรายงานนี้',
  'จำนวนรายการไม่เท่ากับจำนวนครั้งที่ตรวจไม่ผ่าน จำนวนเครื่อง หรือจำนวนข้อบกพร่องที่ยังไม่ได้แก้ไข และไม่ใช่ตัวชี้วัด',
  'การไม่พบรายการ ไม่ได้หมายความว่าได้ตรวจแล้วหรือผ่านการตรวจ',
  'ผลตรวจที่บันทึกไม่สำเร็จครบทุกขั้นตอนอาจไม่ปรากฏในรายงานนี้',
  'ระบบไม่ได้ตรวจสอบว่าข้อมูลปลายทางของลิงก์มีอยู่จริง',
]

const LINK_SUPPRESSED_NOTE = '(ลิงก์ใช้ไม่ได้: รหัสมีอักขระที่หน้าปลายทางยังรองรับไม่ได้)'
const PAGING_NOTE = 'ข้อมูลอาจเลื่อนหรือซ้ำระหว่างหน้า หากมีการบันทึกใหม่ระหว่างดู'

const POPULATION_LABELS: { key: keyof InspectionFindingReportPopulation; label: string }[] = [
  { key: 'read_record_count', label: 'แถวข้อบกพร่องที่อ่านจากระบบทั้งหมด' },
  { key: 'readable_count', label: 'อ่านได้และแสดงในรายงานได้' },
  { key: 'issue_row_count', label: 'อ่านไม่ได้ จึงไม่ได้แสดงในรายงาน' },
]

function buildQuery(request: AppliedRequest): string {
  const params = new URLSearchParams()
  if (request.assetType) params.set('asset_type', request.assetType)
  if (request.createdFrom) params.set('created_from', request.createdFrom)
  if (request.createdTo) params.set('created_to', request.createdTo)
  params.set('page', String(request.page))
  params.set('page_size', String(PAGE_SIZE))
  return params.toString()
}

function validationMessage(err: ApiError): string {
  const errors = (err.details as { errors?: Array<Record<string, unknown>> } | null | undefined)?.errors
  const reason = errors?.[0]?.reason
  if (reason === 'AFTER_CREATED_TO') return 'วันที่เริ่มต้องไม่อยู่หลังวันที่สิ้นสุด'
  if (reason === 'INVALID_DATE') return 'วันที่ไม่ถูกต้อง'
  return 'เงื่อนไขของรายงานไม่ถูกต้อง กรุณาตรวจสอบตัวเลือกอีกครั้ง'
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
    title: code === 'INSPECTION_FINDING_SCHEMA_INVALID' ? 'ไม่แสดงรายงานข้อบกพร่อง' : 'โหลดรายงานข้อบกพร่องไม่สำเร็จ',
    message: describeErrorCode(code),
    requestId,
    retry: true,
  }
}

const isBlank = (value: string) => value.trim() === ''

function describeFilter(filter: InspectionFindingReportFilter): string {
  const assetType = filter.asset_type ? assetTypeLabel[filter.asset_type] : 'ทั้งหมด'
  const from = filter.created_from ? formatReportCalendarDate(filter.created_from) : 'ไม่จำกัดวันเริ่มต้น'
  const to = filter.created_to ? formatReportCalendarDate(filter.created_to) : 'ไม่จำกัดวันสิ้นสุด'
  return `เงื่อนไข: ประเภททรัพย์สิน ${assetType} · วันที่บันทึก (เวลาไทย) ตั้งแต่ ${from} ถึง ${to}`
}

function renderCreatedAt({ item }: ReportRow) {
  return <span className="inspection-finding-report__cell">{formatReportInstantBangkok(item.created_at)}</span>
}

function renderAsset({ item }: ReportRow) {
  const link = assetDetailLink(item.asset_type, item.asset_id)
  return (
    <span className="inspection-finding-report__cell">
      <span className="inspection-finding-report__text">{item.asset_id}</span>
      {link ? (
        <span className="inspection-finding-report__links">
          <Link to={link}>ดูรายละเอียด</Link>
        </span>
      ) : (
        <span className="inspection-finding-report__note">{LINK_SUPPRESSED_NOTE}</span>
      )}
    </span>
  )
}

function renderTitle({ item }: ReportRow) {
  return (
    <span className="inspection-finding-report__cell inspection-finding-report__text">
      {isBlank(item.item_title) ? '(ไม่มีชื่อรายการ)' : item.item_title}
    </span>
  )
}

function renderFindingId({ item }: ReportRow) {
  return (
    <span className="inspection-finding-report__cell inspection-finding-report__text">
      {isBlank(item.finding_id) ? '(ไม่มีรหัสข้อบกพร่อง)' : item.finding_id}
    </span>
  )
}

function renderInspection({ item }: ReportRow) {
  if (isBlank(item.inspection_id)) {
    return <span className="inspection-finding-report__cell">ไม่มีรหัสผลการตรวจ</span>
  }
  const link = inspectionDetailLink(item.inspection_id)
  return (
    <span className="inspection-finding-report__cell">
      <span className="inspection-finding-report__text">{item.inspection_id}</span>
      {link ? (
        <span className="inspection-finding-report__links">
          <Link to={link}>ดูผลการตรวจ</Link>
        </span>
      ) : (
        <span className="inspection-finding-report__note">{LINK_SUPPRESSED_NOTE}</span>
      )}
    </span>
  )
}

function renderFlags({ item }: ReportRow) {
  if (item.flags.length === 0) return <span className="inspection-finding-report__cell">-</span>
  return (
    <ul className="inspection-finding-report__cell inspection-finding-report__flags">
      {item.flags.map((flag) => (
        <li key={flag}>{inspectionFindingReportFlagLabel[flag] ?? flag}</li>
      ))}
    </ul>
  )
}

/**
 * "รายงานข้อบกพร่องจากการตรวจเช็ค (ประวัติที่บันทึก)" — Phase 7 Batch 7E2,
 * read-only GET /reports/inspection-findings (can_view, enforced
 * server-side). Recorded history only: it never states that a defect is
 * still unresolved or is outstanding work.
 *
 * Three separate states: the draft form (editing sends nothing), the
 * applied request (set only by submit — which resets to page 1 — and reused
 * by refresh/paging/retry), and the backend response (rows, totals, filter
 * echo and disclosures, applied together). A request-generation guard
 * applies only the newest request's success or error; loading and errors
 * hide every part of an older response.
 */
export function InspectionFindingReportPage() {
  const [draft, setDraft] = useState<Criteria>(INITIAL_CRITERIA)
  const [applied, setApplied] = useState<AppliedRequest>({ ...INITIAL_CRITERIA, page: 1 })
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const generation = useRef(0)

  // `load` only fetches and applies; `run` (called from event handlers)
  // records the applied request and hides the current response first.
  const load = useCallback(async (request: AppliedRequest) => {
    const current = ++generation.current
    const result = await apiGet<InspectionFindingReport>(`/reports/inspection-findings?${buildQuery(request)}`)
    if (current !== generation.current) return
    setState(result.ok ? { kind: 'ready', report: result.data } : toErrorState(result.error))
  }, [])

  const run = (request: AppliedRequest) => {
    setApplied(request)
    setState({ kind: 'loading' })
    void load(request)
  }

  useEffect(() => {
    // Initial state already holds the default request: no filters, page 1.
    void load({ ...INITIAL_CRITERIA, page: 1 })
  }, [load])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    run({ ...draft, page: 1 })
  }

  const updateDraft = (patch: Partial<Criteria>) => setDraft((current) => ({ ...current, ...patch }))

  const renderPartial = (report: InspectionFindingReport) => {
    if (report.complete) return null
    const issues = report.population.issue_row_count
    const defects = Object.entries(report.data_issues.issue_defect_counts)
    return (
      <Card className="state-panel inspection-finding-report__partial">
        <div role="status">
          <p className="state-panel__title">ข้อมูลไม่ครบ: มี {issues} แถวที่อ่านไม่ได้ จึงไม่แสดงในรายงาน</p>
          <p>แถวที่อ่านไม่ได้อาจตรงกับเงื่อนไขที่เลือก ผลรายงานนี้จึงอาจไม่ครบ กรุณาแจ้งผู้ดูแลระบบ</p>
        </div>
        {defects.length > 0 && (
          <>
            <p className="inspection-finding-report__subheading">ประเภทปัญหา (นับตามปัญหา ไม่ใช่จำนวนรายการ)</p>
            <ul className="inspection-finding-report__list">
              {defects.map(([code, count]) => (
                <li key={code}>
                  {inspectionFindingReportDefectLabel[code] ?? code}: {count}
                </li>
              ))}
            </ul>
          </>
        )}
        {report.data_issues.sample_finding_ids.length > 0 && (
          <p className="inspection-finding-report__text">
            ตัวอย่างรหัสข้อบกพร่องที่อ่านไม่ได้: {report.data_issues.sample_finding_ids.join(', ')}
          </p>
        )}
        {report.data_issues.issue_rows_without_usable_id > 0 && (
          <p>แถวที่อ่านไม่ได้และไม่มีรหัสข้อบกพร่อง: {report.data_issues.issue_rows_without_usable_id}</p>
        )}
      </Card>
    )
  }

  const renderPopulation = (population: InspectionFindingReportPopulation) => (
    <details className="inspection-finding-report__population">
      <summary>จำนวนที่ใช้ประกอบรายงาน (ไม่ใช่ตัวชี้วัด)</summary>
      <dl>
        {POPULATION_LABELS.map(({ key, label }) => (
          <div key={key} className="inspection-finding-report__population-row">
            <dt>{label}</dt>
            <dd>{population[key]}</dd>
          </div>
        ))}
      </dl>
    </details>
  )

  const renderRows = (report: InspectionFindingReport) => {
    const { items, total_items: totalItems, page_size: pageSize } = report
    const currentPage = report.page
    if (totalItems === 0) {
      if (!report.complete) {
        return (
          <Card className="state-panel">
            <p className="state-panel__title">
              ไม่พบรายการที่อ่านได้ตามเงื่อนไข แต่มี {report.population.issue_row_count} แถวที่อ่านไม่ได้
              ซึ่งอาจตรงเงื่อนไข
            </p>
          </Card>
        )
      }
      if (report.population.read_record_count === 0) {
        return (
          <Card className="state-panel">
            <p className="state-panel__title">ยังไม่มีข้อบกพร่องที่บันทึกไว้</p>
            <p>{SCOPE_NOTES[4]}</p>
          </Card>
        )
      }
      return (
        <Card className="state-panel">
          <p className="state-panel__title">ไม่พบข้อบกพร่องที่บันทึกไว้ตามเงื่อนไข</p>
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
        <p className="inspection-finding-report__range" aria-live="polite">
          แสดงรายการที่ {firstIndex}–{lastIndex} จาก {totalItems} รายการข้อบกพร่องที่บันทึกไว้
        </p>
        <ResponsiveTable<ReportRow>
          columns={[
            { key: 'created_at', header: 'วันที่บันทึก (เวลาไทย)', render: renderCreatedAt },
            {
              key: 'asset_type',
              header: 'ประเภททรัพย์สิน',
              render: ({ item }) => (
                <span className="inspection-finding-report__cell">
                  {assetTypeLabel[item.asset_type] ?? item.asset_type}
                </span>
              ),
            },
            { key: 'asset_id', header: 'รหัสทรัพย์สิน', render: renderAsset },
            { key: 'item_title', header: 'รายการตรวจที่ไม่ผ่าน', render: renderTitle },
            { key: 'finding_id', header: 'รหัสข้อบกพร่อง', render: renderFindingId },
            { key: 'inspection', header: 'ผลการตรวจ', render: renderInspection },
            {
              key: 'status',
              header: 'สถานะที่บันทึก',
              render: ({ item }) => (
                <span className="inspection-finding-report__cell">
                  {inspectionFindingRecordedStatusLabel[item.recorded_status] ?? item.recorded_status}
                </span>
              ),
            },
            { key: 'flags', header: 'หมายเหตุข้อมูล', render: renderFlags },
          ]}
          rows={rows}
          getRowKey={(row) => `position-${row.position}`}
        />
        <p className="inspection-finding-report__note">{PAGING_NOTE}</p>
        <nav className="inspection-finding-report__pager" aria-label="เปลี่ยนหน้ารายงานข้อบกพร่อง">
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage <= 1}
            onClick={() => run({ ...applied, page: currentPage - 1 })}
          >
            ก่อนหน้า
          </button>
          <span className="inspection-finding-report__page-label">
            หน้า {currentPage} จาก {totalPages}
          </span>
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage >= totalPages}
            onClick={() => run({ ...applied, page: currentPage + 1 })}
          >
            ถัดไป
          </button>
        </nav>
      </>
    )
  }

  const renderResults = () => {
    if (state.kind === 'loading') return <LoadingState message="กำลังโหลดรายงาน..." />
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
    const { report } = state
    return (
      <div className="inspection-finding-report__result">
        <p className="inspection-finding-report__filter-echo">{describeFilter(report.filter)}</p>
        {renderPartial(report)}
        {renderRows(report)}
        {renderPopulation(report.population)}
      </div>
    )
  }

  return (
    <section className="page inspection-finding-report">
      <h1>รายงานข้อบกพร่องจากการตรวจเช็ค (ประวัติที่บันทึก)</h1>
      <ul className="inspection-finding-report__scope">
        {SCOPE_NOTES.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>

      <form className="inspection-finding-report__form" onSubmit={submit} aria-label="ตัวกรองรายงานข้อบกพร่อง">
        <div className="inspection-finding-report__fields">
          <FormField label="ประเภททรัพย์สิน" htmlFor="finding-report-asset-type">
            <select
              id="finding-report-asset-type"
              value={draft.assetType}
              onChange={(event) => updateDraft({ assetType: event.target.value as AssetTypeFilter })}
            >
              {ASSET_TYPE_OPTIONS.map((option) => (
                <option key={option.value || 'ALL'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </FormField>
          <FormField
            label="บันทึกตั้งแต่วันที่"
            htmlFor="finding-report-from"
            hint="วันที่ตามเวลาไทย รวมวันที่เลือก · เว้นว่าง = ไม่จำกัด"
          >
            <input
              id="finding-report-from"
              type="date"
              value={draft.createdFrom}
              onChange={(event) => updateDraft({ createdFrom: event.target.value })}
            />
          </FormField>
          <FormField label="ถึงวันที่" htmlFor="finding-report-to" hint="วันที่ตามเวลาไทย รวมวันที่เลือก · เว้นว่าง = ไม่จำกัด">
            <input
              id="finding-report-to"
              type="date"
              value={draft.createdTo}
              onChange={(event) => updateDraft({ createdTo: event.target.value })}
            />
          </FormField>
        </div>
        <div className="inspection-finding-report__actions">
          <button type="submit" className="button button--primary">
            แสดงรายงาน
          </button>
          <button type="button" className="button button--secondary" onClick={() => setDraft(INITIAL_CRITERIA)}>
            ล้างเงื่อนไข
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
