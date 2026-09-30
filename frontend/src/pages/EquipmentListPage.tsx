import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, type ApiResult } from '../lib/apiClient'
import { duplicateIdsInPage, equipmentDetailLink } from '../lib/equipmentListLinks'
import {
  describeErrorCode,
  equipmentCategoryLabel,
  equipmentStatusLabel,
  equipmentStatusTone,
} from '../lib/labels'
import type { Equipment, EquipmentCategory, Page } from '../lib/types'

const CATEGORY_OPTIONS: EquipmentCategory[] = [
  'LATHE',
  'MILLING',
  'AIR_COMPRESSOR',
  'WELDING',
  'PRESS',
  'DRILL_PRESS',
  'GRINDER',
  'FORKLIFT',
  'OTHER',
]

const PAGE_SIZE = 50

interface Criteria {
  q: string
  category: EquipmentCategory | ''
}

/** The whole request that was sent: criteria plus page. */
interface AppliedRequest extends Criteria {
  page: number
}

const EMPTY_CRITERIA: Criteria = { q: '', category: '' }

/**
 * Every state carries the request that produced it, so the rows, totals,
 * filter echo, pager and retry target always describe the same request
 * (applied atomically from one response).
 */
type LoadState =
  | { kind: 'loading'; request: AppliedRequest }
  | { kind: 'error'; request: AppliedRequest; message: string; requestId?: string | null }
  | { kind: 'ready'; request: AppliedRequest; data: Page<Equipment> }

/** One displayed row; `position` (1-based within the whole result) is the
 * render key, never the equipment id (ids may repeat or be blank). */
interface EquipmentRow {
  item: Equipment
  position: number
  duplicateInPage: boolean
}

const LINK_UNSAFE_NOTE = '(ไม่มีลิงก์: รหัสมีอักขระที่หน้ารายละเอียดยังรองรับไม่ได้)'
const LINK_BLANK_NOTE = '(ไม่มีลิงก์: ไม่มีรหัส)'
const LINK_DUPLICATE_NOTE = '(ไม่มีลิงก์: รหัสนี้ซ้ำกันในหน้านี้)'
const COUNT_NOTE =
  'จำนวนนี้นับตามระเบียนเครื่องมือที่ระบบส่งกลับ ไม่ใช่จำนวนยานพาหนะ และไม่ได้ยืนยันว่าไม่มีรหัสซ้ำ'
const PAGING_NOTE =
  'ข้อมูลอาจเลื่อนหรือซ้ำระหว่างหน้า หากมีการแก้ไขข้อมูลระหว่างดู ลิงก์ไม่ได้รับประกันว่าหน้ารายละเอียดจะเปิดได้'

function buildQuery(request: AppliedRequest): string {
  const params = new URLSearchParams({
    page: String(request.page),
    page_size: String(PAGE_SIZE),
  })
  if (request.q) params.set('q', request.q)
  if (request.category) params.set('category', request.category)
  return params.toString()
}

/** The whole state for one response, built before it is applied. */
function toLoadState(request: AppliedRequest, result: ApiResult<Page<Equipment>>): LoadState {
  if (result.ok) return { kind: 'ready', request, data: result.data }
  const err = result.error
  return {
    kind: 'error',
    request,
    message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
    requestId: err instanceof ApiError ? err.requestId : null,
  }
}

function describeCriteria(request: AppliedRequest): string {
  const parts: string[] = []
  if (request.q) parts.push(`คำค้น "${request.q}"`)
  if (request.category) {
    parts.push(`ประเภท ${equipmentCategoryLabel[request.category] ?? request.category}`)
  }
  return `เงื่อนไขที่ใช้: ${parts.length > 0 ? parts.join(' · ') : 'ไม่กรองเงื่อนไข'}`
}

function renderId({ item, duplicateInPage }: EquipmentRow) {
  const id = item.equipment_id
  const link = duplicateInPage ? null : equipmentDetailLink(id)
  if (link) return <Link to={link}>{id}</Link>
  const note = id.trim() === '' ? LINK_BLANK_NOTE : duplicateInPage ? LINK_DUPLICATE_NOTE : LINK_UNSAFE_NOTE
  return (
    <span className="equipment-list__id">
      <span className="equipment-list__id-text">{id}</span>{' '}
      <span className="equipment-list__note">{note}</span>
    </span>
  )
}

/**
 * Workshop equipment search (Phase 2 page, completed in Phase 7 Batch 7F2).
 * The backend owns filtering, ordering and `total_items`; this page shows
 * one backend page of 50 at a time with explicit paging. Draft form values
 * are separate from the last applied request: editing sends nothing, and
 * "ค้นหา" applies the whole form from page 1. A request-generation guard
 * drops any response that is not the latest request's.
 */
