import { describe, expect, it } from 'vitest'
import { certificateReportLinks, isLinkableVehicleId } from './certificateReportLinks'

// Phase 7 Batch 7D2 — conservative link eligibility (synthetic ids only).

describe('certificate report link eligibility', () => {
  it('links ids made only of ASCII unreserved characters, verbatim and without query strings', () => {
    for (const id of ['VEH-1046', 'SYN_1', 'a.b', 'x~y', '0042', 'A', '...', '.a', 'a..']) {
      expect(isLinkableVehicleId(id)).toBe(true)
      expect(certificateReportLinks(id)).toEqual({
        vehicleDetail: `/vehicle/${id}`,
        vehicleCertificates: `/vehicle/${id}/certificates`,
      })
    }
  })

  it('rejects "." and ".." (path segments the router would resolve)', () => {
    expect(certificateReportLinks('.')).toBeNull()
    expect(certificateReportLinks('..')).toBeNull()
  })

  it('checks the whole string, rejecting trailing newlines and control characters', () => {
    for (const id of ['VEH-1\n', '\nVEH-1', 'VEH-1\r', 'VEH\t1', 'VEH-1\u0000', 'VEH-1\u007f', 'VEH-1 ']) {
      expect(isLinkableVehicleId(id)).toBe(false)
    }
  })

  it('rejects blank, whitespace, Unicode and reserved/percent characters', () => {
    for (const id of [
      '', ' ', 'VEH 1', ' VEH-1', 'VEH-1 ', 'รถ-1', 'Café', 'VEH‐1', 'Ｖ1',
      'VEH/1', 'VEH?1', 'VEH#1', 'VEH%201', 'VEH&1', 'VEH+1', 'VEH:1', 'VEH;1', 'VEH=1',
      'VEH@1', 'VEH,1', "VEH'1", 'VEH"1', 'VEH<1>', 'VEH\\1', 'VEH[1]', 'VEH(1)', 'VEH!1', 'VEH*1', 'VEH$1',
    ]) {
      expect(isLinkableVehicleId(id)).toBe(false)
      expect(certificateReportLinks(id)).toBeNull()
    }
  })
})
