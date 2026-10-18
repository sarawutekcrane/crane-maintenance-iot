/**
 * Thai label mapping for internal English codes (baseline section 1:
 * "Internal stable technical identifiers may remain English... Do not
 * expose raw database field names to ordinary users"). Extend these maps
 * as new enum values are introduced; never invent a Thai label for a code
 * the backend does not actually send.
 */
import type { StatusTone } from '../components/StatusBadge'

/** Vehicle-only status labels. Do not use for Equipment — see
 * `equipmentStatusLabel` (decision C02). */
export const operationalStatusLabel: Record<string, string> = {
  WORKING: 'ใช้งานอยู่',
  READY: 'พร้อมใช้งาน',
  MAINTENANCE: 'ซ่อมบำรุง',
  OUT_OF_SERVICE: 'หยุดใช้งาน',
  LONG_TERM_PARKING: 'จอดระยะยาว',
}

export const operationalStatusTone: Record<string, StatusTone> = {
  WORKING: 'success',
  READY: 'info',
  MAINTENANCE: 'warning',
  OUT_OF_SERVICE: 'danger',
  LONG_TERM_PARKING: 'neutral',
}

/** Workshop equipment status labels — a vocabulary separate from
 * Vehicle's `operationalStatusLabel` (decision C02, extended by the Core
 * Demo Fixes EQUIPMENT STATUS CHANGE approval with RETIRED). */
export const equipmentStatusLabel: Record<string, string> = {
  READY: 'พร้อมใช้งาน',
  IN_USE: 'กำลังใช้งาน',
  MAINTENANCE: 'ซ่อมบำรุง',
  OUT_OF_SERVICE: 'งดใช้งานชั่วคราว',
  RETIRED: 'ปลดระวาง / เลิกใช้งานถาวร',
}

export const equipmentStatusTone: Record<string, StatusTone> = {
  READY: 'info',
  IN_USE: 'success',
  MAINTENANCE: 'warning',
  OUT_OF_SERVICE: 'danger',
  RETIRED: 'neutral',
}

export const componentRoleLabel: Record<string, string> = {
  CARRIER_ENGINE: 'เครื่องยนต์ Carrier / เครื่องยนต์ช่วงล่าง',
  CRANE_ENGINE: 'เครื่องยนต์ Crane / เครื่องยนต์ชุดเครน',
  PTO: 'ระบบส่งกำลัง (PTO)',
  VEHICLE: 'ตัวรถ',
}

export const equipmentCategoryLabel: Record<string, string> = {
  LATHE: 'เครื่องกลึง',
  MILLING: 'เครื่องมิลลิ่ง',
  AIR_COMPRESSOR: 'ปั๊มลม',
  WELDING: 'เครื่องเชื่อม',
  PRESS: 'เครื่องอัด',
  DRILL_PRESS: 'เครื่องเจาะ',
  GRINDER: 'เครื่องเจียร',
  FORKLIFT: 'รถโฟล์คลิฟท์',
  OTHER: 'อื่น ๆ',
}

/** Phase 3 — inspection result codes (backend/app/domain/checklist.py:
 * `InspectionResultValue`). Stable English codes, Thai labels only here. */
export const inspectionResultLabel: Record<string, string> = {
  PASS: 'ผ่าน',
  FAIL: 'ไม่ผ่าน',
  NA: 'ไม่เกี่ยวข้อง',
}

export const inspectionResultTone: Record<string, StatusTone> = {
  PASS: 'success',
  FAIL: 'danger',
  NA: 'neutral',
}

export const assetTypeLabel: Record<string, string> = {
  VEHICLE: 'ยานพาหนะ',
  EQUIPMENT: 'เครื่องมือ/อุปกรณ์',
}

/** Phase 4 — PM trigger type labels. */
export const pmTriggerTypeLabel: Record<string, string> = {
  ENGINE_HOUR: 'ชั่วโมงเครื่องยนต์',
  PTO_HOUR: 'ชั่วโมง PTO',
  ODOMETER: 'เลขไมล์',
  CALENDAR: 'ตามรอบเวลา',
}

/** Phase 4 — PM work order status. PROVISIONAL/CONFIGURABLE placeholder
 * only (OPEN_DECISIONS_REGISTER_EN.txt E01 is unresolved) — only two
 * states exist, no transition matrix. */
export const pmWorkOrderStatusLabel: Record<string, string> = {
  OPEN: 'กำลังดำเนินการ',
  CLOSED: 'ปิดงานแล้ว',
}

export const pmWorkOrderStatusTone: Record<string, StatusTone> = {
  OPEN: 'info',
  CLOSED: 'success',
}

/** Phase 4 — counter type labels (guardrails §10). */
export const counterTypeLabel: Record<string, string> = {
  ENGINE_HOUR: 'ชั่วโมงเครื่องยนต์',
  PTO_HOUR: 'ชั่วโมง PTO',
  ODOMETER: 'เลขไมล์ (ODOMETER)',
}

/** Phase 4 — Repair source type labels (baseline section 10). */
export const repairSourceTypeLabel: Record<string, string> = {
  MANUAL: 'แจ้งซ่อมด้วยตนเอง',
  INSPECTION_RESULT: 'ผลการตรวจเช็ค',
  FINDING: 'ข้อบกพร่องจากการตรวจเช็ค',
  PM_RESULT: 'ผลงาน PM',
  ALERT: 'การแจ้งเตือน',
  REPAIR_REQUEST: 'รายการแจ้งซ่อม',
}

/** Phase 4 — Repair status. PROVISIONAL/CONFIGURABLE placeholder only
 * (OPEN_DECISIONS_REGISTER_EN.txt F01 is unresolved) — only two states
 * exist, no transition matrix. */
export const repairStatusLabel: Record<string, string> = {
  OPEN: 'กำลังดำเนินการ',
  CLOSED: 'ปิดงานแล้ว',
}

export const repairStatusTone: Record<string, StatusTone> = {
  OPEN: 'warning',
  CLOSED: 'success',
}

/** Phase 5 — tracking-mode labels (baseline "APPROVED PART-TRACKING
 * CONCEPTS"). The four meanings must remain distinct in the UI. */
export const trackingModeLabel: Record<string, string> = {
  NONE: 'ไม่มีการติดตามอายุการใช้งาน',
  CONSUMABLE: 'วัสดุสิ้นเปลือง (บันทึกการใช้งานจริง)',
  POSITION_LIFETIME: 'อายุการใช้งานตามตำแหน่ง',
  INSTANCE_TRACKED: 'ติดตามรายชิ้น (มีรหัสชิ้นงานเฉพาะ)',
}

export const partSetItemRequirementLabel: Record<string, string> = {
  REQUIRED: 'จำเป็นต้องมี',
  OPTIONAL: 'ไม่บังคับ',
  ALTERNATIVE: 'ใช้แทนกันได้',
}

/** G05: PARTIALLY FROZEN placeholder — known states only, see
 * `PartInstanceStatus` in lib/types.ts. */
export const partInstanceStatusLabel: Record<string, string> = {
  INSTALLED: 'ติดตั้งใช้งานอยู่',
  REMOVED: 'ถอดออกแล้ว',
  IN_REPAIR: 'อยู่ระหว่างซ่อม',
  READY_FOR_INSTALL: 'พร้อมติดตั้ง',
  STOCK: 'อยู่ในคลัง',
  SCRAPPED: 'ปลดระวาง/ทิ้ง',
}

export const partInstanceStatusTone: Record<string, StatusTone> = {
  INSTALLED: 'success',
  REMOVED: 'neutral',
  IN_REPAIR: 'warning',
  READY_FOR_INSTALL: 'info',
  STOCK: 'info',
  SCRAPPED: 'danger',
}

/** Never render UNKNOWN's value as `0` — always show this label instead
 * when `value` is `null`. */
export const priorUsageQualityLabel: Record<string, string> = {
  KNOWN: 'ทราบค่าแน่ชัด',
  PARTIAL: 'ทราบค่าบางส่วน',
  UNKNOWN: 'ไม่ทราบค่า',
}

export const partActionTypeLabel: Record<string, string> = {
  CONSUMED: 'ใช้หมด/เบิกใช้',
  INSTALLED: 'ติดตั้ง',
  REMOVED: 'ถอดออก',
  SERVICED: 'ซ่อม/บำรุงรักษา',
}

export const lifecycleStartReasonLabel: Record<string, string> = {
  ENROLLMENT: 'เริ่มติดตามครั้งแรก',
  OVERHAUL: 'Overhaul (ได้รับอนุมัติ)',
}

export const installationSegmentStatusLabel: Record<string, string> = {
  ACTIVE: 'ติดตั้งอยู่ปัจจุบัน',
  CLOSED: 'สิ้นสุดการติดตั้งแล้ว',
}

export const lifetimeTriggerTypeLabel: Record<string, string> = {
  ENGINE_HOUR: 'ชั่วโมงเครื่องยนต์',
  PTO_HOUR: 'ชั่วโมง PTO',
  ODOMETER: 'เลขไมล์',
  CYCLE: 'จำนวนรอบการทำงาน',
  CALENDAR: 'ตามรอบเวลา',
}

export const lifetimeRuleScopeLabel: Record<string, string> = {
  MODEL: 'กำหนดตามรุ่นเครื่องจักร',
  VEHICLE: 'กำหนดเฉพาะยานพาหนะ (Override)',
}

/** Web/API Phase 6 Batch 6A — Vehicle Event (Work History). The frozen
 * six-value `event_type` vocabulary and three-value `time_quality`
 * vocabulary (see `app.domain.vehicle_event` / `lib/types.ts`
 * `VehicleEventType`/`TimeQuality`) — Thai labels only here, never
 * hard-coded inline in a page. */
export const vehicleEventTypeLabel: Record<string, string> = {
  ENGINE_START: 'เริ่มเดินเครื่อง',
  ENGINE_STOP: 'หยุดเครื่อง',
  PTO_ON: 'เปิด PTO',
  PTO_OFF: 'ปิด PTO',
  DEVICE_ONLINE: 'อุปกรณ์ออนไลน์',
  DEVICE_OFFLINE: 'อุปกรณ์ออฟไลน์',
}

export const timeQualityLabel: Record<string, string> = {
  TIME_SYNCED: 'เวลาจากอุปกรณ์ถูกซิงก์แล้ว',
  TIME_ESTIMATED: 'เวลาจากอุปกรณ์เป็นค่าประมาณ',
  TIME_NOT_SYNCED: 'เวลาอุปกรณ์ยังไม่ซิงก์',
}

export const timeQualityTone: Record<string, StatusTone> = {
  TIME_SYNCED: 'success',
  TIME_ESTIMATED: 'warning',
  TIME_NOT_SYNCED: 'danger',
}

/** Web/API Phase 6 Batch 6B — Daily Summary. The frozen two-value
 * `metric_type` vocabulary and two-value `data_status` vocabulary (see
 * `app.domain.daily_summary` / `lib/types.ts` `DailySummaryMetricType`/
 * `DailySummaryDataStatus`) — Thai labels only here, never hard-coded
 * inline in a page. Raw English codes are never exposed to ordinary
 * users. */
export const dailySummaryMetricTypeLabel: Record<string, string> = {
  ENGINE_RUN_DURATION: 'ระยะเวลาเดินเครื่อง',
  PTO_RUN_DURATION: 'ระยะเวลาใช้งาน PTO',
}

export const dailySummaryDataStatusLabel: Record<string, string> = {
  COMPLETE: 'ข้อมูลครบถ้วน',
  PARTIAL: 'ข้อมูลไม่ครบถ้วน',
}

export const dailySummaryDataStatusTone: Record<string, StatusTone> = {
  COMPLETE: 'success',
  PARTIAL: 'warning',
}

