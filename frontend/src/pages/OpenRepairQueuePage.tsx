import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { ApiError, apiGet } from '../lib/apiClient'
import { assetTypeLabel, describeErrorCode, formatRepairReportOpenedAt } from '../lib/labels'
import type { AssetType, Page, RepairSummary } from '../lib/types'

const PAGE_SIZE = 50

type AssetFilter = AssetType | ''

const ASSET_FILTERS: { value: AssetFilter; label: string }[] = [
  { value: '', label: 'ทั้งหมด' },
  { value: 'VEHICLE', label: 'ยานพาหนะ' },
  { value: 'EQUIPMENT', label: 'เครื่องมือ/อุปกรณ์' },
]

const DUPLICATE_ID_NOTE = 'เลขที่ใบงานซ้ำในข้อมูล — เปิดรายละเอียดจากรายการนี้ไม่ได้'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'denied' }
  | { kind: 'error'; title: string; message: string; requestId?: string | null }
  | {
      kind: 'ready'
      items: RepairSummary[]
      page: number
      pageSize: number
      totalItems: number
      assetType: AssetFilter
    }

/** One displayed row: `position` (1-based, within the whole result) is the
 * render key — a page position, never a record identity. */
interface ReportRow {
  repair: RepairSummary
  position: number
  duplicateId: boolean
}

function toErrorState(err: ApiError | Error): LoadState {
  if (err instanceof ApiError && err.status === 403) return { kind: 'denied' }
  const code = err instanceof ApiError ? err.code : undefined
  return {
    kind: 'error',
    title: code === 'REPAIR_ORDER_SCHEMA_INVALID' ? 'ไม่แสดงรายการงานซ่อมค้าง' : 'โหลดงานซ่อมค้างไม่สำเร็จ',
    message: describeErrorCode(code),
    requestId: err instanceof ApiError ? err.requestId : null,
  }
}

function toReadyState(data: Page<RepairSummary>, assetType: AssetFilter): LoadState {
  return {
    kind: 'ready',
    items: data.items,
    page: data.page,
    pageSize: data.page_size,
    totalItems: data.total_items,
    assetType,
  }
}

function buildQuery(assetType: AssetFilter, page: number): string {
  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  if (assetType) params.set('asset_type', assetType)
  return params.toString()
}

const isBlank = (value: string) => value.trim() === ''

function toRows(items: RepairSummary[], firstPosition: number): ReportRow[] {
  // Only duplicates within this displayed page can be detected; ids are
  // compared exactly as returned (no trimming or case folding).
  const occurrences = new Map<string, number>()
  for (const item of items) {
    if (!isBlank(item.repair_id)) {
      occurrences.set(item.repair_id, (occurrences.get(item.repair_id) ?? 0) + 1)
    }
  }
  return items.map((repair, index) => ({
    repair,
    position: firstPosition + index,
    duplicateId: (occurrences.get(repair.repair_id) ?? 0) > 1,
  }))
}

function renderRepairId({ repair, duplicateId }: ReportRow) {
  if (isBlank(repair.repair_id)) return '(ไม่มีเลขที่ใบงาน)'
  if (duplicateId) {
    return (
      <span className="open-repair-report__cell">
        {repair.repair_id}
        <span className="open-repair-report__duplicate-note">{DUPLICATE_ID_NOTE}</span>
      </span>
    )
  }
  return (
    <Link className="open-repair-report__cell" to={`/repairs/${encodeURIComponent(repair.repair_id)}`}>
      {repair.repair_id}
    </Link>
  )
}

function renderAsset({ repair }: ReportRow) {
  const label = assetTypeLabel[repair.asset_type] ?? repair.asset_type
  if (isBlank(repair.asset_id)) {
    return <span className="open-repair-report__cell">{`${label} (ไม่มีรหัสสินทรัพย์)`}</span>
  }
  const base =
    repair.asset_type === 'VEHICLE' ? '/vehicle' : repair.asset_type === 'EQUIPMENT' ? '/equipment' : null
  const text = `${label} ${repair.asset_id}`
  if (!base) return <span className="open-repair-report__cell">{text}</span>
  return (
    <Link className="open-repair-report__cell" to={`${base}/${encodeURIComponent(repair.asset_id)}`}>
      {text}
    </Link>
  )
}

