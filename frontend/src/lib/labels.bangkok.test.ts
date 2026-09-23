// Phase 7 Batch 7C2 — the open-repair report's opened-at formatter must not
// depend on the browser's time zone. Force a non-Thai process zone (UTC-8/-7)
// before any date is formatted in this file. (The app tsconfig has no Node
// types, so the Node-only `process` global is reached through globalThis.)
;(globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env.TZ =
  'America/Los_Angeles'

import { describe, expect, it } from 'vitest'
import {
  formatRepairReportOpenedAt,
  formatThaiDateTime,
  REPORT_OPENED_AT_UNREADABLE,
  REPORT_TIMEZONE_UNSPECIFIED,
} from './labels'

describe('formatRepairReportOpenedAt (open-repair report only)', () => {
  it('runs under a non-Bangkok process time zone', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('America/Los_Angeles')
    // Sanity: the browser-local interpretation differs from Bangkok here.
    expect(new Date('2026-01-15T02:15:00Z').getHours()).toBe(18)
  })

  it('shows offset-bearing instants in Asia/Bangkok, not browser-local time', () => {
    expect(formatRepairReportOpenedAt('2026-01-15T02:15:00Z')).toBe('15 ม.ค. 2569 09:15')
    expect(formatRepairReportOpenedAt('2026-01-15T02:15:00+00:00')).toBe('15 ม.ค. 2569 09:15')
    expect(formatRepairReportOpenedAt('2026-01-15T02:15:00.123456Z')).toBe('15 ม.ค. 2569 09:15')
  })

  it('handles date rollover into the next Bangkok day and year', () => {
    expect(formatRepairReportOpenedAt('2026-01-15T20:30:00Z')).toBe('16 ม.ค. 2569 03:30')
    expect(formatRepairReportOpenedAt('2025-12-31T17:30:00Z')).toBe('1 ม.ค. 2569 00:30')
  })

  it('respects explicit non-UTC offsets', () => {
    expect(formatRepairReportOpenedAt('2026-01-15T09:15:00+07:00')).toBe('15 ม.ค. 2569 09:15')
    expect(formatRepairReportOpenedAt('2026-01-14T18:15:00-08:00')).toBe('15 ม.ค. 2569 09:15')
    expect(formatRepairReportOpenedAt('2026-01-15T07:45:00+0530')).toBe('15 ม.ค. 2569 09:15')
  })

  it('shows timezone-less text as stored, with a label, never reinterpreted', () => {
    expect(formatRepairReportOpenedAt('2026-01-15T08:00:00')).toBe(`2026-01-15T08:00:00 ${REPORT_TIMEZONE_UNSPECIFIED}`)
    expect(formatRepairReportOpenedAt('2026-01-15')).toBe('2026-01-15 (ไม่ระบุเขตเวลา)')
    // A naive midnight-1970 value is not an instant: it is labelled, not hidden.
    expect(formatRepairReportOpenedAt('1970-01-01T00:00:00')).toBe('1970-01-01T00:00:00 (ไม่ระบุเขตเวลา)')
  })

  it('shows the no-readable-date text only for the exact 1970-01-01T00:00:00Z instant', () => {
    expect(REPORT_OPENED_AT_UNREADABLE).toBe('ไม่มีวันที่เปิดใบงานที่อ่านได้')
    for (const epoch of [
      '1970-01-01T00:00:00Z',
      '1970-01-01T00:00:00+00:00',
      '1970-01-01T00:00:00.000Z',
      '1970-01-01T07:00:00+07:00',
      '1969-12-31T16:00:00-08:00',
    ]) {
      expect(formatRepairReportOpenedAt(epoch)).toBe(REPORT_OPENED_AT_UNREADABLE)
    }
    expect(formatRepairReportOpenedAt('1970-01-01T00:00:01Z')).toBe('1 ม.ค. 2513 07:00')
    expect(formatRepairReportOpenedAt('')).toBe(REPORT_OPENED_AT_UNREADABLE)
  })

  it('returns unparseable or impossible text raw', () => {
    for (const raw of ['not-a-date', '15/01/2026 08:00', '2026-02-30T00:00:00Z', '2026-01-15T25:00:00Z', '2026-01-15T08:00:00+25:00', '<b>x</b>']) {
      expect(formatRepairReportOpenedAt(raw)).toBe(raw)
    }
  })
})

describe('formatThaiDateTime (other pages) is unchanged', () => {
  it('still formats in the process-local zone without an explicit time zone', () => {
    const iso = '2026-01-15T02:15:00Z'
    const legacy = new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))
    expect(formatThaiDateTime(iso)).toBe(legacy)
    expect(formatThaiDateTime(iso)).toBe('14 ม.ค. 2569 18:15')
  })
})