/** Web/API Phase 6 Batch 6C — Alert. The frozen three-value `severity`
 * vocabulary (D24) and four-value `alert_status` vocabulary (baseline
 * section 23) — Thai labels only here, never hard-coded inline in a
 * page. D24 freezes ONLY the severity vocabulary; no `alert_type` label
 * mapping exists or should ever be added (see `lib/types.ts` `Alert`
 * docstring) — `alert_type` is always displayed as its exact stored
 * opaque technical value.
 *
 * `null` severity/status must never fall back to a real enum value
 * (e.g. never assume INFO/ACTIVE) — see `unknownAlertFieldLabel`. */
export const alertSeverityLabel: Record<string, string> = {
  INFO: 'ข้อมูล',
  WARNING: 'คำเตือน',
  CRITICAL: 'วิกฤต',
}

export const alertSeverityTone: Record<string, StatusTone> = {
  INFO: 'info',
  WARNING: 'warning',
  CRITICAL: 'danger',
}

/** MUTED must remain visibly distinct from RESOLVED (A07/D25: "MUTED is
 * not RESOLVED") — never collapse the two. */
export const alertStatusLabel: Record<string, string> = {
  ACTIVE: 'กำลังแจ้งเตือน',
  ACKNOWLEDGED: 'รับทราบแล้ว',
  MUTED: 'ระงับการแจ้งเตือนชั่วคราว',
  RESOLVED: 'สิ้นสุดแล้ว',
}

export const alertStatusTone: Record<string, StatusTone> = {
  ACTIVE: 'danger',
  ACKNOWLEDGED: 'warning',
  MUTED: 'neutral',
  RESOLVED: 'success',
}

/** Shown for a `null` severity/status cell — never a fabricated real
 * enum value. */
export const unknownAlertFieldLabel = 'ไม่มีข้อมูล'

export const unknownAlertTypeLabel = 'ไม่ระบุประเภท'

export const missingAlertMessageLabel = 'ไม่มีข้อความแจ้งเตือน'

export const missingAlertSourceLabel = 'ไม่มีข้อมูลแหล่งที่มา'

/** R2 Batch R2-C2a — the codes one Personnel link family shares
 * (backend personnel_link.py: `<LINK>_*` and `<TARGET>_*`). */
function r2LinkErrorMessages(link: string, target: string, targetTh: string): Record<string, string> {
  return {
    [`${link}_STALE`]: `ความเชื่อมโยง${targetTh}เปลี่ยนไปหลังจากที่โหลดข้อมูล กรุณาโหลดข้อมูลล่าสุดแล้วลองใหม่`,
    [`${link}_MISMATCH`]: `ข้อมูลความเชื่อมโยง${targetTh}ปัจจุบันไม่ตรงกับประวัติล่าสุด ต้องปรับข้อมูลให้ตรงกับประวัติก่อน`,
    [`${link}_RELINK_REQUIRED`]: `บุคลากรนี้เชื่อมโยง${targetTh}อยู่แล้ว ให้ใช้ "เปลี่ยนการเชื่อมโยง"`,
    [`${link}_LINK_REQUIRED`]: `บุคลากรนี้ยังไม่ได้เชื่อมโยง${targetTh} ให้ใช้ "เชื่อมโยง"`,
    [`${link}_TARGET_REQUIRED`]: `กรุณาระบุรหัส${targetTh}`,
    [`${link}_TARGET_NOT_ALLOWED`]: `การยกเลิกการเชื่อมโยงต้องไม่ระบุรหัส${targetTh}`,
    [`${link}_RECONCILIATION_NOT_REQUIRED`]: 'ข้อมูลปัจจุบันตรงกับประวัติแล้ว ไม่ต้องปรับข้อมูล',
    [`${link}_RELATED_REQUEST_INVALID`]: 'รหัสคำขอที่อ้างอิงไม่ตรงกับรายการล่าสุดในประวัติ',
    [`${link}_HISTORY_WRITE_FAILED`]: 'บันทึกประวัติความเชื่อมโยงไม่สำเร็จหรือไม่ทราบผล',
    [`${link}_PROJECTION_WRITE_FAILED`]: 'บันทึกประวัติแล้ว แต่ปรับข้อมูลความเชื่อมโยงปัจจุบันไม่สำเร็จ',
    [`${link}_HISTORY_READ_FAILED`]: 'อ่านประวัติความเชื่อมโยงไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
    [`${link}_HISTORY_SCHEMA_INVALID`]: 'ประวัติความเชื่อมโยงยังไม่พร้อมใช้งานในระบบ',
    [`${link}_HISTORY_DATA_INVALID`]: 'ประวัติความเชื่อมโยงไม่ถูกต้อง กรุณาแจ้งผู้ดูแลข้อมูล',
    [`${target}_NOT_FOUND`]: `ไม่พบ${targetTh}รหัสนี้ในขอบเขตข้อมูลปัจจุบัน`,
    [`${target}_SCOPE_UNPROVEN`]: `${targetTh}รหัสนี้ไม่อยู่ในขอบเขตข้อมูลปัจจุบัน (TEST/REAL) จึงใช้ไม่ได้`,
    [`${target}_ID_AMBIGUOUS`]: `มี${targetTh}ที่ใช้รหัสนี้มากกว่าหนึ่งรายการ ระบบไม่เลือกให้`,
    [`${target}_ALREADY_LINKED`]: `${targetTh}รหัสนี้เชื่อมโยงกับบุคลากรอื่นอยู่แล้ว ต้องยกเลิกที่บุคลากรนั้นก่อน`,
  }
}