export function EquipmentListPage() {
  const [draft, setDraft] = useState<Criteria>(EMPTY_CRITERIA)
  const [state, setState] = useState<LoadState>({
    kind: 'loading',
    request: { ...EMPTY_CRITERIA, page: 1 },
  })
  const generation = useRef(0)

  const fetchPage = useCallback(async (request: AppliedRequest) => {
    const current = ++generation.current
    const result = await apiGet<Page<Equipment>>(`/equipment?${buildQuery(request)}`)
    if (current !== generation.current) return
    setState(toLoadState(request, result))
  }, [])

  const run = (request: AppliedRequest) => {
    setState({ kind: 'loading', request })
    void fetchPage(request)
  }

  useEffect(() => {
    void fetchPage({ ...EMPTY_CRITERIA, page: 1 })
  }, [fetchPage])

  const renderResults = () => {
    if (state.kind === 'loading') {
      return <LoadingState message="กำลังโหลดรายการเครื่องมือ..." />
    }
    if (state.kind === 'error') {
      return (
        <ErrorState
          title="โหลดรายการเครื่องมือไม่สำเร็จ"
          message={state.message}
          requestId={state.requestId}
          onRetry={() => run(state.request)}
        />
      )
    }

    const { request, data } = state
    const { items, total_items: totalItems, page_size: pageSize, page: currentPage } = data
    const criteria = <p className="equipment-list__applied">{describeCriteria(request)}</p>

    if (totalItems === 0 && items.length === 0) {
      return (
        <>
          {criteria}
          <Card className="state-panel">
            <p className="state-panel__title">ไม่พบเครื่องมือที่ตรงกับเงื่อนไข</p>
            <p>ลองเปลี่ยนคำค้นหาหรือประเภท แล้วกด "ค้นหา"</p>
          </Card>
        </>
      )
    }
    if (items.length === 0) {
      return (
        <>
          {criteria}
          <Card className="state-panel">
            <p className="state-panel__title">ไม่มีรายการในหน้านี้</p>
            <p>ขณะนี้ระบบส่งกลับ {totalItems} รายการตามเงื่อนไขนี้</p>
            <button
              type="button"
              className="button button--secondary button--full-width"
              onClick={() => run({ ...request, page: 1 })}
            >
              กลับไปหน้าแรก
            </button>
          </Card>
        </>
      )
    }

    const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))
    const firstIndex = (currentPage - 1) * pageSize + 1
    const lastIndex = firstIndex + items.length - 1
    const duplicates = duplicateIdsInPage(items.map((item) => item.equipment_id))
    const rows: EquipmentRow[] = items.map((item, index) => ({
      item,
      position: firstIndex + index,
      duplicateInPage: duplicates.has(item.equipment_id),
    }))
    return (
      <>
        {criteria}
        <p className="equipment-list__range" aria-live="polite">
          พบ {totalItems} รายการที่ตรงกับเงื่อนไข · แสดงรายการที่ {firstIndex}–{lastIndex} จาก{' '}
          {totalItems} รายการ
        </p>
        <ResponsiveTable<EquipmentRow>
          columns={[
            { key: 'equipment_id', header: 'รหัส', render: renderId },
            { key: 'name', header: 'ชื่อ', render: ({ item }) => item.name },
            {
              key: 'category',
              header: 'ประเภท',
              render: ({ item }) => equipmentCategoryLabel[item.category] ?? item.category,
            },
            {
              key: 'status',
              header: 'สถานะ',
              render: ({ item }) => (
                <StatusBadge
                  label={equipmentStatusLabel[item.operational_status] ?? item.operational_status}
                  tone={equipmentStatusTone[item.operational_status]}
                />
              ),
            },
          ]}
          rows={rows}
          getRowKey={(row) => `position-${row.position}`}
        />
        <p className="equipment-list__note">{COUNT_NOTE}</p>
        <p className="equipment-list__note">{PAGING_NOTE}</p>
        <nav className="equipment-list__pager" aria-label="เปลี่ยนหน้ารายการเครื่องมือ">
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage <= 1}
            onClick={() => run({ ...request, page: currentPage - 1 })}
          >
            ก่อนหน้า
          </button>
          <span className="equipment-list__page-label">
            หน้า {currentPage} จาก {totalPages}
          </span>
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage >= totalPages}
            onClick={() => run({ ...request, page: currentPage + 1 })}
          >
            ถัดไป
          </button>
        </nav>
      </>
    )
  }

  return (
    <section className="page">
      <h1>เครื่องมือ/อุปกรณ์ซ่อมบำรุง</h1>
      <p>ค้นหาและดูรายการเครื่องมือในโรงซ่อม แตะรายการเพื่อดูรายละเอียด</p>

      <Card>
        <form
          className="form-grid form-grid--two-column"
          onSubmit={(event) => {
            event.preventDefault()
            run({ q: draft.q.trim(), category: draft.category, page: 1 })
          }}
        >
          <FormField label="ค้นหา (ชื่อ หรือ รหัส)" htmlFor="equipment-search-q">
            <input
              id="equipment-search-q"
              type="text"
              value={draft.q}
              onChange={(event) => setDraft({ ...draft, q: event.target.value })}
              placeholder="เช่น เครื่องกลึง"
            />
          </FormField>
          <FormField label="ประเภท" htmlFor="equipment-search-category">
            <select
              id="equipment-search-category"
              value={draft.category}
              onChange={(event) =>
                setDraft({ ...draft, category: event.target.value as EquipmentCategory | '' })
              }
            >
              <option value="">ทั้งหมด</option>
              {CATEGORY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {equipmentCategoryLabel[option]}
                </option>
              ))}
            </select>
          </FormField>
          <div className="equipment-list__actions">
            <button type="submit" className="button button--primary">
              ค้นหา
            </button>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => {
                setDraft(EMPTY_CRITERIA)
                run({ ...EMPTY_CRITERIA, page: 1 })
              }}
            >
              ล้างตัวกรอง
            </button>
          </div>
        </form>
      </Card>

      {renderResults()}
    </section>
  )
}
