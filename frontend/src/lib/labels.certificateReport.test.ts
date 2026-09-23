// Phase 7 Batch 7D2 — the certificate report's calendar-date formatter must
// not shift valid dates in a browser WEST of UTC. Force a non-Thai process
// zone before any date is formatted in this file (the app tsconfig has no
// Node types, so the Node-only `process` global is reached via globalThis).
;(globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env.TZ =
  'America/Los_Angeles'

import { describe, expect, it } from 'vitest'
import {
  certificateExpiryPositionLabel,
  certificateReportDefectLabel,
  certificateReportFlagLabel,
  certificateStatusLabel,
  describeErrorCode,
  formatReportCalendarDate,
  formatThaiDate,
} from './labels'

describe('formatReportCalendarDate (certificate report only)', () => {
  it('runs under a zone where local midnight parsing would shift the day', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('America/Los_Angeles')
    expect(new Date('2026-01-15').getDate()).toBe(14)
  })

  it('shows valid calendar dates on the same day, including leap day and year ends', () => {
    expect(formatReportCalendarDate('2026-01-15')).toBe('15 ม.ค. 2569')
    expect(formatReportCalendarDate('2028-02-29')).toBe('29 ก.พ. 2571')
    expect(formatReportCalendarDate('2026-12-31')).toBe('31 ธ.ค. 2569')
    expect(formatReportCalendarDate('2026-01-01')).toBe('1 ม.ค. 2569')
  })

  it('returns impossible or non-calendar text unchanged', () => {
    for (const value of ['2026-02-30', '2027-02-29', '2026-13-01', '2026-1-5', '20260115', '2026-01-15T00:00:00Z', '', 'x']) {
      expect(formatReportCalendarDate(value)).toBe(value)
    }
  })

  it('leaves the legacy formatThaiDate unchanged (it still uses the browser zone)', () => {
    expect(formatThaiDate('2026-01-15')).toBe('14 ม.ค. 2569')
  })
})

describe('certificate report Thai labels', () => {
  it('labels every flag, defect and expiry position as observations in Thai', () => {
    const flags = [
      'SAME_TYPE_ACTIVE_EXISTS', 'MULTIPLE_ACTIVE_SAME_TYPE', 'STORED_ACTIVE_PAST_EXPIRY',
      'STORED_EXPIRED_EXPIRY_NOT_BEFORE_TODAY', 'LINK_PRESENT_ON_NON_REPLACED', 'DUPLICATE_CERTIFICATE_ID',
      'BLANK_CERTIFICATE_ID', 'BLANK_VEHICLE_ID',
    ]
    expect(Object.keys(certificateReportFlagLabel).sort()).toEqual([...flags].sort())
    expect(Object.keys(certificateReportDefectLabel).sort()).toEqual(['INVALID_EXPIRY_DATE', 'UNMAPPABLE_ROW', 'UNRECOGNIZED_STATUS'])
    expect(Object.keys(certificateExpiryPositionLabel).sort()).toEqual(['AFTER_TODAY', 'BEFORE_TODAY', 'NO_EXPIRY_DATE', 'TODAY'])
    const all = [certificateReportFlagLabel, certificateReportDefectLabel, certificateExpiryPositionLabel].flatMap(Object.values)
    for (const text of all) {
      expect(text).toMatch(/[฀-๿]/)
      expect(text).not.toMatch(/_[A-Z]/)
      expect(text).not.toMatch(/ถูกต้องตามกฎหมาย|ครบถ้วนตามกฎหมาย/)
    }
    expect(certificateReportFlagLabel.SAME_TYPE_ACTIVE_EXISTS).toContain('ไม่ได้ยืนยันว่าเป็นใบแทน')
  })

  it('reuses the existing certificate status labels and adds the two report error messages', () => {
    expect(certificateStatusLabel).toEqual({ ACTIVE: 'ยังใช้งานได้', REPLACED: 'ถูกแทนที่แล้ว', EXPIRED: 'หมดอายุ' })
    expect(describeErrorCode('VEHICLE_CERTIFICATE_SCHEMA_INVALID')).toBe(
      'โครงสร้างข้อมูลใบรับรองไม่ถูกต้อง จึงไม่แสดงรายงานเพื่อป้องกันผลที่คลาดเคลื่อน กรุณาแจ้งผู้ดูแลระบบ',
    )
    expect(describeErrorCode('VEHICLE_CERTIFICATE_READ_FAILED')).toBe(
      'ไม่สามารถอ่านข้อมูลใบรับรองได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
    )
  })
})
