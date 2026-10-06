/** Capability name constants (Core Demo Fixes Delta REV05 section 10) —
 * kept in their own module, separate from `capabilities.tsx`'s React
 * context/provider/hook, so that file can stay component-only. */
export const CAN_VIEW = 'can_view'
export const CAN_MANAGE_PM = 'can_manage_pm'
export const CAN_REPORT_REPAIR = 'can_report_repair'
export const CAN_MANAGE_REPAIR = 'can_manage_repair'
export const CAN_CLOSE_REPAIR = 'can_close_repair'
export const CAN_RECORD_INSPECTION = 'can_record_inspection'
/** Phase 7 Batch 7O2b — edit a vehicle's registration (contract Final Rev2 §3.1). */
export const CAN_EDIT_VEHICLE_REGISTRATION = 'can_edit_vehicle_registration'
/** Phase 7 Batch 7O2c — transfer a vehicle and reconcile its branch projection. */
export const CAN_TRANSFER_VEHICLE_BRANCH = 'can_transfer_vehicle_branch'
/** Phase 7 Batch 7O2c — insert, correct and cancel branch-history events. */
export const CAN_CORRECT_BRANCH_HISTORY = 'can_correct_branch_history'
