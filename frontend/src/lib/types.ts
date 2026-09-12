/** Mirrors backend/app/api/v1/vehicle_schemas.py and equipment_schemas.py. */

export type OperationalStatus =
  | 'WORKING'
  | 'READY'
  | 'MAINTENANCE'
  | 'OUT_OF_SERVICE'
  | 'LONG_TERM_PARKING'

export type ComponentRole = 'ENGINE_MAIN' | 'ENGINE_SECONDARY' | 'PTO' | 'VEHICLE'

export type EquipmentCategory =
  | 'LATHE'
  | 'MILLING'
  | 'AIR_COMPRESSOR'
  | 'WELDING'
  | 'PRESS'
  | 'DRILL_PRESS'
  | 'GRINDER'
  | 'FORKLIFT'
  | 'OTHER'

export interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total_items: number
}

export interface VehicleModel {
  model_id: string
  model_code: string
  model_name: string
  brand: string | null
  description: string | null
  component_roles: ComponentRole[]
  created_at: string
  updated_at: string
}

export interface Vehicle {
  vehicle_id: string
  machine_no: string
  model_id: string
  serial_number: string | null
  operational_status: OperationalStatus
  created_at: string
  updated_at: string
}

export interface VehicleComponent {
  component_id: string
  vehicle_id: string
  component_role: ComponentRole
  label: string
}

export interface VehicleStatusHistoryEntry {
  history_id: string
  vehicle_id: string
  status: OperationalStatus
  changed_at: string
  changed_by: string | null
  note: string | null
}

export interface VehicleDetail {
  vehicle: Vehicle
  model: VehicleModel | null
  components: VehicleComponent[]
}

export interface ChangeVehicleStatusResult {
  vehicle: Vehicle
  history_entry: VehicleStatusHistoryEntry
}

export interface Equipment {
  equipment_id: string
  equipment_code: string
  name: string
  category: EquipmentCategory
  serial_number: string | null
  location: string | null
  operational_status: OperationalStatus
  created_at: string
  updated_at: string
}
