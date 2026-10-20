import { describe, expect, it } from 'vitest'
import { bulkEligible, bulkExcluded, employeesForPosition, switchView, toggleDraft, type AccessEmployee } from './accessManagement'

function emp(id: string, caps: string[], extra: Partial<AccessEmployee> = {}): AccessEmployee {
  return { personnel_id: id, name: id, position: 'ช่าง', position_key: 'ช่าง', active: true, is_self: false, is_root: false, exclusion: null, capabilities: caps, ...extra }
}

describe('Access Management helpers (synthetic)', () => {
  const people = [
    emp('A', ['can_view']),
    emp('B', ['can_view']),
    emp('C', []),
    emp('ME', ['can_view'], { is_self: true, exclusion: 'SELF_NOT_EDITABLE' }),
    emp('OLD', ['can_view'], { active: false, exclusion: 'INACTIVE' }),
    emp('D', [], { position: 'คนขับ', position_key: 'คนขับ' }),
  ]

  it('a bulk change reaches every employee the server marks editable; the rest are listed, never dropped', () => {
    expect(bulkEligible(people).map((e) => e.personnel_id)).toEqual(['A', 'B', 'C', 'D'])
    expect(bulkExcluded(people).map((e) => [e.personnel_id, e.exclusion])).toEqual([['ME', 'SELF_NOT_EDITABLE'], ['OLD', 'INACTIVE']])
    // D1/D2: the root holder's own record is editable (no exclusion) and is therefore included.
    expect(bulkEligible([emp('ROOT', [], { is_self: true, is_root: true })])).toHaveLength(1)
    expect(employeesForPosition(people, 'คนขับ').map((e) => e.personnel_id)).toEqual(['D'])
    expect(employeesForPosition(people, '')).toHaveLength(6)
  })

  it('an untouched department switch shows the counts; ON/OFF only when uniform', () => {
    const eligible = bulkEligible(people)
    expect(switchView('can_view', {}, { kind: 'DEPARTMENT', eligible })).toEqual({ kind: 'MIXED', holders: 2, total: 4 })
    expect(switchView('can_manage_pm', {}, { kind: 'DEPARTMENT', eligible })).toEqual({ kind: 'OFF' })
    expect(switchView('can_view', { can_view: false }, { kind: 'DEPARTMENT', eligible })).toEqual({ kind: 'OFF' })
    expect(switchView('can_view', {}, { kind: 'DEPARTMENT', eligible: [] })).toEqual({ kind: 'OFF' })
  })

  it('toggling: mixed → ON; an individual switch set back to its stored value is no change', () => {
    const mixed = { kind: 'MIXED' as const, holders: 2, total: 4 }
    expect(toggleDraft({}, 'can_view', mixed, null)).toEqual({ can_view: true })
    expect(toggleDraft({ can_view: true }, 'can_view', { kind: 'ON' }, null)).toEqual({ can_view: false })
    expect(toggleDraft({}, 'can_view', { kind: 'ON' }, true)).toEqual({ can_view: false })
    expect(toggleDraft({ can_view: false }, 'can_view', { kind: 'OFF' }, true)).toEqual({})
  })
})