const knownErrorMessages: Record<string, string> = {
  // R2 Batch R2-C2a — the shared link-family codes come first, so every message
  // defined explicitly below (including pre-existing ones) takes precedence.
  ...r2LinkErrorMessages('PERSONNEL_TECHNICIAN_LINK', 'TECHNICIAN', 'ช่าง'),
  ...r2LinkErrorMessages('PERSONNEL_ACCOUNT_LINK', 'USER_ACCOUNT', 'บัญชีผู้ใช้'),
  ...r2LinkErrorMessages('PERSONNEL_DRIVER_LINK', 'DRIVER', 'คนขับ/ผู้ควบคุม'),
  VEHICLE_NOT_FOUND: 'ไม่พบข้อมูลยานพาหนะนี้',
  MODEL_NOT_FOUND: 'ไม่พบข้อมูลรุ่นเครื่องจักรนี้',
  EQUIPMENT_NOT_FOUND: 'ไม่พบข้อมูลเครื่องมือ/อุปกรณ์นี้',
  VALIDATION_ERROR: 'ข้อมูลที่ส่งไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง',
  NOT_FOUND: 'ไม่พบข้อมูลที่ต้องการ',
  NO_ACTIVE_CHECKLIST: 'ยังไม่มีรายการตรวจเช็คที่ใช้งานอยู่สำหรับประเภทนี้',
  CHECKLIST_REVISION_NOT_FOUND: 'ไม่พบข้อมูลรุ่นรายการตรวจเช็คนี้',
  INSPECTION_NOT_FOUND: 'ไม่พบข้อมูลผลการตรวจเช็คนี้',
  ATTACHMENT_NOT_FOUND: 'ไม่พบไฟล์แนบนี้',
  ATTACHMENT_TYPE_NOT_ALLOWED: 'ไม่รองรับชนิดไฟล์นี้ กรุณาแนบไฟล์รูปภาพ',
  ATTACHMENT_TOO_LARGE: 'ไฟล์มีขนาดใหญ่เกินกำหนด กรุณาเลือกไฟล์ที่มีขนาดเล็กลง',
  PM_PLAN_NOT_FOUND: 'ไม่พบแผนบำรุงรักษานี้',
  NO_ACTIVE_PM_TASK_REVISION: 'ยังไม่มีรายการงาน PM ที่ใช้งานอยู่สำหรับแผนนี้',
  PM_TASK_REVISION_NOT_FOUND: 'ไม่พบข้อมูลรุ่นรายการงาน PM นี้',
  PM_WORK_ORDER_NOT_FOUND: 'ไม่พบใบสั่งงาน PM นี้',
  PM_WORK_ORDER_CLOSED: 'ใบสั่งงาน PM นี้ถูกปิดแล้ว ไม่สามารถเพิ่มผลงานได้',
  PM_WORK_ORDER_ALREADY_CLOSED: 'ใบสั่งงาน PM นี้ถูกปิดไปแล้ว',
  PM_TASK_RESULT_ALREADY_EXISTS: 'มีผลงานสำหรับรายการนี้อยู่แล้ว ไม่สามารถบันทึกซ้ำได้',
  METER_COMPONENT_NOT_FOUND: 'ไม่พบส่วนประกอบนี้บนยานพาหนะดังกล่าว',
  METER_SNAPSHOT_NOT_FOUND: 'ไม่พบข้อมูลค่ามาตรวัดนี้',
  REPAIR_NOT_FOUND: 'ไม่พบข้อมูลใบแจ้งซ่อมนี้',
  REPAIR_SOURCE_NOT_FOUND: 'ไม่พบข้อมูลต้นทางของการแจ้งซ่อมนี้',
  REPAIR_ALREADY_CLOSED: 'ใบแจ้งซ่อมนี้ถูกปิดไปแล้ว',
  // Decision B (exact-source duplicate prevention): backend-controlled —
  // shown only if a direct/race API call bypasses the normal UI, which
  // already hides the report form once GET /repair-requests/by-source
  // shows an existing request for this exact Finding/PM Work Result.
  REPAIR_REQUEST_SOURCE_ALREADY_REPORTED: 'รายการผิดปกตินี้ถูกแจ้งซ่อมแล้ว',
  PART_NOT_FOUND: 'ไม่พบข้อมูลอะไหล่นี้',
  PART_SET_NOT_FOUND: 'ไม่พบข้อมูลชุดอะไหล่นี้',
  PART_SET_REVISION_NOT_FOUND: 'ไม่พบข้อมูลรุ่นชุดอะไหล่นี้',
  NO_ACTIVE_PART_SET_REVISION: 'ยังไม่มีรุ่นชุดอะไหล่ที่ใช้งานอยู่สำหรับชุดนี้',
  PART_NOT_INSTANCE_TRACKED: 'อะไหล่นี้ไม่ได้กำหนดให้ติดตามรายชิ้น',
  PART_NOT_POSITION_LIFETIME: 'อะไหล่นี้ไม่ได้กำหนดให้ติดตามอายุการใช้งานตามตำแหน่ง',
  PART_INSTANCE_NOT_FOUND: 'ไม่พบข้อมูลชิ้นงานนี้',
  PART_INSTANCE_ALREADY_INSTALLED: 'ชิ้นงานนี้ติดตั้งใช้งานอยู่แล้ว กรุณาถอด/โยกย้ายก่อน',
  PART_INSTANCE_NOT_INSTALLED: 'ชิ้นงานนี้ไม่ได้ติดตั้งใช้งานอยู่ในขณะนี้',
  PART_INSTANCE_SCRAPPED: 'ชิ้นงานนี้ถูกปลดระวางแล้ว ไม่สามารถติดตั้งได้',
  PART_INSTANCE_INSTALLED: 'ชิ้นงานนี้ติดตั้งใช้งานอยู่ กรุณาถอดออกก่อนเริ่มรอบการใช้งานใหม่',
  POSITION_LIFETIME_NOT_FOUND: 'ไม่พบข้อมูลอายุการใช้งานตามตำแหน่งนี้',
  LIFETIME_RULE_NOT_FOUND: 'ไม่พบข้อมูลกฎอายุการใช้งานนี้',
  EQUIPMENT_RETIRED: 'เครื่องมือ/อุปกรณ์นี้ถูกปลดระวางแล้ว ไม่สามารถใช้งานใหม่ได้',
  PM_PLAN_NOT_ASSIGNED_TO_MODEL: 'แผนบำรุงรักษานี้ไม่ใช่แผนที่กำหนดให้กับรุ่นเครื่องจักรนี้',
  PM_SCOPE_ALREADY_APPROVED: 'ขอบเขตงาน PM นี้ได้รับการอนุมัติและล็อกแล้ว',
  PM_TASK_NOT_IN_SCOPE: 'งานนี้ไม่อยู่ในขอบเขตของใบสั่งงาน PM นี้',
  // Final Cross-Phase Integration Fix (F3): a KNOWN, intentionally
  // unsupported repository operation (e.g. still-stubbed Google Sheets
  // path) — never implies data was lost, and retrying will not help.
  FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE: 'ฟังก์ชันนี้ยังไม่รองรับในโหมดข้อมูลที่กำลังใช้งาน',
  PM_SCOPE_NOT_COMPLETE: 'ต้องทำรายการงานในขอบเขตที่อนุมัติให้ครบก่อนจึงจะปิดงานได้',
  // Web/API Phase 6 Batch 1 — Driver / Operator.
  DRIVER_NOT_FOUND: 'ไม่พบข้อมูลพนักงานขับ/ผู้ควบคุมนี้',
  // VEHICLE_DRIVER_ASSIGNMENT_ALREADY_ENDED intentionally removed: ending
  // an already-ended assignment is now an idempotent no-op (project
  // decision, targeted correction) — the backend never returns this code.
  // Web/API Phase 6 Batch 2A — Vehicle Certificate.
  VEHICLE_CERTIFICATE_NOT_FOUND: 'ไม่พบข้อมูลเอกสาร/ใบรับรองนี้',
  // Web/API Phase 6 Batch 3A — Model Document.
  MODEL_DOCUMENT_NOT_FOUND: 'ไม่พบข้อมูลเอกสารประจำรุ่นเครื่องจักรนี้',
  // Web/API Phase 6 Batch 3B — Model Document revision.
  MODEL_DOCUMENT_REVISION_STATE_CONFLICT:
    'ข้อมูลการเชื่อมโยงฉบับปรับปรุงของเอกสารนี้ไม่ถูกต้อง ต้องให้ผู้ดูแลระบบตรวจสอบก่อน',
  MODEL_DOCUMENT_EFFECTIVE_FROM_MISSING:
    'เอกสารต้นทางยังไม่มีวันที่เริ่มมีผลใช้ จึงยังไม่สามารถสร้างฉบับปรับปรุงได้',
  MODEL_DOCUMENT_EFFECTIVE_FROM_NOT_LATER:
    'วันที่เริ่มมีผลใช้ของฉบับใหม่ต้องอยู่หลังวันที่เริ่มมีผลใช้ของเอกสารต้นทาง',
  MODEL_DOCUMENT_EFFECTIVE_TO_CONFLICT:
    'เอกสารต้นทางมีวันที่สิ้นสุดการใช้งานที่ไม่ตรงกับวันที่เริ่มมีผลใช้ของฉบับใหม่ กรุณาตรวจสอบข้อมูล',
  MODEL_DOCUMENT_VERSION_REQUIRED: 'กรุณาระบุเวอร์ชัน/ฉบับที่ของเอกสารฉบับใหม่',
  MODEL_DOCUMENT_VERSION_DUPLICATE: 'เวอร์ชัน/ฉบับที่ของฉบับใหม่ต้องไม่ซ้ำกับเวอร์ชันของเอกสารต้นทาง',
  // Web/API Phase 7 Batch 7B2 — fleet status dashboard (no numbers are
  // shown for any of these).
  VEHICLE_MASTER_DATA_INVALID:
    'ข้อมูลทะเบียนรถบางรายการไม่ครบหรือไม่ถูกต้อง (เช่น ไม่ได้ระบุสถานะ สถานะไม่ถูกต้อง หรือรหัสรถซ้ำ) ระบบจึงไม่แสดงตัวเลข เพื่อไม่ให้จำนวนคลาดเคลื่อน กรุณาแจ้งผู้ดูแลข้อมูลให้ตรวจสอบทะเบียนรถ',
  VEHICLE_MASTER_SCHEMA_INVALID:
    'โครงสร้างตารางทะเบียนรถไม่ตรงกับที่ระบบรองรับ ระบบจึงไม่แสดงตัวเลข กรุณาติดต่อผู้ดูแลระบบ',
  VEHICLE_MASTER_READ_FAILED: 'ไม่สามารถอ่านข้อมูลทะเบียนรถได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
  // Web/API Phase 7 Batch 7C2 — open-repair report (no rows or totals are
  // shown for either of these).
  REPAIR_ORDER_SCHEMA_INVALID:
    'โครงสร้างข้อมูลใบงานซ่อมไม่ถูกต้อง จึงไม่แสดงรายการเพื่อป้องกันผลที่คลาดเคลื่อน กรุณาแจ้งผู้ดูแลระบบ',
  REPAIR_ORDER_READ_FAILED: 'ไม่สามารถอ่านข้อมูลใบงานซ่อมได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
  // Web/API Phase 7 Batch 7D2 — certificate expiry report (no rows, totals
  // or disclosures are shown for either of these).
  VEHICLE_CERTIFICATE_SCHEMA_INVALID:
    'โครงสร้างข้อมูลใบรับรองไม่ถูกต้อง จึงไม่แสดงรายงานเพื่อป้องกันผลที่คลาดเคลื่อน กรุณาแจ้งผู้ดูแลระบบ',
  VEHICLE_CERTIFICATE_READ_FAILED: 'ไม่สามารถอ่านข้อมูลใบรับรองได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
  // Web/API Phase 7 Batch 7E2 — recorded inspection findings report (no
  // rows, totals or disclosures are shown for either of these).
  INSPECTION_FINDING_SCHEMA_INVALID: 'โครงสร้างตารางข้อบกพร่องไม่ถูกต้อง จึงแสดงรายงานไม่ได้',
  INSPECTION_FINDING_READ_FAILED: 'อ่านข้อมูลข้อบกพร่องไม่สำเร็จ กรุณาลองใหม่',
  // Web/API Phase 7 Batch 7K2 — validated equipment reads and status writes.
  EQUIPMENT_ID_AMBIGUOUS:
    'รหัสเครื่องมือนี้ซ้ำกันมากกว่าหนึ่งรายการในทะเบียนเครื่องมือ ระบบจึงไม่ดำเนินการใด ๆ กรุณาแจ้งผู้ดูแลข้อมูลให้แก้ไขรหัสที่ซ้ำ',
  EQUIPMENT_MASTER_DATA_INVALID:
    'ข้อมูลทะเบียนเครื่องมือบางรายการไม่ถูกต้อง (เช่น ประเภทหรือสถานะไม่ถูกต้อง) ระบบจึงไม่แสดงหรือไม่บันทึกข้อมูล เพื่อป้องกันผลที่คลาดเคลื่อน กรุณาแจ้งผู้ดูแลข้อมูล',
  EQUIPMENT_MASTER_SCHEMA_INVALID:
    'โครงสร้างตารางทะเบียนเครื่องมือไม่ตรงกับที่ระบบรองรับ ระบบจึงไม่ดำเนินการ กรุณาติดต่อผู้ดูแลระบบ',
  EQUIPMENT_MASTER_READ_FAILED: 'ไม่สามารถอ่านข้อมูลทะเบียนเครื่องมือได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
  EQUIPMENT_STATUS_HISTORY_DATA_INVALID:
    'ข้อมูลประวัติการเปลี่ยนสถานะบางรายการไม่ถูกต้อง (เช่น สถานะไม่ถูกต้อง หรือรูปแบบเวลาปะปนกัน) จึงแสดงประวัติไม่ได้ กรุณาแจ้งผู้ดูแลข้อมูล',
  EQUIPMENT_STATUS_HISTORY_SCHEMA_INVALID:
    'โครงสร้างตารางประวัติสถานะเครื่องมือไม่ตรงกับที่ระบบรองรับ ระบบจึงไม่ดำเนินการ กรุณาติดต่อผู้ดูแลระบบ',
  EQUIPMENT_STATUS_HISTORY_READ_FAILED: 'ไม่สามารถอ่านประวัติการเปลี่ยนสถานะได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
  EQUIPMENT_MASTER_WRITE_FAILED:
    'บันทึกการเปลี่ยนสถานะเครื่องมือไม่สำเร็จหรือไม่ทราบผล ระบบไม่ได้ลองใหม่อัตโนมัติ กรุณาตรวจสอบสถานะปัจจุบันก่อนลองใหม่',
  EQUIPMENT_STATUS_HISTORY_WRITE_FAILED:
    'ระบบได้รับการยืนยันการเปลี่ยนสถานะแล้ว แต่บันทึกประวัติไม่สำเร็จหรือไม่ทราบผล ระบบไม่ได้ลองใหม่อัตโนมัติ กรุณาตรวจสอบประวัติ',
  EQUIPMENT_ID_NOT_SUPPORTED_FOR_WORK:
    'รหัสเครื่องมือนี้ยังใช้บันทึกงานใหม่ไม่ได้ เพราะระบบบันทึกงานอาจเก็บรหัสนี้ผิดเพี้ยน (เช่น รหัสที่เป็นตัวเลขล้วน) กรุณาแจ้งผู้ดูแลข้อมูล',
  // Web/API Phase 7 Batch 7O2a — registry reads (read-only). A failed read
  // is always shown as an error, never as an empty history.
  VEHICLE_BRANCH_FILTER_UNAVAILABLE:
    'ตารางทะเบียนรถยังไม่มีช่องสาขาที่รับผิดชอบ จึงกรองตามสาขาไม่ได้ กรุณาล้างตัวกรองสาขา',
  REGISTRY_DATA_CONTEXT_NOT_CONFIGURED:
    'ระบบยังไม่ได้ตั้งค่าขอบเขตข้อมูลทะเบียน/สาขา จึงยังแสดงข้อมูลส่วนนี้ไม่ได้ กรุณาติดต่อผู้ดูแลระบบ',
  BRANCH_MASTER_SCHEMA_INVALID: 'โครงสร้างตารางรายชื่อสาขาไม่ตรงกับที่ระบบรองรับ จึงโหลดชื่อสาขาไม่ได้',
  BRANCH_MASTER_DATA_INVALID: 'ข้อมูลรายชื่อสาขาบางรายการไม่ถูกต้อง (เช่น รหัสซ้ำ) จึงโหลดชื่อสาขาไม่ได้',
  BRANCH_MASTER_READ_FAILED: 'ไม่สามารถอ่านรายชื่อสาขาได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
  PROVINCE_MASTER_SCHEMA_INVALID: 'โครงสร้างตารางรายชื่อจังหวัดไม่ตรงกับที่ระบบรองรับ จึงโหลดชื่อจังหวัดไม่ได้',
  PROVINCE_MASTER_DATA_INVALID: 'ข้อมูลรายชื่อจังหวัดบางรายการไม่ถูกต้อง (เช่น รหัสซ้ำ) จึงโหลดชื่อจังหวัดไม่ได้',
  PROVINCE_MASTER_READ_FAILED: 'ไม่สามารถอ่านรายชื่อจังหวัดได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
  BRANCH_HISTORY_SCHEMA_INVALID:
    'โครงสร้างตารางประวัติสาขาที่รับผิดชอบไม่ตรงกับที่ระบบรองรับ จึงแสดงประวัติไม่ได้ กรุณาติดต่อผู้ดูแลระบบ',
  BRANCH_HISTORY_DATA_INVALID:
    'ข้อมูลประวัติสาขาของรถคันนี้บางรายการไม่ถูกต้อง จึงแสดงประวัติไม่ได้ เพื่อไม่ให้สาขาที่แสดงคลาดเคลื่อน กรุณาแจ้งผู้ดูแลข้อมูล',
  BRANCH_HISTORY_READ_FAILED: 'ไม่สามารถอ่านประวัติสาขาที่รับผิดชอบได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
  REGISTRATION_HISTORY_SCHEMA_INVALID:
    'โครงสร้างตารางประวัติทะเบียนรถไม่ตรงกับที่ระบบรองรับ จึงแสดงประวัติไม่ได้ กรุณาติดต่อผู้ดูแลระบบ',
  REGISTRATION_HISTORY_DATA_INVALID:
    'ข้อมูลประวัติทะเบียนของรถคันนี้บางรายการไม่ถูกต้อง จึงแสดงประวัติไม่ได้ กรุณาแจ้งผู้ดูแลข้อมูล',
  REGISTRATION_HISTORY_READ_FAILED: 'ไม่สามารถอ่านประวัติทะเบียนรถได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง',
  // Web/API Phase 7 Batch 7O2b — registration changes. These codes are shown
  // only for a proven refusal (nothing was saved by that request); an
  // uncertain outcome is never described with them (see registrationWriteText).
  REQUEST_ID_REQUIRED: 'คำขอไม่มีรหัสคำขอที่ถูกต้อง ระบบจึงไม่ได้ดำเนินการ กรุณาลองใหม่อีกครั้ง',
  VEHICLE_ID_AMBIGUOUS: 'รหัสยานพาหนะนี้ซ้ำกันในข้อมูลทะเบียนรถ ระบบจึงไม่ได้แก้ไข กรุณาแจ้งผู้ดูแลข้อมูล',
  REGISTRATION_TEXT_INVALID: 'ทะเบียนต้องยาว 1–50 ตัวอักษร และต้องมีตัวอักษรหรือตัวเลขอย่างน้อยหนึ่งตัว',
  REGISTRATION_TEXT_REQUIRED: 'ต้องกรอกทะเบียนก่อนจึงจะระบุจังหวัดได้',
  REGISTRATION_PROJECTION_MISMATCH:
    'ทะเบียนในข้อมูลทะเบียนรถไม่ตรงกับประวัติล่าสุด ต้องปรับข้อมูลให้ตรงกันก่อนจึงจะแก้ไขได้',
  VEHICLE_REGISTRY_STALE: 'มีผู้อื่นแก้ไขทะเบียนของรถคันนี้ไปแล้ว กรุณาโหลดข้อมูลใหม่แล้วตรวจสอบอีกครั้ง',
  PROVINCE_NOT_FOUND: 'ไม่พบรหัสจังหวัดนี้ในรายชื่อจังหวัด',
  PROVINCE_INACTIVE: 'จังหวัดนี้ถูกปิดใช้งาน จึงเลือกใหม่ไม่ได้',
  REGISTRATION_DUPLICATE: 'ทะเบียนและจังหวัดนี้ถูกใช้กับรถคันอื่นอยู่แล้ว',
  RECONCILIATION_MODE_INVALID: 'กรุณาเลือกวิธีปรับข้อมูลให้ตรงกัน',
  REASON_REQUIRED: 'กรุณาระบุเหตุผล',
  RELATED_REQUEST_NOT_FOUND: 'ไม่พบรหัสคำขอที่อ้างถึงในประวัติทะเบียนของรถคันนี้',
  REGISTRATION_HISTORY_STALE: 'ประวัติทะเบียนเปลี่ยนไปแล้วหลังจากที่โหลด กรุณาโหลดข้อมูลใหม่แล้วตรวจสอบอีกครั้ง',
  MASTER_PAIR_INVALID:
    'ทะเบียนในข้อมูลทะเบียนรถไม่ถูกต้องตามกฎ จึงยอมรับค่านี้ไม่ได้ กรุณาใช้ค่าตามประวัติหรือแจ้งผู้ดูแลข้อมูล',
  // Web/API Phase 7 Batch 7O2c — responsible-branch changes (proven refusals only).
  BRANCH_HISTORY_STALE: 'ประวัติสาขาหรือสาขาปัจจุบันเปลี่ยนไปแล้วหลังจากที่โหลด กรุณาโหลดข้อมูลใหม่แล้วตรวจสอบอีกครั้ง',
  BRANCH_TIMELINE_AMBIGUOUS:
    'ประวัติสาขามีรายการที่มีผลเวลาเดียวกัน จึงระบุลำดับไม่ได้ ระบบจึงไม่ได้บันทึก (แก้ไขหรือยกเลิกได้เฉพาะรายการที่มีผลเวลาเดียวกัน และต้องระบุสาขาเดิมได้ชัดเจน)',
  BRANCH_PROJECTION_MISMATCH:
    'สาขาในข้อมูลทะเบียนรถไม่ตรงกับประวัติ ต้องปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติก่อน',
  BRANCH_EVENT_SAME_INSTANT: 'มีรายการย้ายสาขาที่มีผลเวลาเดียวกันนี้อยู่แล้ว กรุณาเลือกเวลาอื่น',
  BRANCH_TRANSFER_NOT_LATEST:
    'เวลาที่มีผลไม่ใช่เวลาล่าสุดในประวัติ หากเป็นการย้ายในอดีต ให้ใช้ "เพิ่มประวัติย้อนหลัง"',
  BRANCH_INSERTION_NOT_HISTORICAL:
    'เวลาที่มีผลต้องอยู่ก่อนรายการล่าสุดในประวัติ หากเป็นการย้ายครั้งใหม่ ให้ใช้ "ย้ายสาขา"',
  BRANCH_EVENT_NOT_FOUND: 'ไม่พบรายการนี้ในประวัติสาขาของรถคันนี้',
  BRANCH_EVENT_CANCELLED: 'รายการนี้ถูกยกเลิกไปแล้ว',
  BRANCH_NOT_FOUND: 'ไม่พบรหัสสาขานี้ในรายชื่อสาขา',
  BRANCH_INACTIVE: 'สาขานี้ถูกปิดใช้งาน จึงเลือกไม่ได้',
  EFFECTIVE_MODE_INVALID: 'รูปแบบเวลาที่มีผลไม่ถูกต้อง',
  EFFECTIVE_MODE_NOT_ALLOWED: 'รายการนี้ต้องระบุวันที่หรือวันที่และเวลา (ใช้ "ตอนนี้" ไม่ได้)',
  EFFECTIVE_TIME_OFFSET_REQUIRED: 'เวลาที่มีผลต้องระบุเขตเวลา',
  EFFECTIVE_TIME_PRECISION: 'เวลาที่มีผลระบุได้ละเอียดถึงวินาทีเท่านั้น',
  FUTURE_EFFECTIVE_NOT_ALLOWED: 'เวลาที่มีผลต้องไม่อยู่ในอนาคต',
  EFFECTIVE_TIME_OUT_OF_RANGE: 'เวลาที่มีผลต้องไม่ก่อน 1 ม.ค. 2533 (00:00 UTC)',
  // R2 Batch R2e — personnel / department lifecycle (deactivate / reactivate / reconcile).
  PERSONNEL_NOT_FOUND: 'ไม่พบข้อมูลบุคลากรนี้',
  PERSONNEL_ID_AMBIGUOUS: 'พบข้อมูลบุคลากรรหัสนี้มากกว่าหนึ่งรายการ ระบบจึงไม่ดำเนินการ กรุณาแจ้งผู้ดูแลข้อมูล',
  DEPARTMENT_NOT_FOUND: 'ไม่พบข้อมูลแผนกนี้',
  DEPARTMENT_ID_AMBIGUOUS: 'พบข้อมูลแผนกรหัสนี้มากกว่าหนึ่งรายการ ระบบจึงไม่ดำเนินการ กรุณาแจ้งผู้ดูแลข้อมูล',
  PERSONNEL_LIFECYCLE_STALE: 'ข้อมูลถูกเปลี่ยนโดยผู้ใช้อื่น กรุณาโหลดข้อมูลล่าสุดก่อนดำเนินการอีกครั้ง',
  DEPARTMENT_LIFECYCLE_STALE: 'ข้อมูลถูกเปลี่ยนโดยผู้ใช้อื่น กรุณาโหลดข้อมูลล่าสุดก่อนดำเนินการอีกครั้ง',
  PERSONNEL_LIFECYCLE_MISMATCH:
    'สถานะปัจจุบันไม่ตรงกับประวัติสถานะล่าสุด ต้องซิงก์สถานะให้ตรงกับประวัติล่าสุดก่อน',
  DEPARTMENT_LIFECYCLE_MISMATCH:
    'สถานะปัจจุบันไม่ตรงกับประวัติสถานะล่าสุด ต้องซิงก์สถานะให้ตรงกับประวัติล่าสุดก่อน',
  PERSONNEL_LIFECYCLE_STATE_INVALID: 'สถานะปัจจุบันของบุคลากรนี้ไม่ใช่ค่าที่ระบบรู้จัก จึงเปลี่ยนสถานะไม่ได้',
  DEPARTMENT_LIFECYCLE_STATE_INVALID: 'สถานะปัจจุบันของแผนกนี้ไม่ใช่ค่าที่ระบบรู้จัก จึงเปลี่ยนสถานะไม่ได้',
  PERSONNEL_MASTER_SCHEMA_INVALID: 'ข้อมูลบุคลากรในระบบมีโครงสร้างไม่ถูกต้อง ไม่สามารถแสดงข้อมูลได้',
  PERSONNEL_MASTER_DATA_INVALID: 'ข้อมูลบุคลากรในระบบไม่ถูกต้อง ไม่สามารถแสดงข้อมูลได้ กรุณาแจ้งผู้ดูแลข้อมูล',
  PERSONNEL_MASTER_READ_FAILED: 'อ่านข้อมูลบุคลากรไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  DEPARTMENT_MASTER_SCHEMA_INVALID: 'ข้อมูลแผนกยังไม่พร้อมใช้งานในระบบ (ไม่ใช่รายการว่าง)',
  DEPARTMENT_MASTER_DATA_INVALID: 'ข้อมูลแผนกในระบบไม่ถูกต้อง ไม่สามารถแสดงข้อมูลได้ กรุณาแจ้งผู้ดูแลข้อมูล',
  DEPARTMENT_MASTER_READ_FAILED: 'อ่านข้อมูลแผนกไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  PERSONNEL_LIFECYCLE_HISTORY_SCHEMA_INVALID: 'ประวัติสถานะบุคลากรยังไม่พร้อมใช้งานในระบบ',
  DEPARTMENT_LIFECYCLE_HISTORY_SCHEMA_INVALID: 'ประวัติสถานะแผนกยังไม่พร้อมใช้งานในระบบ',
  PERSONNEL_LIFECYCLE_HISTORY_DATA_INVALID: 'ประวัติสถานะบุคลากรไม่ถูกต้อง กรุณาแจ้งผู้ดูแลข้อมูล',
  DEPARTMENT_LIFECYCLE_HISTORY_DATA_INVALID: 'ประวัติสถานะแผนกไม่ถูกต้อง กรุณาแจ้งผู้ดูแลข้อมูล',
  PERSONNEL_LIFECYCLE_HISTORY_READ_FAILED: 'อ่านประวัติสถานะบุคลากรไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  DEPARTMENT_LIFECYCLE_HISTORY_READ_FAILED: 'อ่านประวัติสถานะแผนกไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  // R2 Batch R2-C2a — relationships, department history, caretaker and permanent responsibility.
  HTTP_ERROR: 'คุณไม่มีสิทธิ์ทำรายการนี้ หรือคำขอไม่ได้รับอนุญาต',
  REQUEST_ID_REUSED: 'รหัสคำขอนี้ถูกใช้กับข้อมูลอื่นแล้ว ระบบไม่ได้บันทึกซ้ำ',
  TECHNICIAN_NOT_ACTIVE: 'ช่างรหัสนี้ไม่อยู่ในสถานะใช้งาน (ACTIVE) จึงกำหนดเป็นผู้ดูแลไม่ได้',
  TECHNICIAN_PERSONNEL_UNRESOLVED: 'ช่างรหัสนี้ยังไม่ได้เชื่อมโยงกับบุคลากร จึงกำหนดเป็นผู้ดูแลไม่ได้',
  TECHNICIAN_PERSONNEL_AMBIGUOUS: 'มีบุคลากรมากกว่าหนึ่งรายการที่เชื่อมโยงกับช่างรหัสนี้ ระบบไม่เลือกให้',
  DRIVER_NOT_ACTIVE: 'คนขับ/ผู้ควบคุมรหัสนี้ไม่อยู่ในสถานะใช้งาน (ACTIVE) จึงกำหนดเป็นผู้รับผิดชอบรถประจำไม่ได้',
  DRIVER_PERSONNEL_AMBIGUOUS: 'มีบุคลากรมากกว่าหนึ่งรายการที่เชื่อมโยงกับคนขับรหัสนี้ ระบบไม่เลือกให้',
  PERSONNEL_NOT_ACTIVE: 'บุคลากรที่เชื่อมโยงกับรหัสนี้ไม่อยู่ในสถานะใช้งาน (ACTIVE)',
  EQUIPMENT_SCOPE_UNPROVEN: 'อุปกรณ์นี้ไม่อยู่ในขอบเขตข้อมูลปัจจุบัน (TEST/REAL) จึงแสดงหรือบันทึกผู้ดูแลไม่ได้',
  VEHICLE_SCOPE_UNPROVEN: 'รถคันนี้ไม่อยู่ในขอบเขตข้อมูลปัจจุบัน (TEST/REAL) จึงแสดงหรือบันทึกผู้รับผิดชอบรถประจำไม่ได้',
  CARETAKER_HISTORY_STALE: 'ข้อมูลผู้ดูแลเปลี่ยนไปหลังจากที่โหลดข้อมูล กรุณาโหลดข้อมูลล่าสุดแล้วลองใหม่',
  CARETAKER_TIMELINE_AMBIGUOUS: 'ลำดับประวัติผู้ดูแลไม่ชัดเจน (มีรายการเวลาเดียวกัน) ต้องแก้ไขหรือยกเลิกรายการที่ชนกันก่อน',
  CARETAKER_EVENT_SAME_INSTANT: 'มีรายการผู้ดูแลที่มีผลในเวลาเดียวกันอยู่แล้ว',
  CARETAKER_EVENT_NOT_LATEST: 'เวลาที่ระบุก่อนรายการล่าสุด ให้ใช้ "เพิ่มประวัติย้อนหลัง" หรือแก้ไขรายการเดิม',
  CARETAKER_INSERTION_NOT_HISTORICAL: 'ไม่มีรายการที่ใหม่กว่าเวลาที่ระบุ ให้ใช้ "เปลี่ยนผู้ดูแล" แทน',
  CARETAKER_EVENT_CANCELLED: 'รายการนี้ถูกยกเลิกแล้ว',
  CARETAKER_EVENT_NOT_FOUND: 'ไม่พบรายการผู้ดูแลนี้ในประวัติ',
  CARETAKER_END_WITHOUT_CARETAKER: 'ไม่มีผู้ดูแลก่อนเวลานี้ จึงสิ้นสุดการดูแลที่เวลานี้ไม่ได้',
  CARETAKER_TECHNICIAN_REQUIRED: 'กรุณาระบุรหัสช่าง',
  CARETAKER_CORRECTION_CHANGES_EVENT_NATURE: 'การแก้ไขรายการสิ้นสุดการดูแลต้องไม่ระบุช่าง (ให้ยกเลิกรายการแทน)',
  CARETAKER_HISTORY_WRITE_FAILED: 'บันทึกประวัติผู้ดูแลไม่สำเร็จหรือไม่ทราบผล',
  EQUIPMENT_CARETAKER_HISTORY_READ_FAILED: 'อ่านประวัติผู้ดูแลอุปกรณ์ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  EQUIPMENT_CARETAKER_HISTORY_SCHEMA_INVALID: 'ประวัติผู้ดูแลอุปกรณ์ยังไม่พร้อมใช้งานในระบบ',
  EQUIPMENT_CARETAKER_HISTORY_DATA_INVALID: 'ประวัติผู้ดูแลอุปกรณ์ไม่ถูกต้อง กรุณาแจ้งผู้ดูแลข้อมูล',
  DRIVER_RESPONSIBILITY_HISTORY_STALE: 'ข้อมูลผู้รับผิดชอบรถประจำเปลี่ยนไปหลังจากที่โหลดข้อมูล กรุณาโหลดข้อมูลล่าสุดแล้วลองใหม่',
  DRIVER_RESPONSIBILITY_TIMELINE_AMBIGUOUS: 'ลำดับประวัติผู้รับผิดชอบรถประจำไม่ชัดเจน (มีรายการเวลาเดียวกัน) ต้องแก้ไขหรือยกเลิกรายการที่ชนกันก่อน',
  DRIVER_RESPONSIBILITY_EVENT_SAME_INSTANT: 'มีรายการผู้รับผิดชอบรถประจำที่มีผลในเวลาเดียวกันอยู่แล้ว',
  DRIVER_RESPONSIBILITY_EVENT_NOT_LATEST: 'เวลาที่ระบุก่อนรายการล่าสุด ให้ใช้ "เพิ่มประวัติย้อนหลัง" หรือแก้ไขรายการเดิม',
  DRIVER_RESPONSIBILITY_INSERTION_NOT_HISTORICAL: 'ไม่มีรายการที่ใหม่กว่าเวลาที่ระบุ ให้ใช้ "เปลี่ยนผู้รับผิดชอบ" แทน',
  DRIVER_RESPONSIBILITY_EVENT_CANCELLED: 'รายการนี้ถูกยกเลิกแล้ว',
  DRIVER_RESPONSIBILITY_EVENT_NOT_FOUND: 'ไม่พบรายการผู้รับผิดชอบรถประจำนี้ในประวัติ',
  DRIVER_RESPONSIBILITY_END_WITHOUT_DRIVER: 'ไม่มีผู้รับผิดชอบก่อนเวลานี้ จึงสิ้นสุดความรับผิดชอบที่เวลานี้ไม่ได้',
  DRIVER_RESPONSIBILITY_DRIVER_REQUIRED: 'กรุณาระบุรหัสคนขับ/ผู้ควบคุม (ระบบไม่เลือกให้)',
  DRIVER_RESPONSIBILITY_CORRECTION_CHANGES_EVENT_NATURE: 'การแก้ไขรายการสิ้นสุดความรับผิดชอบต้องไม่ระบุคนขับ (ให้ยกเลิกรายการแทน)',
  DRIVER_RESPONSIBILITY_HISTORY_WRITE_FAILED: 'บันทึกประวัติผู้รับผิดชอบรถประจำไม่สำเร็จหรือไม่ทราบผล',
  CRANE_DRIVER_RESPONSIBILITY_HISTORY_READ_FAILED: 'อ่านประวัติผู้รับผิดชอบรถประจำไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  CRANE_DRIVER_RESPONSIBILITY_HISTORY_SCHEMA_INVALID: 'ประวัติผู้รับผิดชอบรถประจำยังไม่พร้อมใช้งานในระบบ',
  CRANE_DRIVER_RESPONSIBILITY_HISTORY_DATA_INVALID: 'ประวัติผู้รับผิดชอบรถประจำไม่ถูกต้อง กรุณาแจ้งผู้ดูแลข้อมูล',
  PERSONNEL_DEPARTMENT_HISTORY_READ_FAILED: 'อ่านประวัติการสังกัดแผนกไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  PERSONNEL_DEPARTMENT_HISTORY_SCHEMA_INVALID: 'ประวัติการสังกัดแผนกยังไม่พร้อมใช้งานในระบบ',
  PERSONNEL_DEPARTMENT_HISTORY_DATA_INVALID: 'ประวัติการสังกัดแผนกไม่ถูกต้อง กรุณาแจ้งผู้ดูแลข้อมูล',
}