/**
 * "งานซ่อมค้าง" — Phase 7 Batch 7C2 open-repair report on the existing
 * GET /repairs/open-queue (can_manage_repair only, enforced server-side).
 * Counts repair WORK ORDERS the backend classifies as OPEN — never Repair
 * Requests and never distinct vehicles. One page-owned GET per load,
 * filter change, page change or refresh; the latest request generation
 * wins for success and error alike, and rows/totals are hidden while a
 * request is in flight or after an error.
 */
export function OpenRepairQueuePage() {
  const [assetType, setAssetType] = useState<AssetFilter>('')
  const [page, setPage] = useState(1)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const generation = useRef(0)

  // `load` only fetches and applies the result; `reload` (called from
  // event handlers) hides the current rows by showing loading first.
  const load = useCallback(async (filter: AssetFilter, targetPage: number) => {
    const current = ++generation.current
    const result = await apiGet<Page<RepairSummary>>(`/repairs/open-queue?${buildQuery(filter, targetPage)}`)
    if (current !== generation.current) return
    setState(result.ok ? toReadyState(result.data, filter) : toErrorState(result.error))
  }, [])

  const reload = (filter: AssetFilter, targetPage: number) => {
    setAssetType(filter)
    setPage(targetPage)
    setState({ kind: 'loading' })
    void load(filter, targetPage)
  }

  useEffect(() => {
    // Initial state already holds the unfiltered first page.
    void load('', 1)
  }, [load])

  const renderResults = () => {
    if (state.kind === 'loading') return <LoadingState message="กำลังโหลดงานซ่อมค้าง..." />
    if (state.kind === 'denied') {
      return <PermissionDeniedState message="หน้านี้สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุงเท่านั้น" />
    }
    if (state.kind === 'error') {
      return (
        <ErrorState
          title={state.title}
          message={state.message}
          requestId={state.requestId}
          onRetry={() => reload(assetType, page)}
        />
      )
    }

    const { items, totalItems, pageSize } = state
    const currentPage = state.page
    const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))

    if (totalItems === 0) {
      return state.assetType ? (
        <Card className="state-panel">
          <p className="state-panel__title">ไม่พบใบงานซ่อมที่ยังไม่ปิดงานสำหรับประเภทสินทรัพย์นี้</p>
        </Card>
      ) : (
        <EmptyState
          title="ระบบไม่พบใบงานซ่อมที่ยังไม่ปิดงาน"
          description="ไม่มีใบงานซ่อมที่ตรงเงื่อนไขส่งกลับจากระบบ รายการแจ้งซ่อมที่รอตรวจรับแสดงแยกที่ “แจ้งซ่อมรอตรวจรับ”"
        />
      )
    }

    if (items.length === 0) {
      // The page is past the end (data changed since the last request).
      return (
        <Card className="state-panel">
          <p className="state-panel__title">หน้านี้ไม่มีรายการแล้ว</p>
          <p>ข้อมูลอาจเปลี่ยนไประหว่างเปลี่ยนหน้า ขณะนี้ระบบส่งกลับ {totalItems} ใบงานตามเงื่อนไขนี้</p>
          <button
            type="button"
            className="button button--secondary button--full-width"
            onClick={() => reload(state.assetType, 1)}
          >
            กลับไปหน้าแรก
          </button>
        </Card>
      )
    }

    const firstIndex = (currentPage - 1) * pageSize + 1
    const lastIndex = firstIndex + items.length - 1
    const rows = toRows(items, firstIndex)

    return (
      <>
        <p className="open-repair-report__range" aria-live="polite">
          แสดงรายการที่ {firstIndex}–{lastIndex} จาก {totalItems} ใบงานที่ระบบส่งกลับ
        </p>
        <ResponsiveTable<ReportRow>
          columns={[
            { key: 'repair_id', header: 'เลขที่ใบงานซ่อม', render: renderRepairId },
            {
              key: 'opened_at',
              header: 'วันที่เปิดใบงาน',
              render: ({ repair }) => (
                <span className="open-repair-report__cell">{formatRepairReportOpenedAt(repair.opened_at)}</span>
              ),
            },
            { key: 'asset', header: 'สินทรัพย์', render: renderAsset },
            {
              key: 'symptom',
              header: 'อาการ/ปัญหาที่พบ',
              render: ({ repair }) => <span className="open-repair-report__cell">{repair.symptom ?? '-'}</span>,
            },
            {
              key: 'assignment',
              header: 'ผู้รับผิดชอบ (ตามที่บันทึกในใบงาน)',
              render: ({ repair }) => (
                <span className="open-repair-report__cell">
                  {repair.primary_technician
                    ? `${repair.primary_technician}${repair.collaborators.length ? ` +${repair.collaborators.length}` : ''}`
                    : 'ยังไม่มอบหมาย'}
                </span>
              ),
            },
          ]}
          rows={rows}
          getRowKey={(row) => `position-${row.position}`}
        />
        <nav className="open-repair-report__pager" aria-label="เปลี่ยนหน้ารายการงานซ่อมค้าง">
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage <= 1}
            onClick={() => reload(state.assetType, currentPage - 1)}
          >
            ก่อนหน้า
          </button>
          <span className="open-repair-report__page-label">
            หน้า {currentPage} จาก {totalPages}
          </span>
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage >= totalPages}
            onClick={() => reload(state.assetType, currentPage + 1)}
          >
            ถัดไป
          </button>
        </nav>
      </>
    )
  }

  return (
    <section className="page open-repair-report">
      <h1>งานซ่อมค้าง</h1>
      <p>
        รายการใบงานซ่อมที่ระบบจัดเป็น “ยังไม่ปิดงาน” ทั้งยานพาหนะและเครื่องมือ/อุปกรณ์
        สำหรับผู้มีสิทธิ์ดูแลงานซ่อมบำรุง
      </p>
      <ul className="open-repair-report__scope">
        <li>นับเป็นจำนวนใบงานซ่อม ไม่ใช่จำนวนคัน รถหนึ่งคันอาจมีหลายใบงาน</li>
        <li>“ยังไม่ปิดงาน” เป็นการจัดประเภทของระบบ ไม่ได้ยืนยันสภาพจริงของเครื่อง</li>
        <li>
          ใบงานที่ช่องสถานะว่างจะถูกจัดเป็น “ยังไม่ปิดงาน”
          และใบงานที่ไม่ได้ระบุประเภทสินทรัพย์จะแสดงเป็นยานพาหนะ ตามค่าเริ่มต้นของระบบเดิม
        </li>
        <li>
          ไม่รวมรายการแจ้งซ่อมที่ยังรอตรวจรับ — ดูที่{' '}
          <Link to="/repair-request-queue">“แจ้งซ่อมรอตรวจรับ”</Link>
        </li>
        <li>
          เวลาที่มีเขตเวลากำกับจะแสดงตามเวลาประเทศไทย
          ส่วนข้อมูลที่ไม่ระบุเขตเวลาจะแสดงตามที่บันทึกพร้อมคำกำกับ
        </li>
      </ul>

      <div className="open-repair-report__toolbar">
        <FormField label="ประเภทสินทรัพย์" htmlFor="open-repair-asset-type">
          <select
            id="open-repair-asset-type"
            value={assetType}
            onChange={(event) => reload(event.target.value as AssetFilter, 1)}
          >
            {ASSET_FILTERS.map((option) => (
              <option key={option.value || 'ALL'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>
        <button type="button" className="button button--secondary" onClick={() => reload(assetType, page)}>
          โหลดข้อมูลใหม่
        </button>
      </div>

      {renderResults()}
    </section>
  )
}
