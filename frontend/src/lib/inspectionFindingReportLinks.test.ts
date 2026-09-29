import { describe, expect, it } from 'vitest'
import { assetDetailLink, inspectionDetailLink } from './inspectionFindingReportLinks'

// Phase 7 Batch 7E2 (T57) — link eligibility reuses the unchanged 7D2 rule.

describe('inspection findings report links', () => {
  it('links eligible ids verbatim to the existing destination routes, with no query string', () => {
    expect(inspectionDetailLink('INS-0001')).toBe('/inspections/INS-0001')
    expect(inspectionDetailLink('INS.0001_a~b')).toBe('/inspections/INS.0001_a~b')
    expect(assetDetailLink('VEHICLE', 'VEH-1046')).toBe('/vehicle/VEH-1046')
    expect(assetDetailLink('EQUIPMENT', 'EQP-0001')).toBe('/equipment/EQP-0001')
    expect(assetDetailLink('VEHICLE', '0012')).toBe('/vehicle/0012') // leading zeros kept
  })

  it('gives no link for blank, dot, reserved, encoded, Unicode or whitespace-bearing ids', () => {
    for (const id of ['', '   ', '.', '..', 'INS 0010', 'EQP/0002', 'INS%200010', 'ผลตรวจ-1', ' VEH-1047', 'VEH-1047 ',
      'INS-1\n', 'INS?x=1', 'INS#1']) {
      expect(inspectionDetailLink(id)).toBeNull()
      expect(assetDetailLink('VEHICLE', id)).toBeNull()
      expect(assetDetailLink('EQUIPMENT', id)).toBeNull()
    }
  })
})