/** Web/API Phase 7 Batch 7O2b — registration editor and outcome banners
 * (contract Final Rev2 §10.2-§10.4; Outcome Classification Addendum A.2).
 * An uncertain outcome is never described as "not saved". */
export const registrationWriteText = {
  unknown: 'ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ',
  unconfirmed: 'ยังไม่พบคำขอนี้ในประวัติ หากต้องการ สามารถส่งคำขอเดิมอีกครั้งได้ (ใช้รหัสคำขอเดิม จะไม่บันทึกซ้ำ)',
  pending:
    'บันทึกในประวัติแล้ว แต่ทะเบียนในข้อมูลทะเบียนรถยังไม่ตรงกับประวัติ — ต้องปรับข้อมูลให้ตรงกัน',
  conflict: 'รหัสคำขอนี้ถูกใช้กับข้อมูลอื่นแล้ว — ต้องตรวจสอบกับผู้ดูแลระบบ',
  submitting: 'กำลังส่งคำขอ...',
  memoryOnly: 'คำเตือนนี้จะหายเมื่อออกจากหน้า',
  acknowledgeHint:
    'การกด "รับทราบ" ลบคำเตือนในเครื่องนี้เท่านั้น ไม่ได้เปลี่ยนข้อมูลในระบบ ไม่ใช่การปรับข้อมูลให้ตรงกัน และไม่ได้ยืนยันว่าการบันทึกครั้งแรกสำเร็จหรือไม่',
  applied: 'บันทึกทะเบียนเรียบร้อยแล้ว',
  noop: 'ทะเบียนเท่ากับค่าปัจจุบันอยู่แล้ว จึงไม่มีการเปลี่ยนแปลง',
  settled: 'ตรวจสอบจากประวัติแล้ว: คำขอนี้ถูกบันทึกและข้อมูลตรงกันแล้ว',
  settledLater: 'ตรวจสอบจากประวัติแล้ว: คำขอนี้ถูกบันทึกแล้ว และมีการเปลี่ยนแปลงภายหลัง',
  duplicateWarning: 'หมายเหตุ: มีรถคันอื่นใช้ทะเบียนและจังหวัดเดียวกันอยู่แล้ว',
  notInSchema: 'แหล่งข้อมูลยังไม่มีช่องนี้ จึงแก้ไขทะเบียนไม่ได้',
  noUser: 'ไม่ทราบผู้ใช้ปัจจุบัน จึงแก้ไขทะเบียนไม่ได้ในขณะนี้',
  provincesUnavailable: 'โหลดรายชื่อจังหวัดไม่ได้ จึงเลือกจังหวัดใหม่ไม่ได้จนกว่าจะโหลดสำเร็จ',
} as const

