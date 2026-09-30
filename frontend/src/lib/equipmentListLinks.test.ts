import { describe, expect, it } from 'vitest'
import { duplicateIdsInPage, equipmentDetailLink } from './equipmentListLinks'

describe('equipmentDetailLink (Phase 7 Batch 7F2, reuses the 7D2 rule)', () => {
  it('links whole-string ASCII-unreserved ids verbatim, keeping leading zeros', () => {
    expect(equipmentDetailLink('EQP-0001')).toBe('/equipment/EQP-0001')
    expect(equipmentDetailLink('000123')).toBe('/equipment/000123')
    expect(equipmentDetailLink('a.b_c~d')).toBe('/equipment/a.b_c~d')
    expect(equipmentDetailLink('...')).toBe('/equipment/...')
  })

  it.each([
    ['blank', ''],
    ['whitespace only', ' '],
    ['leading space', ' EQP-1'],
    ['trailing newline', 'EQP-1\n'],
    ['inner space', 'EQP 1'],
    ['slash', 'a/b'],
    ['backslash', 'a\\b'],
    ['percent sequence', '%2F'],
    ['encoded space', 'EQP%201'],
    ['query delimiter', 'a?b'],
    ['fragment delimiter', 'a#b'],
    ['dot segment', '.'],
    ['double dot segment', '..'],
    ['non-ASCII', 'เครื่อง-1'],
    ['reserved colon', 'a:b'],
  ])('suppresses the link for %s', (_, id) => {
    expect(equipmentDetailLink(id)).toBeNull()
  })
})

describe('duplicateIdsInPage', () => {
  it('reports only ids repeated within the given page', () => {
    expect([...duplicateIdsInPage(['A', 'B', 'A', 'C', 'B', 'A'])].sort()).toEqual(['A', 'B'])
    expect(duplicateIdsInPage(['A', 'B', 'C']).size).toBe(0)
    expect(duplicateIdsInPage([]).size).toBe(0)
  })
})
