import { useMemo, useState } from 'react'
import { FormField } from './FormField'
import { componentRoleLabel } from '../lib/labels'
import type { CounterType, MeterReadingInput, VehicleComponent } from '../lib/types'

interface MeterField {
  key: string
  label: string
  componentId: string | null
  counterType: CounterType
}

function buildFields(components: VehicleComponent[]): MeterField[] {
  const fields: MeterField[] = []
  for (const component of components) {
    if (component.component_role === 'CARRIER_ENGINE' || component.component_role === 'CRANE_ENGINE') {
      fields.push({
        key: component.component_id,
        label: `${componentRoleLabel[component.component_role] ?? component.component_role} (ชั่วโมงเครื่องยนต์)`,
        componentId: component.component_id,
        counterType: 'ENGINE_HOUR',
      })
    } else if (component.component_role === 'PTO') {
      fields.push({
        key: component.component_id,
        label: `${componentRoleLabel.PTO} (ชั่วโมง PTO)`,
        componentId: component.component_id,
        counterType: 'PTO_HOUR',
      })
    }
  }
  fields.push({ key: 'ODOMETER', label: 'เลขไมล์ (ODOMETER)', componentId: null, counterType: 'ODOMETER' })
  return fields
}

interface MeterSnapshotFieldsProps {
  components: VehicleComponent[]
  onChange: (readings: MeterReadingInput[]) => void
}

/**
 * Component-aware meter reading capture (baseline section 5/16 / Phase 4
 * scope): one input per component-scoped counter the vehicle actually has
 * — never a fabricated CRANE_ENGINE field on a single-engine vehicle —
 * plus one vehicle-level ODOMETER field. Left blank means UNKNOWN and is
 * simply omitted from the built readings (never sent as 0).
 *
 * Only rendered for vehicles: workshop equipment has no approved counter
 * model yet (OPEN_DECISIONS_REGISTER_EN.txt C03) — callers must not render
 * this for `asset_type === 'EQUIPMENT'`.
 */
export function MeterSnapshotFields({ components, onChange }: MeterSnapshotFieldsProps) {
  const fields = useMemo(() => buildFields(components), [components])
  const [values, setValues] = useState<Record<string, string>>({})

  const updateValue = (key: string, raw: string) => {
    const next = { ...values, [key]: raw }
    setValues(next)
    const readings: MeterReadingInput[] = []
    for (const field of fields) {
      const text = next[field.key]
      if (text === undefined || text.trim() === '') continue
      const numeric = Number(text)
      readings.push({
        component_id: field.componentId,
        counter_type: field.counterType,
        value: Number.isFinite(numeric) ? numeric : null,
      })
    }
    onChange(readings)
  }

  return (
    <div className="form-grid">
      {fields.map((field) => (
        <FormField
          key={field.key}
          label={field.label}
          htmlFor={`meter-${field.key}`}
          hint="เว้นว่างไว้หากไม่ทราบค่า (ไม่ถือว่าเป็น 0)"
        >
          <input
            id={`meter-${field.key}`}
            type="number"
            inputMode="decimal"
            step="any"
            value={values[field.key] ?? ''}
            onChange={(event) => updateValue(field.key, event.target.value)}
          />
        </FormField>
      ))}
    </div>
  )
}
