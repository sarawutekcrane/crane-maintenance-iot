import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, type ApiResult } from '../lib/apiClient'
import { describeErrorCode, operationalStatusLabel, operationalStatusTone } from '../lib/labels'
import type {
  InspectionFinding,
  OperationalStatus,
  Page,
  PmWorkOrderSummary,
  RepairSummary,
  Vehicle,
  VehicleModel,
} from '../lib/types'

const STATUS_FILTERS: OperationalStatus[] = [
  'WORKING',
  'READY',
  'MAINTENANCE',
  'OUT_OF_SERVICE',
  'LONG_TERM_PARKING',
]

const VEHICLE_PAGE_SIZE = 50
// Backend maximum page_size for /models, /repairs and /pm/work-orders.
const MODEL_PAGE_SIZE = 200
const INDICATOR_PAGE_SIZE = 200

interface Filters {
  q: string
  status: OperationalStatus | ''
  modelId: string
}

const EMPTY_FILTERS: Filters = { q: '', status: '', modelId: '' }

type VehicleState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | {
      kind: 'ready'
      vehicles: Vehicle[]
      page: number
      pageSize: number
      totalItems: number
    }

/**
 * One indicator category (open repairs, open PM work orders, open
 * findings). A failed or truncated read is never treated as "zero":
 * only `complete` carries counts, and only when the response proves the
 * whole requested result set was returned.
 */
type CategoryState =
  | { kind: 'loading' }
  | { kind: 'failed' }
  | { kind: 'incomplete' }
  | { kind: 'complete'; counts: Map<string, number> }

type CategoryKey = 'repair' | 'pm' | 'finding'

type IndicatorState = Record<CategoryKey, CategoryState>

const CATEGORY_KEYS: CategoryKey[] = ['repair', 'pm', 'finding']

const CATEGORY_LABEL: Record<CategoryKey, string> = {
  repair: 'งานซ่อมที่เปิด',
  pm: 'ใบงาน PM ที่เปิด',
  finding: 'ข้อบกพร่องที่ค้าง',
}

const LOADING_INDICATORS: IndicatorState = {
  repair: { kind: 'loading' },
  pm: { kind: 'loading' },
  finding: { kind: 'loading' },
}

type ModelOptionsState = {
  models: VehicleModel[]
  loadedPages: number
  totalItems: number | null
  loading: boolean
  failed: boolean
}

function countByAssetId<T extends { asset_id: string }>(items: T[]): Map<string, number> {
  const counts = new Map<string, number>()
  for (const item of items) {
    counts.set(item.asset_id, (counts.get(item.asset_id) ?? 0) + 1)
  }
  return counts
}

function pagedCategory<T extends { asset_id: string }>(result: ApiResult<Page<T>>): CategoryState {
  if (!result.ok) return { kind: 'failed' }
  const { items, page, total_items } = result.data
  // Only a first page that already holds every matching record is complete.
  if (page !== 1 || items.length < total_items) return { kind: 'incomplete' }
  return { kind: 'complete', counts: countByAssetId(items) }
}

function listCategory<T extends { asset_id: string }>(result: ApiResult<T[]>): CategoryState {
  // /findings is an unpaginated list: a successful response is the whole set.
  if (!result.ok) return { kind: 'failed' }
  return { kind: 'complete', counts: countByAssetId(result.data) }
}

function toVehicleState(result: ApiResult<Page<Vehicle>>): VehicleState {
  if (!result.ok) {
    const err = result.error
    return {
      kind: 'error',
      message: err instanceof ApiError ? describeErrorCode(err.code) : 'โหลดข้อมูลไม่สำเร็จ',
      requestId: err instanceof ApiError ? err.requestId : null,
    }
  }
  return {
    kind: 'ready',
    vehicles: result.data.items,
    page: result.data.page,
    pageSize: result.data.page_size,
    totalItems: result.data.total_items,
  }
}

