import { useEffect, useRef, useState } from 'react'
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

/**
 * Core Demo Fixes, PART INSTANCE / LIFETIME CORRECTIONS: "Asset selection
 * for install/transfer should use searchable/selectable known assets
 * instead of requiring manual raw ID typing in the normal UI." Searches
 * the same vehicle/equipment list endpoints the Vehicle/Equipment list
 * pages already use — never invents a new asset directory.
 */
export function AssetSearchSelect({ id, assetType, assetId, onChangeAssetId }: AssetSearchSelectProps) {
  const [query, setQuery] = useState('')
  const [options, setOptions] = useState<AssetOption[]>([])
  const [searching, setSearching] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setQuery('')
    setOptions([])
  }, [assetType])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearching(true)
      const search = async () => {
        if (assetType === 'VEHICLE') {
          const params = new URLSearchParams({ page_size: '10' })
          if (query.trim()) params.set('q', query.trim())
          const result = await apiGet<Page<Vehicle>>(`/vehicles?${params.toString()}`)
          if (result.ok) {
            setOptions(
              result.data.items.map((v) => ({
                assetId: v.vehicle_id,
                displayLabel: `${v.vehicle_id} — ${v.machine_no}`,
              })),
            )
          }
        } else {
          const params = new URLSearchParams({ page_size: '10' })
          if (query.trim()) params.set('q', query.trim())
          const result = await apiGet<Page<Equipment>>(`/equipment?${params.toString()}`)
          if (result.ok) {
            setOptions(
              result.data.items.map((e) => ({
                assetId: e.equipment_id,
                displayLabel: `${e.equipment_id} — ${e.name}`,
              })),
            )
          }
        }
        setSearching(false)
      }
      void search()
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetType, query])

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

  return (
    <div className="form-field">
      <label htmlFor={id}>ค้นหายานพาหนะ/อุปกรณ์</label>
      <input
        id={id}
        type="text"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="พิมพ์รหัสหรือชื่อ/เลขเครื่องจักร"
      />
      {searching && <p className="form-field__hint">กำลังค้นหา...</p>}
      {options.length > 0 && (
        <ul>
          {options.map((option) => (
            <li key={option.assetId}>
              <button
                type="button"
                className="button button--secondary button--full-width"
                onClick={() => {
                  onChangeAssetId(option.assetId)
                  setQuery('')
                  setOptions([])
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
