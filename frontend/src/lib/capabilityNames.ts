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
/** R2 Batch R2e — deactivate / reactivate / reconcile a personnel record (not a login account). */
export const CAN_MANAGE_PERSONNEL = 'can_manage_personnel'
/** R2 Batch R2e — deactivate / reactivate / reconcile a department record. */
export const CAN_MANAGE_DEPARTMENT = 'can_manage_department'
/** R2 Batch R2-C2a — the existing backend capabilities of the R2f write routes
 * (backend/app/domain/authz.py). There is deliberately no department-move
 * capability here: no role holds it and no control is shown for it. */
export const CAN_LINK_PERSONNEL_TECHNICIAN = 'can_link_personnel_technician'
export const CAN_LINK_PERSONNEL_ACCOUNT = 'can_link_personnel_account'
export const CAN_LINK_PERSONNEL_DRIVER = 'can_link_personnel_driver'
export const CAN_ASSIGN_EQUIPMENT_CARETAKER = 'can_assign_equipment_caretaker'
export const CAN_ASSIGN_CRANE_DRIVER = 'can_assign_crane_driver'
/** R3 (contract §8, TS-1 — provisional name): the narrow Finding authority,
 * required IN ADDITION to the repair capability for Finding actions. A UX
 * hint only; the backend re-checks every write. */
export const CAN_MANAGE_FINDING_REPAIR = 'can_manage_finding_repair'
/** R3-F1 L10 (Owner decision D8-A): cancel a PENDING, never converted Repair
 * Request of any source, by hand, with a reason. Maintenance Department Manager
 * (and ADMIN) only. A UX hint; the backend re-checks it. */
export const CAN_CANCEL_REPAIR_REQUEST = 'can_cancel_repair_request'