/** Web/API Phase 7 Batch 7O2c — responsible-branch actions and outcome
 * banners. NOT_DETERMINED (recorded, timeline still ambiguous, vehicle record
 * left unchanged) is never described as a completed change. */
export const branchWriteText = {
  unknown: 'ยังไม่ทราบผลการบันทึก — ระบบจะตรวจสอบจากประวัติ',
  unconfirmed: registrationWriteText.unconfirmed,
  pending:
    'บันทึกในประวัติสาขาแล้ว แต่สาขาในข้อมูลทะเบียนรถยังไม่ตรงกับประวัติหรือยังระบุไม่ได้ — ยังไม่ถือว่าเสร็จสมบูรณ์',
  notDetermined:
    'บันทึกในประวัติสาขาแล้ว แต่ประวัติยังมีรายการที่มีผลเวลาเดียวกัน จึงยังระบุสาขาปัจจุบันไม่ได้ และไม่ได้เปลี่ยนสาขาในข้อมูลทะเบียนรถ',
  conflict: registrationWriteText.conflict,
  submitting: registrationWriteText.submitting,
  memoryOnly: registrationWriteText.memoryOnly,
  acknowledgeHint: registrationWriteText.acknowledgeHint,
  applied: 'บันทึกการเปลี่ยนแปลงสาขาเรียบร้อยแล้ว',
  noop: 'ข้อมูลเท่ากับค่าปัจจุบันอยู่แล้ว จึงไม่มีการเปลี่ยนแปลง',
  settled: 'ตรวจสอบจากประวัติสาขาแล้ว: คำขอนี้ถูกบันทึกและข้อมูลตรงกันแล้ว',
  settledLater: 'ตรวจสอบจากประวัติสาขาแล้ว: คำขอนี้ถูกบันทึกแล้ว และมีการเปลี่ยนแปลงภายหลัง',
  w1Rejected: 'ระบบปลายทางปฏิเสธการบันทึกคำขอนี้ จึงไม่มีการเปลี่ยนแปลงจากคำขอนี้ กรุณาลองใหม่อีกครั้ง',
  relatedNotFound: 'ไม่พบรหัสคำขอที่อ้างถึงในประวัติสาขาของรถคันนี้',
  masterNotInSchema: 'แหล่งข้อมูลยังไม่มีช่องสาขาที่รับผิดชอบ จึงเปลี่ยนสาขาไม่ได้',
  noUser: 'ไม่ทราบผู้ใช้ปัจจุบัน จึงเปลี่ยนสาขาไม่ได้ในขณะนี้',
  historyUnavailable: 'ต้องโหลดประวัติสาขาสำเร็จก่อน จึงจะเปลี่ยนแปลงสาขาได้',
  branchesUnavailable: 'โหลดรายชื่อสาขาไม่ได้ จึงเลือกสาขาไม่ได้จนกว่าจะโหลดสำเร็จ',
} as const

