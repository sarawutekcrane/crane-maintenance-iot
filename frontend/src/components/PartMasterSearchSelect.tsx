import { useEffect, useRef, useState } from 'react'
import { apiGet } from '../lib/apiClient'
import type { Page, PartMaster } from '../lib/types'

interface PartMasterSearchSelectProps {
  selectedPart: PartMaster | null
  onSelectPart: (part: PartMaster | null) => void
  freeTextDescription: string
  onFreeTextDescriptionChange: (value: string) => void
}

/**
 * Core Demo Fixes, REPAIR PARTS section E: "Standard interaction should
 * select/search from Part Master rather than free-typing part identity.
 * Free-text may remain only as an explicit fallback for an unregistered/
 * unknown part, clearly marked as such." This component is the shared
 * search/select UI; free text stays available and visibly labeled as a
 * fallback, never the default.
 */
export function PartMasterSearchSelect({
  selectedPart,
  onSelectPart,
  freeTextDescription,
  onFreeTextDescriptionChange,
}: PartMasterSearchSelectProps) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<PartMaster[]>([])
  const [searching, setSearching] = useState(false)
  const [useFreeText, setUseFreeText] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      return
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearching(true)
      void apiGet<Page<PartMaster>>(`/parts?q=${encodeURIComponent(query.trim())}&page_size=10`).then(
        (result) => {
          setSearching(false)
          if (result.ok) setResults(result.data.items)
        },
      )
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query])

  if (selectedPart) {
    return (
      <div className="form-field">
        <label>อะไหล่ (จาก Part Master)</label>
        <div className="status-card__row">
          <span>
            {selectedPart.name}
            {selectedPart.specification ? ` (${selectedPart.specification})` : ''}
          </span>
          <button type="button" className="button button--secondary" onClick={() => onSelectPart(null)}>
            เปลี่ยนอะไหล่
          </button>
        </div>
      </div>
    )
  }

  if (useFreeText) {
    return (
      <div className="form-field">
        <label htmlFor="part-free-text">ชื่ออะไหล่ (ระบุเอง — อะไหล่ยังไม่ได้ลงทะเบียนใน Part Master)</label>
        <input
          id="part-free-text"
          type="text"
          value={freeTextDescription}
          onChange={(event) => onFreeTextDescriptionChange(event.target.value)}
        />
        <button
          type="button"
          className="button button--secondary"
          onClick={() => setUseFreeText(false)}
        >
          ค้นหาจาก Part Master แทน
        </button>
      </div>
    )
  }

  return (
    <div className="form-field">
      <label htmlFor="part-search">ค้นหาอะไหล่จาก Part Master</label>
      <input
        id="part-search"
        type="text"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="พิมพ์ชื่อหรือรหัสอะไหล่"
      />
      {searching && <p className="form-field__hint">กำลังค้นหา...</p>}
      {results.length > 0 && (
        <ul>
          {results.map((part) => (
            <li key={part.part_id}>
              <button
                type="button"
                className="button button--secondary button--full-width"
                onClick={() => {
                  onSelectPart(part)
                  setQuery('')
                  setResults([])
                }}
              >
                {part.name}
                {part.specification ? ` (${part.specification})` : ''}
              </button>
            </li>
          ))}
        </ul>
      )}
      {query.trim() && !searching && results.length === 0 && (
        <p className="form-field__hint">ไม่พบอะไหล่ที่ตรงกับคำค้นหา</p>
      )}
      <button type="button" className="button button--secondary" onClick={() => setUseFreeText(true)}>
        ไม่พบอะไหล่ในระบบ — ระบุชื่อเอง (สำหรับอะไหล่ที่ยังไม่ได้ลงทะเบียน)
      </button>
    </div>
  )
}
