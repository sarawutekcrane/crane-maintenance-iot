import { describe, expect, it } from 'vitest'
import {
  NOT_IN_SCHEMA_TEXT,
  NOT_RECORDED_TEXT,
  type ReferenceLoad,
  registryText,
  resolveCode,
  resolveField,
  resolveOptionalCode,
} from './referenceResolution'

// Phase 7 Batch 7O2a — contract Final Rev2 §7.1/§7.2 resolution vocabulary.
// Synthetic codes only.

const ready: ReferenceLoad = {
  kind: 'ready',
  byCode: new Map([
    ['TH-21', { name: 'ระยอง', isActive: true }],
    ['TH-76', { name: 'เพชรบุรี', isActive: false }],
  ]),
}

describe('reference resolution', () => {
  it('resolves a loaded code to its name, marking inactive entries', () => {
    expect(resolveCode('TH-21', ready)).toEqual({ resolution: 'RESOLVED', text: 'ระยอง' })
    expect(resolveCode('TH-76', ready)).toEqual({ resolution: 'RESOLVED', text: 'เพชรบุรี (ไม่ใช้งาน)' })
  })

  it('says UNKNOWN_CODE only when the list loaded successfully', () => {
    expect(resolveCode('TH-99', ready)).toEqual({ resolution: 'UNKNOWN_CODE', text: 'รหัสไม่อยู่ในทะเบียน (TH-99)' })
  })

  it('never says "not in the registry" when the list is unavailable or loading', () => {
    const down = resolveCode('TH-99', { kind: 'unavailable' })
    expect(down).toEqual({ resolution: 'REFERENCE_UNAVAILABLE', text: 'TH-99 (ไม่สามารถโหลดชื่อได้)' })
    expect(down.text).not.toContain('ไม่อยู่ในทะเบียน')
    const loading = resolveCode('TH-99', { kind: 'loading' })
    expect(loading.resolution).toBe('REFERENCE_LOADING')
    expect(loading.text).not.toContain('ไม่อยู่ในทะเบียน')
  })

  it('distinguishes a missing column from a blank value', () => {
    expect(resolveField({ state: 'NOT_IN_SCHEMA', value: null }, ready).text).toBe(NOT_IN_SCHEMA_TEXT)
    expect(resolveField({ state: 'NOT_RECORDED', value: null }, ready).text).toBe(NOT_RECORDED_TEXT)
    expect(NOT_IN_SCHEMA_TEXT).not.toBe(NOT_RECORDED_TEXT)
    // An older response without `registry` reads as "not in the source".
    expect(resolveField(undefined, ready).text).toBe(NOT_IN_SCHEMA_TEXT)
    expect(registryText(undefined).text).toBe(NOT_IN_SCHEMA_TEXT)
  })

  it('shows recorded registration text exactly', () => {
    for (const value of ['0012', ' กข 1234 ', '1,234', 'AB-01']) {
      expect(registryText({ state: 'RECORDED', value })).toEqual({ resolution: 'RESOLVED', text: value })
    }
  })

  it('resolves nullable history codes with a caller-chosen none text', () => {
    expect(resolveOptionalCode(null, ready, 'ไม่มี')).toBe('ไม่มี')
    expect(resolveOptionalCode('TH-21', ready)).toBe('ระยอง')
  })
})
