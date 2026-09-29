// Phase 7 Batch 7E2 (T58) — the findings report shows recorded instants in
// Asia/Bangkok regardless of the browser zone. Force a non-Thai process
// zone before any date is formatted in this file (the app tsconfig has no
// Node types, so the Node-only `process` global is reached via globalThis).
;(globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env.TZ =
  'America/Los_Angeles'

import { describe, expect, it } from 'vitest'
import {
  describeErrorCode,
  formatReportInstantBangkok,
  formatThaiDateTime,
  inspectionFindingRecordedStatusLabel,
  inspectionFindingReportDefectLabel,
  inspectionFindingReportFlagLabel,
} from './labels'

describe('formatReportInstantBangkok (findings report only)', () => {
  it('runs under a non-Bangkok process zone', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('America/Los_Angeles')
  })

  it('shows UTC instants as Bangkok date and time, including the next Bangkok day', () => {
    expect(formatReportInstantBangkok('2026-09-28T02:10:00Z')).toBe('28 ก.ย. 2569 09:10')
    expect(formatReportInstantBangkok('2026-09-28T18:30:00Z')).toBe('29 ก.ย. 2569 01:30')
    expect(formatReportInstantBangkok('2026-09-27T16:59:59Z')).toBe('27 ก.ย. 2569 23:59')
    expect(formatReportInstantBangkok('2026-09-28T02:10:00.123456Z')).toBe('28 ก.ย. 2569 09:10')
    expect(formatReportInstantBangkok('2026-09-28T09:10:00+07:00')).toBe('28 ก.ย. 2569 09:10')
    // The legacy formatter is unchanged and still uses the browser zone.
    expect(formatThaiDateTime('2026-09-28T02:10:00Z')).toBe('27 ก.ย. 2569 19:10')
  })

  it('formats the approved representable extremes without throwing', () => {
    expect(formatReportInstantBangkok('9999-12-31T16:59:59Z')).toMatch(/^31 ธ\.ค\. 10542 23:59$/)
    const early = formatReportInstantBangkok('0001-01-01T00:00:00Z')
    expect(early).not.toBe('0001-01-01T00:00:00Z')
    expect(early).toMatch(/544/)
  })

  it('returns text that is not an offset-bearing instant unchanged', () => {
    for (const value of ['', 'x', '2026-09-28', '2026-09-28T02:10:00', '2026-13-01T00:00:00Z']) {
      expect(formatReportInstantBangkok(value)).toBe(value)
    }
  })
})

describe('findings report Thai labels', () => {
  it('labels every flag, defect and the recorded status in Thai without claiming outstanding work', () => {
    expect(Object.keys(inspectionFindingReportFlagLabel).sort()).toEqual(
      ['BLANK_FINDING_ID', 'BLANK_INSPECTION_ID', 'BLANK_RESULT_ID', 'DUPLICATE_FINDING_ID'],
    )
    expect(Object.keys(inspectionFindingReportDefectLabel).sort()).toEqual(
      [
        'BLANK_ASSET_ID', 'BLANK_ASSET_TYPE', 'BLANK_STATUS', 'CREATED_AT_WITHOUT_TIMEZONE', 'INVALID_CREATED_AT',
        'MISSING_CREATED_AT', 'UNMAPPABLE_ROW', 'UNRECOGNIZED_ASSET_TYPE', 'UNRECOGNIZED_STATUS',
        'UNREPRESENTABLE_CREATED_AT', 'UNSUPPORTED_TEXT_VALUE',
      ],
    )
    const all = [inspectionFindingReportFlagLabel, inspectionFindingReportDefectLabel].flatMap(Object.values)
    for (const text of all) {
      expect(text).toMatch(/[฀-๿]/)
      expect(text).not.toMatch(/_[A-Z]/)
      expect(text).not.toMatch(/ค้าง|ยังไม่ได้แก้ไข|แก้ไขแล้ว/)
    }
    expect(inspectionFindingRecordedStatusLabel.OPEN).toBe('OPEN (ค่าที่บันทึก)')
    expect(describeErrorCode('INSPECTION_FINDING_SCHEMA_INVALID')).toBe('โครงสร้างตารางข้อบกพร่องไม่ถูกต้อง จึงแสดงรายงานไม่ได้')
    expect(describeErrorCode('INSPECTION_FINDING_READ_FAILED')).toBe('อ่านข้อมูลข้อบกพร่องไม่สำเร็จ กรุณาลองใหม่')
  })
})
