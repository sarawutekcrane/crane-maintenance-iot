/**
 * Phase 7 Batch 7O2a — registry display and reference resolution (contract
 * Final Rev2 §7.1, §7.2). One vocabulary on every page:
 *
 * - RESOLVED: the list loaded and the code is in it → its name
 *   (an inactive entry adds "(ไม่ใช้งาน)");
 * - UNKNOWN_CODE: the list loaded successfully and the code is absent;
 * - REFERENCE_UNAVAILABLE: the list request failed → the raw code, never
 *   "code does not exist";
 * - NOT_APPLICABLE: nothing recorded ("ยังไม่ได้บันทึก") or the source has
 *   no such column ("แหล่งข้อมูลยังไม่มีช่องนี้") — two different states.
 *
 * Stored text is shown exactly as returned (no trim or case change).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from './apiClient'
import type { BranchReference, ProvinceReference, ReferenceList, RegistryField } from './types'

export const NOT_RECORDED_TEXT = 'ยังไม่ได้บันทึก'
export const NOT_IN_SCHEMA_TEXT = 'แหล่งข้อมูลยังไม่มีช่องนี้'
export const INACTIVE_SUFFIX = '(ไม่ใช้งาน)'
export const NAME_UNAVAILABLE_TEXT = 'ไม่สามารถโหลดชื่อได้'
export const NAME_LOADING_TEXT = 'กำลังโหลดชื่อ...'

export interface ReferenceEntry {
  name: string
  isActive: boolean
}

/** One reference list as loaded on this page view. */
export type ReferenceLoad =
  | { kind: 'loading' }
  | { kind: 'ready'; byCode: Map<string, ReferenceEntry> }
  | { kind: 'unavailable' }

export type Resolution = 'RESOLVED' | 'UNKNOWN_CODE' | 'REFERENCE_UNAVAILABLE' | 'REFERENCE_LOADING' | 'NOT_APPLICABLE'

export interface ResolvedText {
  resolution: Resolution
  text: string
}

/** A missing `registry` (an older response shape) reads as NOT_IN_SCHEMA. */
const ABSENT: RegistryField = { state: 'NOT_IN_SCHEMA', value: null }

function notApplicable(field: RegistryField): ResolvedText {
  return {
    resolution: 'NOT_APPLICABLE',
    text: field.state === 'NOT_IN_SCHEMA' ? NOT_IN_SCHEMA_TEXT : NOT_RECORDED_TEXT,
  }
}

/** A free-text registry field (registration number): exact text or a state text. */
export function registryText(field: RegistryField | undefined): ResolvedText {
  const f = field ?? ABSENT
  if (f.state !== 'RECORDED' || f.value === null) return notApplicable(f)
  return { resolution: 'RESOLVED', text: f.value }
}

/** Resolve a stored code (province, branch) against its reference list. */
export function resolveCode(code: string, reference: ReferenceLoad): ResolvedText {
  if (reference.kind === 'loading') return { resolution: 'REFERENCE_LOADING', text: `${code} (${NAME_LOADING_TEXT})` }
  if (reference.kind === 'unavailable') {
    return { resolution: 'REFERENCE_UNAVAILABLE', text: `${code} (${NAME_UNAVAILABLE_TEXT})` }
  }
  const entry = reference.byCode.get(code)
  if (!entry) return { resolution: 'UNKNOWN_CODE', text: `รหัสไม่อยู่ในทะเบียน (${code})` }
  return { resolution: 'RESOLVED', text: entry.isActive ? entry.name : `${entry.name} ${INACTIVE_SUFFIX}` }
}

export function resolveField(field: RegistryField | undefined, reference: ReferenceLoad): ResolvedText {
  const f = field ?? ABSENT
  if (f.state !== 'RECORDED' || f.value === null) return notApplicable(f)
  return resolveCode(f.value, reference)
}

/** A nullable code from a history row: null means "none / unknown". */
export function resolveOptionalCode(code: string | null, reference: ReferenceLoad, noneText = 'ไม่ทราบ/ไม่มี'): string {
  return code === null ? noneText : resolveCode(code, reference).text
}

function byCode<T>(items: T[], code: (item: T) => string, entry: (item: T) => ReferenceEntry): Map<string, ReferenceEntry> {
  return new Map(items.map((item) => [code(item), entry(item)]))
}

/** A 200 reference body is used only when every item has the contracted
 * runtime shape (code and name strings, boolean is_active); otherwise the
 * list is treated as unavailable (7O2a review fix), never as a partial Map. */
function isList<T>(data: unknown, code: keyof T & string, name: keyof T & string): data is ReferenceList<T> {
  if (typeof data !== 'object' || data === null) return false
  const items = (data as { items?: unknown }).items
  return (
    Array.isArray(items) &&
    items.every((item) => {
      if (typeof item !== 'object' || item === null) return false
      const row = item as Record<string, unknown>
      return typeof row[code] === 'string' && typeof row[name] === 'string' && typeof row.is_active === 'boolean'
    })
  )
}

export interface ReferenceLists {
  branches: ReferenceLoad
  provinces: ReferenceLoad
  /** Re-request every list that is not loaded; never touches filters. */
  retry: () => void
}

/**
 * GET /branches and GET /provinces once per page view (§7.2), each with its
 * own state. A late response after unmount, or an older response after a
 * retry, is ignored. A failure only makes names unavailable: callers keep
 * any applied filter unchanged.
 */
export function useReferenceLists(): ReferenceLists {
  const [branches, setBranches] = useState<ReferenceLoad>({ kind: 'loading' })
  const [provinces, setProvinces] = useState<ReferenceLoad>({ kind: 'loading' })
  const generation = useRef({ branches: 0, provinces: 0 })
  const mounted = useRef(true)

  // The initial state is `loading`; only a retry shows loading again.
  const loadBranches = useCallback(async () => {
    const mine = ++generation.current.branches
    const result = await apiGet<ReferenceList<BranchReference>>('/branches')
    if (!mounted.current || mine !== generation.current.branches) return
    setBranches(
      result.ok && isList<BranchReference>(result.data, 'branch_id', 'branch_name')
        ? {
            kind: 'ready',
            byCode: byCode(
              result.data.items,
              (b) => b.branch_id,
              (b) => ({ name: b.branch_name, isActive: b.is_active }),
            ),
          }
        : { kind: 'unavailable' },
    )
  }, [])

  const loadProvinces = useCallback(async () => {
    const mine = ++generation.current.provinces
    const result = await apiGet<ReferenceList<ProvinceReference>>('/provinces')
    if (!mounted.current || mine !== generation.current.provinces) return
    setProvinces(
      result.ok && isList<ProvinceReference>(result.data, 'province_code', 'province_name_th')
        ? {
            kind: 'ready',
            byCode: byCode(
              result.data.items,
              (p) => p.province_code,
              (p) => ({ name: p.province_name_th, isActive: p.is_active }),
            ),
          }
        : { kind: 'unavailable' },
    )
  }, [])

  useEffect(() => {
    mounted.current = true
    void loadBranches()
    void loadProvinces()
    return () => {
      mounted.current = false
    }
  }, [loadBranches, loadProvinces])

  const retry = useCallback(() => {
    if (branches.kind === 'unavailable') {
      setBranches({ kind: 'loading' })
      void loadBranches()
    }
    if (provinces.kind === 'unavailable') {
      setProvinces({ kind: 'loading' })
      void loadProvinces()
    }
  }, [branches.kind, provinces.kind, loadBranches, loadProvinces])

  return { branches, provinces, retry }
}
