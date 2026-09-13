import type { PmUsedPartInput } from '../lib/types'

interface PartRowsEditorProps {
  parts: PmUsedPartInput[]
  onChange: (parts: PmUsedPartInput[]) => void
}

/**
 * Mobile-friendly actual-parts-used entry (baseline mobile requirement:
 * "part entry must not require a wide table"). Each part is its own
 * stacked card with description/quantity/unit fields and a remove
 * button — never a desktop-style multi-column table.
 */
export function PartRowsEditor({ parts, onChange }: PartRowsEditorProps) {
  const updateRow = (index: number, patch: Partial<PmUsedPartInput>) => {
    onChange(parts.map((part, i) => (i === index ? { ...part, ...patch } : part)))
  }

  const removeRow = (index: number) => {
    onChange(parts.filter((_, i) => i !== index))
  }

  const addRow = () => {
    onChange([
      ...parts,
      { part_description: '', quantity: null, unit: null, part_instance_id: null },
    ])
  }

  return (
    <div className="part-rows-editor">
      {parts.map((part, index) => (
        <div className="part-rows-editor__row" key={index}>
          <div className="form-field">
            <label htmlFor={`part-desc-${index}`}>ชื่ออะไหล่</label>
            <input
              id={`part-desc-${index}`}
              type="text"
              value={part.part_description}
              onChange={(event) => updateRow(index, { part_description: event.target.value })}
              placeholder="เช่น ไส้กรองน้ำมันเครื่อง"
            />
          </div>
          <div className="part-rows-editor__row-fields">
            <div className="form-field">
              <label htmlFor={`part-qty-${index}`}>จำนวน</label>
              <input
                id={`part-qty-${index}`}
                type="number"
                inputMode="decimal"
                value={part.quantity ?? ''}
                onChange={(event) =>
                  updateRow(index, {
                    quantity: event.target.value === '' ? null : Number(event.target.value),
                  })
                }
              />
            </div>
            <div className="form-field">
              <label htmlFor={`part-unit-${index}`}>หน่วย</label>
              <input
                id={`part-unit-${index}`}
                type="text"
                value={part.unit ?? ''}
                onChange={(event) => updateRow(index, { unit: event.target.value || null })}
                placeholder="เช่น ชิ้น"
              />
            </div>
          </div>
          <div className="form-field">
            <label htmlFor={`part-instance-${index}`}>รหัสชิ้นงาน (Part Instance) — ถ้ามี</label>
            <input
              id={`part-instance-${index}`}
              type="text"
              value={part.part_instance_id ?? ''}
              onChange={(event) =>
                updateRow(index, { part_instance_id: event.target.value || null })
              }
              placeholder="เช่น PINST-0001"
            />
          </div>
          <button
            type="button"
            className="button button--secondary"
            onClick={() => removeRow(index)}
          >
            ลบรายการอะไหล่
          </button>
        </div>
      ))}
      <button type="button" className="button button--secondary button--full-width" onClick={addRow}>
        + เพิ่มอะไหล่ที่ใช้
      </button>
    </div>
  )
}
