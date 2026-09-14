/** Capability name constants (Core Demo Fixes Delta REV05 section 10) —
 * kept in their own module, separate from `capabilities.tsx`'s React
 * context/provider/hook, so that file can stay component-only. */
export const CAN_VIEW = 'can_view'
export const CAN_MANAGE_PM = 'can_manage_pm'
export const CAN_REPORT_REPAIR = 'can_report_repair'
export const CAN_MANAGE_REPAIR = 'can_manage_repair'
export const CAN_CLOSE_REPAIR = 'can_close_repair'
export const CAN_RECORD_INSPECTION = 'can_record_inspection'