function mergeModelPage(
  prev: ModelOptionsState,
  result: ApiResult<Page<VehicleModel>>,
  targetPage: number,
): ModelOptionsState {
  // A failed page keeps every option (and the selection) already loaded.
  if (!result.ok) return { ...prev, loading: false, failed: true }
  const known = new Set(prev.models.map((m) => m.model_id))
  const added = result.data.items.filter((m) => !known.has(m.model_id))
  return {
    models: [...prev.models, ...added],
    loadedPages: targetPage,
    totalItems: result.data.total_items,
    loading: false,
    failed: false,
  }
}

function buildVehicleQuery(filters: Filters, page: number): string {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(VEHICLE_PAGE_SIZE),
  })
  if (filters.q) params.set('q', filters.q)
  if (filters.status) params.set('status', filters.status)
  if (filters.modelId) params.set('model_id', filters.modelId)
  return params.toString()
}

function hasFilters(filters: Filters): boolean {
  return Boolean(filters.q || filters.status || filters.modelId)
}

export function VehicleListPage() {
  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS)
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [vehicleState, setVehicleState] = useState<VehicleState>({ kind: 'loading' })
  const [indicators, setIndicators] = useState<IndicatorState>(LOADING_INDICATORS)
  const [modelOptions, setModelOptions] = useState<ModelOptionsState>({
    models: [],
    loadedPages: 0,
    totalItems: null,
    loading: true,
    failed: false,
  })

  // Request generations: a response is applied only if no newer request
  // of the same kind was started after it, so a slow obsolete response can
  // never overwrite newer results, errors or page metadata.
  const vehicleGeneration = useRef(0)
  const indicatorGeneration = useRef(0)
  const modelGeneration = useRef(0)

  const loadIndicators = useCallback(async () => {
    const generation = ++indicatorGeneration.current

    // One list call per category (never one call per vehicle row).
    const [repairsResult, pmResult, findingsResult] = await Promise.all([
      apiGet<Page<RepairSummary>>(
        `/repairs?asset_type=VEHICLE&status=OPEN&page_size=${INDICATOR_PAGE_SIZE}`,
      ),
      apiGet<Page<PmWorkOrderSummary>>(
        `/pm/work-orders?asset_type=VEHICLE&status=OPEN&page_size=${INDICATOR_PAGE_SIZE}`,
      ),
      apiGet<InspectionFinding[]>('/findings?asset_type=VEHICLE&status=OPEN'),
    ])
    if (generation !== indicatorGeneration.current) return

    setIndicators({
      repair: pagedCategory(repairsResult),
      pm: pagedCategory(pmResult),
      finding: listCategory(findingsResult),
    })
  }, [])

  const loadVehicles = useCallback(async (filters: Filters, targetPage: number) => {
    const generation = ++vehicleGeneration.current

    const result = await apiGet<Page<Vehicle>>(`/vehicles?${buildVehicleQuery(filters, targetPage)}`)
    if (generation !== vehicleGeneration.current) return

    setVehicleState(toVehicleState(result))
  }, [])

  const loadModelPage = useCallback(async (targetPage: number) => {
    const generation = ++modelGeneration.current

    const result = await apiGet<Page<VehicleModel>>(
      `/models?page=${targetPage}&page_size=${MODEL_PAGE_SIZE}`,
    )
    if (generation !== modelGeneration.current) return

    setModelOptions((prev) => mergeModelPage(prev, result, targetPage))
  }, [])

  // The load* functions only fetch and apply results; these wrappers
  // (called from event handlers) show the loading state first.
  const reloadVehicles = (filters: Filters, targetPage: number) => {
    setVehicleState({ kind: 'loading' })
    void loadVehicles(filters, targetPage)
  }

  const reloadIndicators = () => {
    setIndicators(LOADING_INDICATORS)
    void loadIndicators()
  }

  const requestModelPage = (targetPage: number) => {
    setModelOptions((prev) => ({ ...prev, loading: true, failed: false }))
    void loadModelPage(targetPage)
  }

  const search = (filters: Filters, targetPage: number) => {
    setApplied(filters)
    setPage(targetPage)
    reloadVehicles(filters, targetPage)
    reloadIndicators()
  }

  useEffect(() => {
    // Initial state already holds the empty filters on page 1.
    void loadVehicles(EMPTY_FILTERS, 1)
    void loadIndicators()
    void loadModelPage(1)
  }, [loadVehicles, loadIndicators, loadModelPage])

  // Any apply action commits the whole form, so the draft and the applied
  // filters are identical right after every search.
  const applyFilters = (next: Filters) => {
    const normalized = { ...next, q: next.q.trim() }
    setDraft(normalized)
    search(normalized, 1)
  }

  const modelNameById = new Map(modelOptions.models.map((m) => [m.model_id, m.model_name]))
  const modelLabel = (modelId: string) => modelNameById.get(modelId) ?? modelId
  const moreModelsAvailable =
    modelOptions.totalItems !== null && modelOptions.models.length < modelOptions.totalItems
  const draftQueryPending = draft.q.trim() !== applied.q

  const unknownCategories = CATEGORY_KEYS.filter((key) => indicators[key].kind !== 'complete')
  const failedCategories = CATEGORY_KEYS.filter((key) => indicators[key].kind === 'failed')
  const indicatorsLoading = CATEGORY_KEYS.some((key) => indicators[key].kind === 'loading')

  const appliedSummary = [
    applied.q ? `คำค้น “${applied.q}”` : null,
    applied.status ? `สถานะ ${operationalStatusLabel[applied.status]}` : null,
    applied.modelId ? `รุ่น ${modelLabel(applied.modelId)}` : null,
  ].filter(Boolean)

  const renderIndicators = (vehicle: Vehicle) => {
    if (indicatorsLoading) {
      return <span className="vehicle-indicators__none">กำลังโหลดสรุปงาน...</span>
    }
    const positive: { key: CategoryKey; count: number }[] = []
    const zero: CategoryKey[] = []
    for (const key of CATEGORY_KEYS) {
      const category = indicators[key]
      if (category.kind !== 'complete') continue
      const count = category.counts.get(vehicle.vehicle_id) ?? 0
      if (count > 0) positive.push({ key, count })
      else zero.push(key)
    }

    if (zero.length === CATEGORY_KEYS.length) {
      return (
        <span className="vehicle-indicators__none">
          ไม่พบงานซ่อม/ใบงาน PM ที่เปิด หรือข้อบกพร่องที่ค้าง
        </span>
      )
    }

    const linkFor: Record<CategoryKey, string> = {
      repair: `/vehicle/${vehicle.vehicle_id}/repairs`,
      pm: `/vehicle/${vehicle.vehicle_id}/pm`,
      finding: `/vehicle/${vehicle.vehicle_id}/inspections`,
    }
    const badgeText: Record<CategoryKey, (count: number) => string> = {
      repair: (count) => `ซ่อม ${count}`,
      pm: (count) => `ใบงาน PM ${count}`,
      finding: (count) => `ข้อบกพร่อง ${count}`,
    }

    return (
      <div className="vehicle-indicators">
        {positive.map(({ key, count }) => (
          <Link
            key={key}
            to={linkFor[key]}
            className={`vehicle-indicators__badge vehicle-indicators__badge--${key}`}
          >
            {badgeText[key](count)}
          </Link>
        ))}
        {zero.length > 0 && (
          <span className="vehicle-indicators__none vehicle-indicators__line">
            ไม่พบ{zero.map((key) => CATEGORY_LABEL[key]).join(', ')}
          </span>
        )}
        {unknownCategories.length > 0 && (
          <span className="vehicle-indicators__unknown vehicle-indicators__line">
            ยังไม่ทราบจำนวน: {unknownCategories.map((key) => CATEGORY_LABEL[key]).join(', ')}
          </span>
        )}
      </div>
    )
  }

  const renderResults = () => {
    if (vehicleState.kind === 'loading') {
      return <LoadingState message="กำลังโหลดรายการยานพาหนะ..." />
    }
    if (vehicleState.kind === 'error') {
      return (
        <ErrorState
          title="โหลดรายการยานพาหนะไม่สำเร็จ"
          message={vehicleState.message}
          requestId={vehicleState.requestId}
          onRetry={() => reloadVehicles(applied, page)}
        />
      )
    }

    const { vehicles, totalItems, pageSize } = vehicleState
    const currentPage = vehicleState.page
    const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))

    if (totalItems === 0) {
      return (
        <EmptyState
          title="ไม่พบยานพาหนะ"
          description={
            hasFilters(applied)
              ? 'ไม่มีรถที่ตรงกับเงื่อนไขที่เลือก ลองเปลี่ยนคำค้นหาหรือล้างตัวกรอง'
              : 'ยังไม่มีรายการรถในระบบ'
          }
        />
      )
    }

    if (vehicles.length === 0) {
      // The page is past the end (data changed since the last request).
      return (
        <Card className="state-panel">
          <p className="state-panel__title">หน้านี้ไม่มีรายการแล้ว</p>
          <p>ข้อมูลอาจเปลี่ยนไประหว่างเปลี่ยนหน้า พบ {totalItems} คันตามเงื่อนไขนี้</p>
          <button
            type="button"
            className="button button--secondary button--full-width"
            onClick={() => search(applied, 1)}
          >
            กลับไปหน้าแรก
          </button>
        </Card>
      )
    }

    const firstIndex = (currentPage - 1) * pageSize + 1
    const lastIndex = firstIndex + vehicles.length - 1

    return (
      <>
        <p className="vehicle-list__range" aria-live="polite">
          แสดงรายการที่ {firstIndex}–{lastIndex} จาก {totalItems} คันที่ตรงกับเงื่อนไข
        </p>
        <ResponsiveTable
          columns={[
            {
              key: 'vehicle_id',
              header: 'รหัสยานพาหนะ',
              render: (vehicle) => (
                <Link to={`/vehicle/${vehicle.vehicle_id}`}>{vehicle.vehicle_id}</Link>
              ),
            },
            { key: 'machine_no', header: 'เลขเครื่องจักร', render: (v) => v.machine_no },
            { key: 'model', header: 'รุ่น', render: (v) => modelLabel(v.model_id) },
            {
              key: 'status',
              header: 'สถานะ',
              render: (v) => (
                <StatusBadge
                  label={operationalStatusLabel[v.operational_status] ?? v.operational_status}
                  tone={operationalStatusTone[v.operational_status]}
                />
              ),
            },
            { key: 'indicators', header: 'สรุปงานที่เปิด', render: renderIndicators },
          ]}
          rows={vehicles}
          getRowKey={(v) => v.vehicle_id}
        />
        <nav className="vehicle-list__pager" aria-label="เปลี่ยนหน้ารายการยานพาหนะ">
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage <= 1}
            onClick={() => search(applied, currentPage - 1)}
          >
            ก่อนหน้า
          </button>
          <span className="vehicle-list__page-label">
            หน้า {currentPage} จาก {totalPages}
          </span>
          <button
            type="button"
            className="button button--secondary"
            disabled={currentPage >= totalPages}
            onClick={() => search(applied, currentPage + 1)}
          >
            ถัดไป
          </button>
        </nav>
      </>
    )
  }

  return (
    <section className="page">
      <h1>ยานพาหนะ</h1>
      <p>ค้นหาและดูรายการรถเครนในระบบ แตะรายการเพื่อดูรายละเอียด</p>

      <Card>
        <form
          className="form-grid form-grid--two-column"
          onSubmit={(event) => {
            event.preventDefault()
            applyFilters(draft)
          }}
        >
          <FormField label="ค้นหา (เลขเครื่องจักร หรือ รหัสยานพาหนะ)" htmlFor="vehicle-search-q">
            <input
              id="vehicle-search-q"
              type="text"
              value={draft.q}
              onChange={(event) => setDraft({ ...draft, q: event.target.value })}
              placeholder="เช่น TC-12"
            />
          </FormField>
          <FormField label="สถานะ" htmlFor="vehicle-search-status">
            <select
              id="vehicle-search-status"
              value={draft.status}
              onChange={(event) =>
                applyFilters({ ...draft, status: event.target.value as OperationalStatus | '' })
              }
            >
              <option value="">ทั้งหมด</option>
              {STATUS_FILTERS.map((status) => (
                <option key={status} value={status}>
                  {operationalStatusLabel[status]}
                </option>
              ))}
            </select>
          </FormField>
          <FormField
            label="รุ่น"
            htmlFor="vehicle-search-model"
            hint={
              modelOptions.totalItems !== null
                ? `โหลดรายการรุ่นแล้ว ${modelOptions.models.length} จาก ${modelOptions.totalItems} รุ่น`
                : undefined
            }
          >
            <select
              id="vehicle-search-model"
              value={draft.modelId}
              onChange={(event) => applyFilters({ ...draft, modelId: event.target.value })}
            >
              <option value="">ทุกรุ่น</option>
              {draft.modelId && !modelNameById.has(draft.modelId) && (
                <option value={draft.modelId}>{draft.modelId}</option>
              )}
              {modelOptions.models.map((model) => (
                <option key={model.model_id} value={model.model_id}>
                  {model.model_name}
                </option>
              ))}
            </select>
          </FormField>
          <div className="vehicle-list__model-actions">
            {modelOptions.failed && (
              <p className="form-field__error" role="alert">
                โหลดรายการรุ่นไม่สำเร็จ ยังค้นหาด้วยเงื่อนไขอื่นได้
              </p>
            )}
            {(modelOptions.failed || moreModelsAvailable) && (
              <button
                type="button"
                className="button button--secondary button--full-width"
                disabled={modelOptions.loading}
                onClick={() => requestModelPage(modelOptions.loadedPages + 1)}
              >
                {modelOptions.failed ? 'ลองโหลดรายการรุ่นอีกครั้ง' : 'โหลดรายการรุ่นเพิ่ม'}
              </button>
            )}
          </div>
          <div className="vehicle-list__form-actions">
            <button type="submit" className="button button--primary button--full-width">
              ค้นหา
            </button>
            <button
              type="button"
              className="button button--secondary button--full-width"
              disabled={!hasFilters(applied) && !hasFilters(draft)}
              onClick={() => applyFilters(EMPTY_FILTERS)}
            >
              ล้างตัวกรอง
            </button>
          </div>
        </form>
        <p className="vehicle-list__applied" aria-live="polite">
          {appliedSummary.length > 0
            ? `เงื่อนไขที่ใช้: ${appliedSummary.join(' · ')}`
            : 'เงื่อนไขที่ใช้: ไม่มีตัวกรอง (แสดงรถทุกคันในรายการ)'}
        </p>
        {draftQueryPending && (
          <p className="form-field__hint">คำค้นหาที่พิมพ์ยังไม่ถูกใช้ กดปุ่ม “ค้นหา” เพื่อใช้</p>
        )}
      </Card>

      {vehicleState.kind === 'ready' && vehicleState.totalItems > 0 && (
        <Card className="state-panel vehicle-list__indicator-note">
          <p>
            สรุปงานนับเฉพาะงานซ่อมที่เปิด ใบงาน PM ที่เปิด และข้อบกพร่องที่ค้าง
            ไม่ได้บอกกำหนด PM อายุชิ้นส่วน ใบรับรองหมดอายุ หรือสถานะออฟไลน์
          </p>
          {!indicatorsLoading && unknownCategories.length > 0 && (
            <div role="status">
              {unknownCategories.map((key) => (
                <p key={key} className="vehicle-indicators__unknown">
                  {CATEGORY_LABEL[key]}:{' '}
                  {indicators[key].kind === 'failed'
                    ? 'โหลดข้อมูลไม่สำเร็จ'
                    : 'ข้อมูลยังไม่ครบ (มีรายการมากกว่าที่โหลดได้ในครั้งเดียว) จึงไม่แสดงจำนวน'}
                </p>
              ))}
            </div>
          )}
          {!indicatorsLoading && failedCategories.length > 0 && (
            <button
              type="button"
              className="button button--secondary button--full-width"
              onClick={reloadIndicators}
            >
              ลองโหลดสรุปงานอีกครั้ง
            </button>
          )}
        </Card>
      )}

      {renderResults()}
    </section>
  )
}
