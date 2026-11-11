import { describe, expect, it } from 'vitest'
import {
  COUNTER_ROWS,
  PARTIAL_TEXT,
  UNKNOWN_TEXT,
  allowedActions,
  basisText,
  isUncertain,
  newRequestId,
  policyText,
  quantityText,
  reasonText,
} from './partLifetime'
import type { UsageQuantity } from './types'

const q = (over: Partial<UsageQuantity>): UsageQuantity => ({ value: null, quality: 'UNKNOWN', policy_state: null,
  reasons: [], ...over })

describe('partLifetime helpers (R6 FINAL §9)', () => {
  it('renders a number only for KNOWN; UNKNOWN / PARTIAL never become 0', () => {
    expect(quantityText(q({ value: 3200, quality: 'KNOWN' }))).toBe('3,200')
    expect(quantityText(q({ value: 0, quality: 'KNOWN' }))).toBe('0')
    expect(quantityText(q({ value: null, quality: 'UNKNOWN' }))).toBe(UNKNOWN_TEXT)
    expect(quantityText(q({ value: 0, quality: 'UNKNOWN' }))).toBe(UNKNOWN_TEXT)
    expect(quantityText(q({ value: 100, quality: 'PARTIAL_RECORDED' }))).toBe(PARTIAL_TEXT)
    expect(quantityText(undefined)).toBe(UNKNOWN_TEXT)
  })

  it('keeps the four counter rows distinct and verified rows first', () => {
    expect(COUNTER_ROWS.map((r) => r.key)).toEqual(['verified_lifetime_total', 'verified_current_cycle',
      'tracked_since_enrollment', 'tracked_in_current_cycle'])
    expect(COUNTER_ROWS[0].label).toContain('ยืนยันแล้ว')
    expect(COUNTER_ROWS[2].label).not.toContain('ยืนยันแล้ว')
  })

  it('labels policy states and reasons from the API, hiding APPROVED', () => {
    expect(policyText('PENDING')).toBe('รอการกำหนดนโยบาย')
    expect(policyText('TEST_PROPOSED')).toBe('ค่าทดสอบตามข้อเสนอ')
    expect(policyText('APPROVED')).toBeNull()
    expect(reasonText(['METER_EVIDENCE_MISSING'])).toBe('ยังไม่มีค่ามาตรวัดที่ยืนยันได้')
    expect(reasonText(['SOMETHING_NEW'])).toBe('SOMETHING_NEW')
    expect(basisText({ basis: { counter_type: 'ENGINE_HOUR', component_role: 'CARRIER_ENGINE' } } as never))
      .toBe('ชั่วโมงเครื่องยนต์ล่าง')
  })

  it('follows the A-1 matrix: no direct install from IN_REPAIR or REMOVED; SCRAPPED is terminal', () => {
    expect(allowedActions('IN_REPAIR')).toMatchObject({ install: false, returnFromRepair: true,
      statusMoves: ['SCRAPPED'] })
    expect(allowedActions('REMOVED').install).toBe(false)
    expect(allowedActions('STOCK').install).toBe(true)
    expect(allowedActions('INSTALLED')).toMatchObject({ remove: true, transfer: true, statusMoves: [] })
    expect(allowedActions('SCRAPPED')).toMatchObject({ install: false, remove: false, statusMoves: [] })
  })

  it('classifies uncertain outcomes and makes fresh UUID intents', () => {
    expect(isUncertain(undefined)).toBe(true)
    expect(isUncertain(503)).toBe(true)
    expect(isUncertain(409)).toBe(false)
    const a = newRequestId()
    expect(a).toMatch(/^[0-9a-f-]{36}$/)
    expect(newRequestId()).not.toBe(a)
  })
})
