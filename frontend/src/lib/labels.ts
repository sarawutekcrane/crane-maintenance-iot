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
 * Vehicle's `operationalStatusLabel` (decision C02). */
export const equipmentStatusLabel: Record<string, string> = {
  READY: 'พร้อมใช้งาน',
  IN_USE: 'กำลังใช้งาน',
  MAINTENANCE: 'ซ่อมบำรุง',
  OUT_OF_SERVICE: 'หยุดใช้งาน',
}

export const equipmentStatusTone: Record<string, StatusTone> = {
  READY: 'info',
  IN_USE: 'success',
  MAINTENANCE: 'warning',
  OUT_OF_SERVICE: 'danger',
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