export const branchOperationLabel: Record<string, string> = {
  transfer: 'ย้ายสาขา',
  insertion: 'เพิ่มประวัติย้อนหลัง',
  correction: 'แก้ไขประวัติ',
  cancellation: 'ยกเลิกรายการ',
  reconcile: 'ปรับข้อมูลสาขาปัจจุบันให้ตรงกับประวัติ',
}

export const registrationIntentStateLabel: Record<string, string> = {
  SUBMITTING: 'กำลังส่ง',
  UNKNOWN: 'ยังไม่ทราบผล',
  UNCONFIRMED: 'ยังไม่พบในประวัติ',
  RECORDED_PROJECTION_PENDING: 'บันทึกแล้ว รอปรับข้อมูลให้ตรงกัน',
  CONFLICT: 'รหัสคำขอขัดแย้ง',
}

export const registrationAcceptedExceptionLabel: Record<string, string> = {
  REFERENCE_UNKNOWN_ACCEPTED: 'ยอมรับรหัสจังหวัดที่ไม่อยู่ในรายชื่อ',
  REFERENCE_INACTIVE_ACCEPTED: 'ยอมรับจังหวัดที่ปิดใช้งาน',
  EXISTING_DUPLICATE_PAIR: 'ยอมรับทะเบียนที่ซ้ำกับรถคันอื่น',
}

/** The one approved `certificate_status` vocabulary (Web/API Phase 6
 * Batch 2A) — distinct from `certificate_type_code`, which has no
 * approved vocabulary and must never appear here (see
 * `lib/types.ts` VehicleCertificate docstring). */
export const certificateStatusLabel: Record<string, string> = {
  ACTIVE: 'ยังใช้งานได้',
  REPLACED: 'ถูกแทนที่แล้ว',
  EXPIRED: 'หมดอายุ',
}

export const certificateStatusTone: Record<string, StatusTone> = {
  ACTIVE: 'success',
  REPLACED: 'neutral',
  EXPIRED: 'danger',
}

/** Core Demo Fixes — Store/Inventory integration boundary. */
export const requisitionSourceTypeLabel: Record<string, string> = {
  PM: 'งาน PM',
  REPAIR: 'งานซ่อม',
}

/** Map a stable backend error `code` to Thai text, falling back to a
 * generic Thai message for unknown codes (per docs/architecture/API_CONVENTIONS.md). */
export function describeErrorCode(code: string | undefined): string {
  if (code && knownErrorMessages[code]) return knownErrorMessages[code]
  return 'เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ กรุณาลองใหม่อีกครั้ง'
}

export function formatThaiDateTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat('th-TH', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

export function formatThaiDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium' }).format(new Date(iso))
  } catch {
    return iso
  }
}

// ---------------------------------------------------------------------------
// Web/API Phase 7 Batch 7C2 — opened-at display for the open-repair report
// ONLY. `formatThaiDateTime` above is deliberately left unchanged for every
// other page. No age, duration or overdue value is ever derived here.
// ---------------------------------------------------------------------------

export const REPORT_OPENED_AT_UNREADABLE = 'ไม่มีวันที่เปิดใบงานที่อ่านได้'
export const REPORT_TIMEZONE_UNSPECIFIED = '(ไม่ระบุเขตเวลา)'

const REPORT_ISO =
  /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?)?(Z|[+-]\d{2}:?\d{2})?$/i

const bangkokDateTime = new Intl.DateTimeFormat('th-TH', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'Asia/Bangkok',
})

/** Calendar/clock fields are checked explicitly, so an impossible value
 * (e.g. 2026-02-30 or 25:00) is shown as raw text instead of rolling over. */
function validWallClock(y: number, mo: number, d: number, h: number, mi: number, s: number): boolean {
  const date = new Date(Date.UTC(y, mo - 1, d))
  return (
    date.getUTCFullYear() === y &&
    date.getUTCMonth() === mo - 1 &&
    date.getUTCDate() === d &&
    h <= 23 &&
    mi <= 59 &&
    s <= 59
  )
}

/**
 * Display text for a repair's `opened_at` in the open-repair report:
 * - offset-bearing ISO timestamp → Thai date/time in Asia/Bangkok;
 * - the instant 1970-01-01T00:00:00Z (any offset spelling) → the
 *   "no readable opened date" text. This is a display convention only:
 *   the response cannot prove whether that value was a fallback or an
 *   explicitly stored date;
 * - ISO text without a zone → the stored wall-clock text as-is plus
 *   "(ไม่ระบุเขตเวลา)", never reinterpreted as UTC or browser-local time;
 * - anything else → the raw text (rendered as text, never as markup).
 */
export function formatRepairReportOpenedAt(value: string): string {
  if (!value.trim()) return REPORT_OPENED_AT_UNREADABLE
  const match = REPORT_ISO.exec(value)
  if (!match) return value
  const [, ys, mos, ds, hs = '0', mis = '0', ss = '0', frac = '', zone] = match
  const [y, mo, d, h, mi, s] = [ys, mos, ds, hs, mis, ss].map(Number)
  if (!validWallClock(y, mo, d, h, mi, s)) return value
  if (!zone) return `${value} ${REPORT_TIMEZONE_UNSPECIFIED}`
  let offsetMinutes = 0
  if (zone.toUpperCase() !== 'Z') {
    const digits = zone.replace(':', '')
    const oh = Number(digits.slice(1, 3))
    const om = Number(digits.slice(3, 5))
    if (oh > 23 || om > 59) return value
    offsetMinutes = (zone.startsWith('-') ? -1 : 1) * (oh * 60 + om)
  }
  const ms = Number(`0.${frac || '0'}`) * 1000
  const instant = Date.UTC(y, mo - 1, d, h, mi, s) + ms - offsetMinutes * 60_000
  if (instant === 0) return REPORT_OPENED_AT_UNREADABLE
  return bangkokDateTime.format(new Date(instant))
}

// ---------------------------------------------------------------------------
// Web/API Phase 7 Batch 7D2 — certificate expiry report ONLY. Every flag and
// disclosure is an observation from the data read: it never states legal
// validity, compliance, or that one certificate replaced another. Stored
// status labels reuse `certificateStatusLabel` above. `formatThaiDate` is
// deliberately left unchanged for every other page.
// ---------------------------------------------------------------------------

export const certificateReportFlagLabel: Record<string, string> = {
  SAME_TYPE_ACTIVE_EXISTS: 'ในข้อมูลมีใบรับรองประเภทเดียวกันของรถคันนี้ที่ยังใช้งานได้ (ข้อสังเกต ไม่ได้ยืนยันว่าเป็นใบแทน)',
  MULTIPLE_ACTIVE_SAME_TYPE: 'พบใบรับรองประเภทเดียวกันของรถคันนี้ที่ยังใช้งานได้มากกว่า 1 รายการ',
  STORED_ACTIVE_PAST_EXPIRY: 'บันทึกว่ายังใช้งานได้ แต่วันหมดอายุผ่านไปแล้ว',
  STORED_EXPIRED_EXPIRY_NOT_BEFORE_TODAY: 'บันทึกว่าหมดอายุ แต่วันหมดอายุคือวันนี้หรือยังมาไม่ถึง',
  LINK_PRESENT_ON_NON_REPLACED: 'มีรหัสใบแทนบันทึกไว้ ทั้งที่ไม่ได้บันทึกว่าถูกแทนที่',
  DUPLICATE_CERTIFICATE_ID: 'รหัสใบรับรองนี้ซ้ำกับรายการอื่นในข้อมูล',
  BLANK_CERTIFICATE_ID: 'ไม่มีรหัสใบรับรองในข้อมูล',
  BLANK_VEHICLE_ID: 'ไม่มีรหัสรถในข้อมูล',
}

export const certificateReportDefectLabel: Record<string, string> = {
  UNRECOGNIZED_STATUS: 'สถานะใบรับรองอ่านไม่ได้หรือไม่ใช่ค่าที่ระบบรู้จัก',
  INVALID_EXPIRY_DATE: 'วันหมดอายุอ่านไม่ได้',
  UNMAPPABLE_ROW: 'ข้อมูลอื่นของรายการอ่านไม่ได้',
}

export const certificateExpiryPositionLabel: Record<string, string> = {
  BEFORE_TODAY: 'หมดอายุก่อนวันนี้',
  TODAY: 'หมดอายุวันนี้',
  AFTER_TODAY: 'หมดอายุหลังวันนี้',
  NO_EXPIRY_DATE: 'ไม่มีวันหมดอายุในระบบ',
}

const REPORT_CALENDAR_DATE = /^(\d{4})-(\d{2})-(\d{2})$/

const utcCalendarDate = new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium', timeZone: 'UTC' })

/** A `YYYY-MM-DD` calendar date (no time, no zone) in Thai, built and
 * formatted in UTC explicitly so it never shifts a day in a browser west
 * (or east) of UTC. Anything else — including impossible dates such as
 * 2026-02-30 — is returned unchanged as text. */
export function formatReportCalendarDate(value: string): string {
  const match = REPORT_CALENDAR_DATE.exec(value)
  if (!match) return value
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const instant = new Date(Date.UTC(y, m - 1, d))
  if (instant.getUTCFullYear() !== y || instant.getUTCMonth() !== m - 1 || instant.getUTCDate() !== d) {
    return value
  }
  return utcCalendarDate.format(instant)
}

