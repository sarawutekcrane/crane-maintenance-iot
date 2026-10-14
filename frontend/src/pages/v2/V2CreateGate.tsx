import type { ReactNode } from 'react'
import { LoadingState } from '../../components/LoadingState'
import { PermissionDeniedState } from '../../components/PermissionDeniedState'
import { V2CreationDisabled } from '../../components/V2ContextBanner'
import { useCapabilities } from '../../lib/capabilities'

/**
 * R2 Batch R2f-h4 B4 (A1-§25) — the creation gate of every V2 create page. The
 * form (and so any create request) exists only when GET /me succeeded and
 * reported `technician_assignment_v2_enabled` exactly true; otherwise the page
 * shows "การมอบหมายช่างยังไม่เปิดใช้งาน" and never falls back to the legacy
 * create flow. The capability check is usability only; the backend decides.
 */
export function V2CreateGate({ capability, children }: { capability: string; children: ReactNode }) {
  const { loading, signals, hasCapability } = useCapabilities()
  if (loading) return <LoadingState message="กำลังตรวจสอบสถานะของระบบ..." />
  if (!signals.v2Enabled) return <V2CreationDisabled />
  if (!hasCapability(capability)) return <PermissionDeniedState />
  return <>{children}</>
}
