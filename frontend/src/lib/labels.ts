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

const knownErrorMessages: Record<string, string> = {
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
  VEHICLE_DRIVER_ASSIGNMENT_NOT_FOUND: 'ไม่พบข้อมูลการมอบหมายคนขับ/ผู้ควบคุมนี้',
  // VEHICLE_DRIVER_ASSIGNMENT_ALREADY_ENDED intentionally removed: ending
  // an already-ended assignment is now an idempotent no-op (project
  // decision, targeted correction) — the backend never returns this code.
  // Web/API Phase 6 Batch 2A — Vehicle Certificate.
  VEHICLE_CERTIFICATE_NOT_FOUND: 'ไม่พบข้อมูลเอกสาร/ใบรับรองนี้',
  // Web/API Phase 6 Batch 3A — Model Document.
  MODEL_DOCUMENT_NOT_FOUND: 'ไม่พบข้อมูลเอกสารประจำรุ่นเครื่องจักรนี้',
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