// ---------------------------------------------------------------------------
// Web/API Phase 7 Batch 7E2 — recorded inspection findings report ONLY.
// Rows are recorded history: no label states that a defect is still
// unresolved, was fixed, or is outstanding work.
// ---------------------------------------------------------------------------

export const inspectionFindingReportFlagLabel: Record<string, string> = {
  DUPLICATE_FINDING_ID: 'รหัสข้อบกพร่องซ้ำ',
  BLANK_FINDING_ID: 'ไม่มีรหัสข้อบกพร่อง',
  BLANK_INSPECTION_ID: 'ไม่มีรหัสผลการตรวจ',
  BLANK_RESULT_ID: 'ไม่มีรหัสผลรายการตรวจ',
}

export const inspectionFindingReportDefectLabel: Record<string, string> = {
  UNSUPPORTED_TEXT_VALUE: 'ค่ารหัส/ข้อความอยู่ในรูปแบบที่อ่านไม่ได้',
  BLANK_ASSET_TYPE: 'ไม่มีประเภททรัพย์สิน',
  UNRECOGNIZED_ASSET_TYPE: 'ประเภททรัพย์สินไม่ถูกต้อง',
  BLANK_ASSET_ID: 'ไม่มีรหัสทรัพย์สิน',
  BLANK_STATUS: 'ไม่มีสถานะ',
  UNRECOGNIZED_STATUS: 'สถานะไม่ถูกต้อง',
  MISSING_CREATED_AT: 'ไม่มีวันที่บันทึก',
  INVALID_CREATED_AT: 'วันที่บันทึกไม่ถูกต้อง',
  CREATED_AT_WITHOUT_TIMEZONE: 'วันที่บันทึกไม่ระบุเขตเวลา',
  UNREPRESENTABLE_CREATED_AT: 'วันที่บันทึกอยู่นอกช่วงที่ระบบแสดงได้',
  UNMAPPABLE_ROW: 'แถวข้อมูลอ่านไม่ได้',
}

export const inspectionFindingRecordedStatusLabel: Record<string, string> = {
  OPEN: 'OPEN (ค่าที่บันทึก)',
}

/** A readable report `created_at` (a UTC instant from the backend) shown
 * as Thai date/time in Asia/Bangkok, independent of the browser's zone.
 * Text that is not a parseable instant is returned unchanged. */
export function formatReportInstantBangkok(value: string): string {
  const instant = new Date(value)
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(value) || Number.isNaN(instant.getTime())) return value
  return bangkokDateTime.format(instant)
}

// ---------------------------------------------------------------------------
// Web/API Phase 7 Batch 7O2a — registry history display (read-only; contract
// Final Rev2 §4.5, §5.4, §7.4). Codes not listed here are shown raw.
// ---------------------------------------------------------------------------

export const branchCurrentSourceLabel: Record<string, string> = {
  EVENT: 'ตามประวัติการย้ายสาขา',
  BASELINE: 'ตามสาขาเดิมก่อนมีประวัติการย้าย',
  IMPORTED_MASTER: 'ตามข้อมูลทะเบียนรถ (ยังไม่มีประวัติการย้าย)',
  NONE: 'ไม่มีสาขา',
  UNDETERMINED: 'ยังระบุไม่ได้',
}

export const branchConsistencyLabel: Record<string, string> = {
  CONSISTENT: 'ตรงกับสาขาในข้อมูลทะเบียนรถ',
  NO_HISTORY: 'ยังไม่มีประวัติให้เปรียบเทียบ',
  PROJECTION_MISMATCH: 'ไม่ตรงกับสาขาในข้อมูลทะเบียนรถ กรุณาแจ้งผู้ดูแลข้อมูล',
  UNDETERMINED: 'ตรวจสอบความตรงกันไม่ได้',
}

export const registrationConsistencyLabel: Record<string, string> = {
  CONSISTENT: 'ตรงกับทะเบียนในข้อมูลทะเบียนรถ',
  NO_HISTORY: 'ยังไม่มีประวัติให้เปรียบเทียบ',
  MISMATCH: 'ไม่ตรงกับทะเบียนในข้อมูลทะเบียนรถ กรุณาแจ้งผู้ดูแลข้อมูล',
  UNDETERMINED: 'ตรวจสอบความตรงกันไม่ได้ (แหล่งข้อมูลยังไม่มีช่องทะเบียน)',
}

export const branchEventNoteLabel: Record<string, string> = {
  RECORDED_SOURCE_DIFFERS: 'สาขาต้นทางที่บันทึกไว้ต่างจากที่คำนวณได้ตามลำดับปัจจุบัน',
  REDUNDANT: 'ย้ายไปสาขาเดิม',
  SAME_INSTANT: 'มีการย้ายอื่นที่มีผลเวลาเดียวกัน จึงเรียงลำดับไม่ได้',
  CANCELLED: 'ยกเลิกแล้ว',
}

export const branchRecordKindLabel: Record<string, string> = {
  ASSIGNMENT: 'บันทึกการย้าย',
  CORRECTION: 'แก้ไขการย้าย',
  CANCELLATION: 'ยกเลิกการย้าย',
  PROJECTION_RECONCILIATION: 'ปรับสาขาในข้อมูลทะเบียนรถ',
}

export const branchEntryOperationLabel: Record<string, string> = {
  TRANSFER: 'ย้ายสาขา',
  INSERTION: 'บันทึกการย้ายย้อนหลัง',
  CORRECTION: 'แก้ไข',
  CANCELLATION: 'ยกเลิก',
  PROJECTION_RECONCILIATION: 'ปรับข้อมูลทะเบียนรถ',
}

export const branchSourceLabel: Record<string, string> = {
  EVENT: 'จากการย้ายครั้งก่อน',
  BASELINE: 'จากสาขาเดิม',
  NONE: 'ไม่มี',
  IMPORTED_MASTER: 'จากข้อมูลทะเบียนรถที่นำเข้า',
}

export const registrationChangeKindLabel: Record<string, string> = {
  CHANGE: 'เปลี่ยนทะเบียน',
  RECONCILIATION_APPLY_RECORDED: 'ปรับข้อมูลทะเบียนรถตามประวัติ',
  RECONCILIATION_ACCEPT_MASTER: 'ยอมรับทะเบียนในข้อมูลทะเบียนรถ',
}

const bangkokDate = new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium', timeZone: 'Asia/Bangkok' })

/** A stored instant (UTC with offset) as Thai text in Asia/Bangkok: a date
 * only for DATE precision, otherwise date and time. Text that is not an
 * offset-bearing instant is returned unchanged. */
export function formatRegistryInstant(value: string | null, precision: string | null = 'DATETIME'): string {
  if (value === null) return '-'
  const instant = new Date(value)
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(value) || Number.isNaN(instant.getTime())) return value
  return precision === 'DATE' ? bangkokDate.format(instant) : bangkokDateTime.format(instant)
}

// ---------------------------------------------------------------------------
// R2 Batch R2-C2a — panel titles and labels (owner-approved Thai wording).
// ---------------------------------------------------------------------------

export const R2_PANEL_TITLES = {
  personnelLinks: 'ความเชื่อมโยงข้อมูลบุคลากร',
  departmentHistory: 'ประวัติการสังกัดแผนก',
  caretaker: 'ผู้ดูแลอุปกรณ์และประวัติ',
  responsibleDriver: 'ผู้รับผิดชอบรถประจำ',
  driverVehicles: 'รถที่รับผิดชอบประจำ',
} as const

/** R2f-f permanent responsibility is never evidence of actual driving. */
export const RESPONSIBLE_DRIVER_NOTE = 'ผู้รับผิดชอบรถประจำ ไม่ได้ยืนยันว่าเป็นผู้ขับรถจริงในแต่ละวัน'

export const linkResolutionLabel: Record<string, string> = {
  RESOLVED: 'เชื่อมโยงแล้ว',
  UNSET: 'ยังไม่ได้เชื่อมโยง',
  MISSING: 'ไม่พบข้อมูลปลายทางที่เชื่อมโยง',
  AMBIGUOUS: 'ข้อมูลซ้ำ ระบบไม่เลือกให้',
  SCOPE_UNPROVEN: 'ไม่อยู่ในขอบเขตข้อมูลปัจจุบัน',
}

export const linkEventKindLabel: Record<string, string> = {
  LINK: 'เชื่อมโยง',
  UNLINK: 'ยกเลิกการเชื่อมโยง',
  RELINK: 'เปลี่ยนการเชื่อมโยง',
  RECONCILIATION: 'ปรับข้อมูลให้ตรงกับประวัติ',
}

export const linkConsistencyLabel: Record<string, string> = {
  NO_HISTORY: 'ยังไม่มีประวัติ',
  CONSISTENT: 'ตรงกับประวัติ',
  MISMATCH: 'ไม่ตรงกับประวัติ',
}

/** The five effective-dated timeline operations (caretaker / permanent driver). */
export const timelineOperationLabel: Record<string, string> = {
  TRANSFER: 'เปลี่ยน/กำหนดใหม่',
  INSERTION: 'เพิ่มประวัติย้อนหลัง',
  END: 'สิ้นสุด',
  CORRECTION: 'แก้ไขรายการ',
  CANCELLATION: 'ยกเลิกรายการ',
}

export const timelineEntryLabel: Record<string, string> = {
  TRANSFER: 'กำหนด/เปลี่ยน',
  INSERTION: 'เพิ่มย้อนหลัง',
  END: 'สิ้นสุด',
}

export const timelineCurrentStatusLabel: Record<string, string> = {
  EVENT: 'มีผลอยู่',
  ENDED: 'สิ้นสุดแล้ว',
  NONE: 'ยังไม่มีข้อมูล',
  UNDETERMINED: 'ระบุไม่ได้ (มีรายการเวลาเดียวกัน)',
}

export const timelineStatusLabel: Record<string, string> = {
  VALID: 'ลำดับประวัติถูกต้อง',
  AMBIGUOUS_ORDER: 'ลำดับประวัติไม่ชัดเจน',
}

export const timelineNoteLabel: Record<string, string> = {
  SAME_INSTANT: 'เวลาเดียวกับรายการอื่น',
  CANCELLED: 'ยกเลิกแล้ว',
}

export const effectivePrecisionLabel: Record<string, string> = {
  DATE: 'ระดับวัน',
  DATETIME: 'ระดับวันและเวลา',
}

// ---------------------------------------------------------------------------
// R2 Batch R2-C2b — E2 operational driver assignment (owner-approved Thai wording).
// E2 is the ASSIGNED driver of a vehicle by day / shift: never the R2f-f permanent
// responsible driver, never the legacy Phase 6 assignment, never proof of driving.
// ---------------------------------------------------------------------------

export const E2_PANEL_TITLES = {
  vehicle: 'การมอบหมายผู้ขับรถตามวัน/กะ',
  driver: 'การมอบหมายขับรถตามวัน/กะ (ทุกคัน)',
} as const

/** Shown on both E2 panels (owner-approved wording). */
export const E2_NOTE =
  'เป็นข้อมูลการมอบหมาย ไม่ใช่การยืนยันว่าได้ขับรถจริง — ระบบ E2 แสดงผู้ขับที่ได้รับมอบหมายเท่านั้น ไม่มีข้อมูลยืนยันผู้ขับจริง'

/** REV5 A3.5 / B06: a viewed shift with no assignment (never filled from permanent responsibility). */
export const E2_UNASSIGNED_SHIFT = 'ยังไม่ได้ระบุผู้ได้รับมอบหมาย'

export const e2ModeLabel: Record<string, string> = {
  FULL_DAY: 'ทั้งวัน',
  DAY_SHIFT: 'กะกลางวัน',
  NIGHT_SHIFT: 'กะกลางคืน',
}

