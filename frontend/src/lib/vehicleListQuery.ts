/**
 * R8 (R8-01 / R8-02, Owner source approval 2026-11-18) — the vehicle list's
 * filters and page in the URL, so a dashboard card can open a pre-filtered
 * list and returning from a vehicle restores the same list.
 *
 * Rules (fail closed, never coerce):
 * - an unknown status, a non-positive or non-integer page, a blank or too-long
 *   value, or any `has_open_alert` other than exactly "true" is IGNORED (the
 *   default applies) — it is never mapped to a near value;
 * - `safeListFrom` accepts only a same-app `/vehicles` path (no scheme, no host,
 *   no `//`, no backslash), so a crafted link can never redirect elsewhere.
 * `lib/listQuery.ts` (personnel / department lists) is deliberately unchanged.
 */
import type { OperationalStatus } from './types'

export const VEHICLE_LIST_STATUSES: readonly OperationalStatus[] = [
  'WORKING',
  'READY',
  'MAINTENANCE',
  'OUT_OF_SERVICE',
  'LONG_TERM_PARKING',
]

export interface VehicleListQuery {
  q: string
  status: OperationalStatus | ''
  modelId: string
  branchId: string
  /** S5: only vehicles with an open alert (trusted can_view readers only). */
  hasOpenAlert: boolean
  page: number
}

export const EMPTY_VEHICLE_LIST_QUERY: VehicleListQuery = {
  q: '',
  status: '',
  modelId: '',
  branchId: '',
  hasOpenAlert: false,
  page: 1,
}

const MAX_VALUE_LENGTH = 100

function boundedText(raw: string | null): string {
  if (raw === null) return ''
  return raw.length > MAX_VALUE_LENGTH ? '' : raw
}

function isStatus(value: string): value is OperationalStatus {
  return (VEHICLE_LIST_STATUSES as readonly string[]).includes(value)
}

export function readVehicleListQuery(params: URLSearchParams): VehicleListQuery {
  const rawStatus = params.get('status') ?? ''
  const rawPage = params.get('page')
  const page = rawPage !== null && /^[1-9]\d{0,5}$/.test(rawPage) ? Number(rawPage) : 1
  return {
    q: boundedText(params.get('q')).trim(),
    status: isStatus(rawStatus) ? rawStatus : '',
    modelId: boundedText(params.get('model_id')),
    branchId: boundedText(params.get('branch_id')),
    hasOpenAlert: params.get('has_open_alert') === 'true',
    page,
  }
}

export function vehicleListParams(query: VehicleListQuery): URLSearchParams {
  const params = new URLSearchParams()
  if (query.q) params.set('q', query.q)
  if (query.status) params.set('status', query.status)
  if (query.modelId) params.set('model_id', query.modelId)
  if (query.branchId) params.set('branch_id', query.branchId)
  if (query.hasOpenAlert) params.set('has_open_alert', 'true')
  if (query.page > 1) params.set('page', String(query.page))
  return params
}

/** The list URL of a query (e.g. a dashboard card's drill-through link). */
export function vehicleListHref(query: Partial<VehicleListQuery>): string {
  const search = vehicleListParams({ ...EMPTY_VEHICLE_LIST_QUERY, ...query }).toString()
  return search ? `/vehicles?${search}` : '/vehicles'
}

/** A validated "back to the list" target, or `/vehicles` when absent/unsafe. */
export function safeListFrom(from: unknown): string {
  if (typeof from !== 'string') return '/vehicles'
  if (!/^\/vehicles(\?[^#\\]*)?$/.test(from)) return '/vehicles'
  return from
}
