import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../lib/apiClient'
import type { AssetType, Equipment, Page, Vehicle } from '../lib/types'

interface AssetSearchSelectProps {
  id: string
  assetType: AssetType
  assetId: string
  onChangeAssetId: (assetId: string) => void
}

interface AssetOption {
  assetId: string
  displayLabel: string
}

const SEARCH_DEBOUNCE_MS = 300

/**
 * The outcome of one search, tagged with the search cycle it belongs to.
 * A new cycle starts on EVERY input transition (query edit, asset type
 * change, selection made or cleared), even when the input returns to an
 * earlier text or type, so a stored result is shown only if it was made
 * in the current cycle — never revived because the text matches again.
 */
type SearchState =
  | { kind: 'loading'; cycle: number }
  | { kind: 'failed'; cycle: number }
  | { kind: 'ready'; cycle: number; options: AssetOption[] }

async function searchAssets(assetType: AssetType, query: string): Promise<AssetOption[] | null> {
  const params = new URLSearchParams({ page_size: '10' })
  if (query.trim()) params.set('q', query.trim())
  if (assetType === 'VEHICLE') {
    const result = await apiGet<Page<Vehicle>>(`/vehicles?${params.toString()}`)
    if (!result.ok) return null
    return result.data.items.map((v) => ({
      assetId: v.vehicle_id,
      displayLabel: `${v.vehicle_id} — ${v.machine_no}`,
    }))
  }
  const result = await apiGet<Page<Equipment>>(`/equipment?${params.toString()}`)
  if (!result.ok) return null
  return result.data.items.map((e) => ({
    assetId: e.equipment_id,
    displayLabel: `${e.equipment_id} — ${e.name}`,
  }))
}

/**
 * Core Demo Fixes, PART INSTANCE / LIFETIME CORRECTIONS: "Asset selection
 * for install/transfer should use searchable/selectable known assets
 * instead of requiring manual raw ID typing in the normal UI." Searches
 * the same vehicle/equipment list endpoints the Vehicle/Equipment list
 * pages already use — never invents a new asset directory.
 *
 * Web/API Phase 7 Batch 7G2 (DEC-8(b)): only the latest search is applied
 * (request generation), results are shown only for the current search
 * cycle so earlier options disappear as soon as the input changes (during
 * the debounce, not only when the next request starts) and are never
 * revived by returning to an earlier query or asset type, and a failed
 * search shows an error with an explicit retry instead of leaving old
 * options selectable.
 * Search and retry only read (GET); nothing here installs or transfers.
 */
export function AssetSearchSelect({ id, assetType, assetId, onChangeAssetId }: AssetSearchSelectProps) {
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState<SearchState | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Incremented whenever earlier searches become obsolete (input change,
  // retry, selection, unmount); a response is applied only if its
  // generation is still the latest.
  const generationRef = useRef(0)
  const selected = Boolean(assetId)
  // Current search cycle; advanced in the same render as each transition.
  const [cycle, setCycle] = useState(0)

  // A new asset type starts from an empty query, and a selection made or
  // cleared by the parent starts a new cycle (adjusted during render, so
  // the old type's query never searches the new type's endpoint and no
  // earlier result is shown for even one render).
  const [queryAssetType, setQueryAssetType] = useState(assetType)
  const [cycleSelected, setCycleSelected] = useState(selected)
  if (queryAssetType !== assetType || cycleSelected !== selected) {
    if (queryAssetType !== assetType) setQuery('')
    setQueryAssetType(assetType)
    setCycleSelected(selected)
    setCycle((c) => c + 1)
  }

  const runSearch = useCallback((type: AssetType, text: string, searchCycle: number) => {
    const generation = ++generationRef.current
    setSearch({ kind: 'loading', cycle: searchCycle })
    void searchAssets(type, text).then((options) => {
      if (generation !== generationRef.current) return
      setSearch(
        options === null
          ? { kind: 'failed', cycle: searchCycle }
          : { kind: 'ready', cycle: searchCycle, options },
      )
    })
  }, [])

  useEffect(() => {
    // Any earlier in-flight search is obsolete from this moment on.
    generationRef.current += 1
    if (selected) return
    const timer = setTimeout(() => {
      debounceRef.current = null
      runSearch(assetType, query, cycle)
    }, SEARCH_DEBOUNCE_MS)
    debounceRef.current = timer
    return () => {
      clearTimeout(timer)
      debounceRef.current = null
      generationRef.current += 1
    }
  }, [assetType, query, selected, cycle, runSearch])

  const retry = () => {
    // One immediate request for the current input; no second debounced one.
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = null
    runSearch(assetType, query, cycle)
  }

  if (assetId) {
    return (
      <div className="form-field">
        <label>ยานพาหนะ/อุปกรณ์ปลายทาง</label>
        <p className="form-field__hint">
          เลือกแล้ว: {assetId}{' '}
          <button type="button" className="button button--secondary" onClick={() => onChangeAssetId('')}>
            เปลี่ยน
          </button>
        </p>
      </div>
    )
  }

  // Only a result made in the current cycle counts; anything else
  // (including the debounce interval) is shown as "searching".
  const current = search && search.cycle === cycle ? search : null
  const assetNoun = assetType === 'VEHICLE' ? 'ยานพาหนะ' : 'เครื่องมือ/อุปกรณ์'

  return (
    <div className="form-field">
      <label htmlFor={id}>ค้นหายานพาหนะ/อุปกรณ์</label>
      <input
        id={id}
        type="text"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
          setCycle((c) => c + 1)
        }}
        placeholder="พิมพ์รหัสหรือชื่อ/เลขเครื่องจักร"
      />
      {(current === null || current.kind === 'loading') && (
        <p className="form-field__hint">กำลังค้นหา...</p>
      )}
      {current?.kind === 'failed' && (
        <>
          <p className="form-field__error" role="alert">
            ค้นหา{assetNoun}ไม่สำเร็จ จึงไม่แสดงรายการให้เลือก
          </p>
          <button type="button" className="button button--secondary" onClick={retry}>
            ลองค้นหาอีกครั้ง
          </button>
        </>
      )}
      {current?.kind === 'ready' && current.options.length === 0 && (
        <p className="form-field__hint">ไม่พบ{assetNoun}ที่ตรงกับคำค้น</p>
      )}
      {current?.kind === 'ready' && current.options.length > 0 && (
        <ul>
          {current.options.map((option) => (
            <li key={option.assetId}>
              <button
                type="button"
                className="button button--secondary button--full-width"
                onClick={() => {
                  generationRef.current += 1
                  setSearch(null)
                  setQuery('')
                  setCycle((c) => c + 1)
                  onChangeAssetId(option.assetId)
                }}
              >
                {option.displayLabel}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