export const e2OperationLabel: Record<string, string> = {
  CREATE: 'มอบหมายใหม่',
  REVISE: 'แก้ไขการมอบหมาย',
  SUBSTITUTE: 'มอบหมายผู้ขับแทนรายวัน/รายกะ',
  CANCEL: 'ยกเลิกการมอบหมายก่อนเริ่ม',
  EARLY_END: 'สิ้นสุดการมอบหมายก่อนกำหนด',
}

/** The REVISE variants of the backend contract. */
export const e2ReviseVariantLabel: Record<string, string> = {
  STATE: 'แก้ไข/ขยายช่วงวันที่หรือผู้ขับ',
  SPLIT: 'เปลี่ยนเวลากะตั้งแต่วันที่กำหนด (แยกช่วง)',
  EXCLUDE: 'ตัดวัน/กะที่บันทึกผิดออก',
  VOID: 'ยกเลิกรายการที่บันทึกผิดทั้งรายการ (หลังเริ่มแล้ว)',
}

export const e2CurrentStatusLabel: Record<string, string> = {
  ASSIGNED: 'มีผู้ขับที่ได้รับมอบหมาย',
  UNKNOWN: 'สถานะการมอบหมายไม่แน่ชัด',
  NONE: 'ไม่มีการมอบหมายในขณะนี้',
  CONFLICTED: 'ข้อมูลการมอบหมายขัดแย้งกัน',
}

export const e2TimelineStatusLabel: Record<string, string> = {
  VALID: 'ข้อมูลการมอบหมายถูกต้อง',
  CONFLICTED: 'ข้อมูลการมอบหมายขัดแย้งกัน',
}

export const e2LifecycleLabel: Record<string, string> = {
  ACTIVE: 'มีผล',
  CANCELLED: 'ยกเลิกแล้ว',
  VOIDED: 'ยกเลิกเพราะบันทึกผิด',
  IN_FORCE: 'มีผล',
}

export const e2RecordKindLabel: Record<string, string> = {
  ASSIGNMENT: 'บันทึกการมอบหมาย',
  REVISION: 'ฉบับแก้ไข',
  HANDOVER: 'การส่งต่อ',
  CANCELLATION: 'การยกเลิก',
}

export const e2RelationLabel: Record<string, string> = {
  SPLIT: 'แยกช่วงจาก',
  SUBSTITUTION: 'ผู้ขับแทนของ',
}

export const e2HandoverKindLabel: Record<string, string> = {
  H2: 'H2 — ทั้งวันวันสุดท้าย → กะกลางคืนที่เริ่มวันเดียวกัน',
  E2_H3: 'H3 — กะกลางคืนข้ามคืน → ทั้งวันของวันถัดไป',
}

export const e2WarningLabel: Record<string, string> = {
  NO_PERMANENT_RESPONSIBLE_DRIVER:
    'ยังไม่ได้กำหนดผู้รับผิดชอบประจำรถ — รถคันนี้ยังไม่มีผู้รับผิดชอบรถประจำ (แจ้งเตือนเท่านั้น ไม่ห้ามบันทึก)',
  PERMANENT_RESPONSIBILITY_UNDETERMINED: 'ระบุผู้รับผิดชอบรถประจำไม่ได้ (แจ้งเตือนเท่านั้น)',
  ADJACENT_ASSIGNMENT_REST_WARNING:
    'ผู้ขับมีการมอบหมายต่อเนื่องติดกัน ควรพิจารณาการพักและความพร้อม (การบันทึกไม่ใช่การรับรองความปลอดภัย)',
  DRIVER_NOT_ACTIVE: 'ผู้ขับของการมอบหมายนี้ไม่อยู่ในสถานะใช้งาน (ACTIVE) แล้ว',
  FUTURE_ASSIGNMENT_DRIVER_NOT_ACTIVE_PENDING_REVIEW: 'การมอบหมายล่วงหน้านี้มีผู้ขับที่ไม่อยู่ในสถานะใช้งาน ต้องตรวจสอบ',
}

/** E2 messages; codes shared with other features get an E2-specific wording
 * here, so the existing (R2f-f / Phase 6) messages are left unchanged. */
const e2ErrorMessages: Record<string, string> = {
  E2_REAL_WRITES_NOT_ENABLED: 'ยังไม่เปิดให้บันทึกการมอบหมายตามวัน/กะกับข้อมูลจริง (REAL) จนกว่าจะผ่านขั้น R11 ไม่มีการบันทึกใด ๆ',
  FEATURE_NOT_AVAILABLE_IN_REPOSITORY_MODE:
    'การมอบหมายผู้ขับตามวัน/กะใช้ได้เฉพาะข้อมูลทดสอบ (Mock/TEST) จนกว่าจะผ่านขั้น R11 จึงยังไม่พร้อมใช้งานในโหมดข้อมูลนี้',
  E2_VEHICLE_CONFLICT: 'ช่วงเวลานี้ทับกับการมอบหมายอื่นของรถคันนี้ ไม่มีการบันทึก',
  E2_DRIVER_CONFLICT: 'ช่วงเวลานี้ทับกับการมอบหมายอื่นของผู้ขับคนนี้ ไม่มีการบันทึก',
  E2_ASSIGNMENT_STALE: 'การมอบหมายเปลี่ยนไปหลังจากที่โหลดข้อมูล กรุณาโหลดข้อมูลล่าสุดแล้วลองใหม่',
  E2_CONCURRENT_CHANGE: 'มีการบันทึกการมอบหมายอื่นก่อนหน้านี้ ไม่มีการบันทึกคำขอนี้ กรุณาโหลดข้อมูลล่าสุดแล้วลองใหม่',
  E2_ASSIGNMENT_NOT_FOUND: 'ไม่พบการมอบหมายนี้ของรถคันนี้',
  E2_ASSIGNMENT_CANCELLED: 'การมอบหมายนี้ถูกยกเลิกแล้ว',
  E2_ASSIGNMENT_VOIDED: 'การมอบหมายนี้ถูกยกเลิกเพราะบันทึกผิดแล้ว',
  E2_ASSIGNMENT_ALREADY_STARTED: 'การมอบหมายนี้เริ่มแล้ว ยกเลิกก่อนเริ่มไม่ได้ ให้ใช้ "สิ้นสุดก่อนกำหนด" หรือ "แก้ไขการมอบหมาย"',
  E2_ASSIGNMENT_NOT_STARTED: 'การมอบหมายนี้ยังไม่เริ่ม ให้ใช้ "ยกเลิกการมอบหมายก่อนเริ่ม"',
  E2_ASSIGNMENT_ALREADY_ENDED: 'การมอบหมายนี้สิ้นสุดแล้ว',
  E2_HANDOVER_NOT_PERMITTED: 'การส่งต่อนี้ไม่เป็นไปตามเงื่อนไข H2/H3 ไม่มีการบันทึก',
  E2_HANDOVER_INVALIDATED: 'การเปลี่ยนแปลงนี้ทำให้การส่งต่อที่มีผลแล้วไม่ถูกต้อง ให้ยกเลิกรายการที่ผิดแล้วบันทึกใหม่',
  E2_SUBSTITUTION_UNIT_INVALID: 'มอบหมายผู้ขับแทนได้เฉพาะทั้งวันหรือทั้งกะของการมอบหมายนี้เท่านั้น',
  E2_SUBSTITUTION_DRIVER_UNCHANGED: 'ผู้ขับแทนต้องเป็นคนละคนกับผู้ขับเดิม',
  E2_TIMELINE_CONFLICTED: 'ข้อมูลการมอบหมายของรถคันนี้ขัดแย้งกันอยู่ ต้องแก้ไขรายการที่ขัดแย้งก่อน',
  E2_DATE_INVALID: 'วันที่ไม่ถูกต้องหรือไม่อยู่ในช่วงการมอบหมาย',
  E2_TIME_INVALID: 'เวลากะต้องอยู่ในรูปแบบ HH:MM (00:00-23:59)',
  E2_RANGE_INVALID: 'วันที่สิ้นสุดต้องไม่อยู่ก่อนวันที่เริ่มต้น',
  E2_RANGE_TOO_LONG: 'การมอบหมายครอบคลุมได้ไม่เกิน 366 วัน และเริ่มล่วงหน้าได้ไม่เกิน 366 วัน',
  E2_SHIFT_REQUIRED: 'กะกลางวัน/กะกลางคืนต้องระบุเวลาเริ่มและเวลาสิ้นสุดของกะ',
  E2_SHIFT_NOT_ALLOWED: 'การมอบหมายทั้งวันต้องไม่ระบุเวลากะ',
  E2_SHIFT_DURATION_INVALID: 'กะต้องยาวมากกว่า 0 และไม่เกิน 24 ชั่วโมง (เวลาเท่ากันต้องเลือกสิ้นสุดวันถัดไป)',
  E2_MODE_INVALID: 'รูปแบบการมอบหมายไม่ถูกต้อง',
  E2_SPLIT_INVALID: 'แยกช่วงเวลากะไม่ได้ตามเงื่อนไข (เฉพาะกะที่ยังไม่สิ้นสุด และวันที่ต้องอยู่หลังวันแรกของการมอบหมาย)',
  E2_EARLY_END_INVALID: 'วันที่สิ้นสุดต้องเป็นวันนี้หรือหลังจากนี้ อยู่ในช่วงการมอบหมาย และก่อนวันสุดท้าย',
  E2_OPERATION_INVALID: 'ประเภทการดำเนินการไม่ถูกต้อง',
  E2_HISTORY_WRITE_FAILED: 'บันทึกประวัติการมอบหมายไม่สำเร็จหรือไม่ทราบผล',
  E2_HISTORY_READ_FAILED: 'อ่านประวัติการมอบหมายไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  E2_HISTORY_SCHEMA_INVALID: 'ประวัติการมอบหมายยังไม่พร้อมใช้งานในระบบ',
  E2_HISTORY_DATA_INVALID: 'ประวัติการมอบหมายไม่ถูกต้อง กรุณาแจ้งผู้ดูแลข้อมูล',
  DRIVER_NOT_FOUND: 'ไม่พบผู้ขับรหัสนี้ในขอบเขตข้อมูลปัจจุบัน',
  DRIVER_NOT_ACTIVE: 'ผู้ขับรหัสนี้ไม่อยู่ในสถานะใช้งาน (ACTIVE) จึงมอบหมายสำหรับช่วงปัจจุบันหรืออนาคตไม่ได้',
  DRIVER_SCOPE_UNPROVEN: 'ผู้ขับรหัสนี้ไม่อยู่ในขอบเขตข้อมูลปัจจุบัน (TEST/REAL)',
  DRIVER_ID_AMBIGUOUS: 'มีผู้ขับที่ใช้รหัสนี้มากกว่าหนึ่งรายการ ระบบไม่เลือกให้',
  DRIVER_PERSONNEL_AMBIGUOUS: 'ผู้ขับนี้เชื่อมโยงกับบุคลากรมากกว่าหนึ่งราย ระบบไม่บันทึก',
  PERSONNEL_NOT_ACTIVE: 'บุคลากรที่เชื่อมโยงกับผู้ขับนี้ไม่อยู่ในสถานะใช้งาน',
  DRIVER_MASTER_READ_FAILED: 'อ่านข้อมูลผู้ขับไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  VEHICLE_SCOPE_UNPROVEN: 'รถคันนี้ไม่อยู่ในขอบเขตข้อมูลปัจจุบัน (TEST/REAL) จึงไม่แสดงการมอบหมายตามวัน/กะ',
}

/** The E2 wording of a code, falling back to the shared messages. */
export function describeE2ErrorCode(code: string | undefined): string {
  if (code && e2ErrorMessages[code]) return e2ErrorMessages[code]
  return describeErrorCode(code)
}
