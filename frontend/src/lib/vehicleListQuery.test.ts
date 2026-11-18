import { describe, expect, it } from 'vitest'
import {
  EMPTY_VEHICLE_LIST_QUERY,
  readVehicleListQuery,
  safeListFrom,
  vehicleListHref,
  vehicleListParams,
} from './vehicleListQuery'

// R8 (R8-01 / R8-02): URL-backed vehicle list state. Synthetic values only.
describe('vehicleListQuery', () => {
  it('reads every supported filter exactly and round-trips through the URL', () => {
    const params = new URLSearchParams('q=TC-12&status=READY&model_id=MODEL-1&branch_id=BR-A&has_open_alert=true&page=3')
    const query = readVehicleListQuery(params)
    expect(query).toEqual({ q: 'TC-12', status: 'READY', modelId: 'MODEL-1', branchId: 'BR-A', hasOpenAlert: true, page: 3 })
    expect(readVehicleListQuery(vehicleListParams(query))).toEqual(query)
  })

  it.each([
    ['status=BOGUS', { status: '' }],
    ['status=ready', { status: '' }],
    ['page=0', { page: 1 }],
    ['page=-3', { page: 1 }],
    ['page=2.5', { page: 1 }],
    ['page=abc', { page: 1 }],
    ['has_open_alert=TRUE', { hasOpenAlert: false }],
    ['has_open_alert=1', { hasOpenAlert: false }],
    [`branch_id=${'B'.repeat(101)}`, { branchId: '' }],
  ])('ignores the invalid value %s (never coerced)', (search, expected) => {
    expect(readVehicleListQuery(new URLSearchParams(search))).toEqual({ ...EMPTY_VEHICLE_LIST_QUERY, ...expected })
  })

  it('builds drill-through links with only the given filters', () => {
    expect(vehicleListHref({})).toBe('/vehicles')
    expect(vehicleListHref({ status: 'READY' })).toBe('/vehicles?status=READY')
    expect(vehicleListHref({ status: 'WORKING', branchId: 'BR-A' })).toBe('/vehicles?status=WORKING&branch_id=BR-A')
    expect(vehicleListHref({ page: 1 })).toBe('/vehicles')
  })

  it.each([
    [undefined, '/vehicles'],
    [42, '/vehicles'],
    ['https://evil.example/vehicles', '/vehicles'],
    ['//evil.example/vehicles', '/vehicles'],
    ['/vehicles/../admin', '/vehicles'],
    ['/vehiclesx', '/vehicles'],
    ['/vehicles?status=READY#x', '/vehicles'],
    ['/vehicles?a=\\b', '/vehicles'],
    ['/vehicles', '/vehicles'],
    ['/vehicles?status=READY&page=2', '/vehicles?status=READY&page=2'],
  ])('accepts only a same-app vehicle list as the back target: %s', (from, expected) => {
    expect(safeListFrom(from)).toBe(expected)
  })
})
