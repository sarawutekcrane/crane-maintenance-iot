/**
 * R6 FINAL §9 — pure helpers for the part lifecycle screens. Every value is
 * taken from the API: no counter or due arithmetic happens in the browser.
 * UNKNOWN / PARTIAL quantities are never rendered as a number (never 0), and
 * a tracked figure is never shown in a verified row.
 */
import { counterBasisLabel, policyStateLabel, usageReasonLabel } from './labels'
import type { PartInstanceStatus, UsageCounters, UsageQuantity } from './types'

export const UNKNOWN_TEXT = 'ไม่ทราบ'
export const PARTIAL_TEXT = 'บันทึกไว้บางส่วน'

/** A fresh client intent id; reuse the SAME id when retrying an uncertain outcome. */
export function newRequestId(): string {
  return globalThis.crypto.randomUUID()
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('th-TH', { maximumFractionDigits: 2 }).format(value)
}

/** The display text of one quantity: a number only when KNOWN. */
export function quantityText(q: UsageQuantity | null | undefined): string {
  if (!q) return UNKNOWN_TEXT
  if (q.quality === 'KNOWN' && q.value !== null && q.value !== undefined) return formatNumber(q.value)
  if (q.quality === 'PARTIAL_RECORDED') return PARTIAL_TEXT
  return UNKNOWN_TEXT
}

export function reasonText(reasons: readonly string[]): string {
  return reasons.map((r) => usageReasonLabel[r] ?? r).join(' · ')
}

export function policyText(state: string | null | undefined): string | null {
  if (!state || state === 'APPROVED') return null
  return policyStateLabel[state] ?? state
}

export function basisText(counters: UsageCounters): string {
  const key = `${counters.basis.counter_type}:${counters.basis.component_role ?? ''}`
  return counterBasisLabel[key] ?? key
}

/** The four rows of one basis, in the fixed FINAL §9 order. */
export const COUNTER_ROWS: { key: keyof Omit<UsageCounters, 'basis'>; label: string }[] = [
  { key: 'verified_lifetime_total', label: 'รวมตลอดอายุ (ยืนยันแล้ว)' },
  { key: 'verified_current_cycle', label: 'รอบปัจจุบัน (ยืนยันแล้ว)' },
  { key: 'tracked_since_enrollment', label: 'ใช้งานที่ติดตามได้ตั้งแต่ลงทะเบียน' },
  { key: 'tracked_in_current_cycle', label: 'ใช้งานที่ติดตามได้ในรอบนี้' },
]

/** A-1 transition matrix (display only; the backend re-checks every move). */
const STATUS_MOVES: Record<PartInstanceStatus, PartInstanceStatus[]> = {
  REMOVED: ['IN_REPAIR', 'READY_FOR_INSTALL', 'STOCK', 'SCRAPPED'],
  READY_FOR_INSTALL: ['IN_REPAIR', 'STOCK', 'SCRAPPED'],
  STOCK: ['IN_REPAIR', 'READY_FOR_INSTALL', 'SCRAPPED'],
  IN_REPAIR: ['SCRAPPED'],
  INSTALLED: [],
  SCRAPPED: [],
}

export interface AllowedActions {
  install: boolean
  remove: boolean
  transfer: boolean
  returnFromRepair: boolean
  statusMoves: PartInstanceStatus[]
}

export function allowedActions(status: PartInstanceStatus): AllowedActions {
  return {
    install: status === 'READY_FOR_INSTALL' || status === 'STOCK',
    remove: status === 'INSTALLED',
    transfer: status === 'INSTALLED',
    returnFromRepair: status === 'IN_REPAIR',
    statusMoves: STATUS_MOVES[status] ?? [],
  }
}

/** Outcome classification for a write: a definitive refusal ends the intent;
 * an uncertain outcome (network / 5xx) keeps the same request id for a retry. */
export function isUncertain(status: number | undefined): boolean {
  return status === undefined || status === 0 || status >= 500
}
