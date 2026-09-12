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
  ENGINE_MAIN: 'เครื่องยนต์หลัก',
  ENGINE_SECONDARY: 'เครื่องยนต์สำรอง',
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

const knownErrorMessages: Record<string, string> = {
  VEHICLE_NOT_FOUND: 'ไม่พบข้อมูลยานพาหนะนี้',
  MODEL_NOT_FOUND: 'ไม่พบข้อมูลรุ่นเครื่องจักรนี้',
  EQUIPMENT_NOT_FOUND: 'ไม่พบข้อมูลเครื่องมือ/อุปกรณ์นี้',
  VALIDATION_ERROR: 'ข้อมูลที่ส่งไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง',
  NOT_FOUND: 'ไม่พบข้อมูลที่ต้องการ',
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
