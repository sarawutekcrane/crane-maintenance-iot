import { assignmentModelOf, type WorkKind } from '../lib/technicianV2'
import { ErrorState } from './ErrorState'
import { TechnicianAssignmentV2Panel } from './TechnicianAssignmentV2Panel'
import { V2ContextBanner } from './V2ContextBanner'

interface JobAssignmentSectionProps {
  kind: WorkKind
  jobId: string
  jobStatus: string
  /** The job's persisted `assignment_model` read signal (B1), raw. */
  assignmentModel: unknown
  onChanged?: () => void
  /** R3 L8 / L9: the job is an R3 Finding round (server-stored `finding_id`). */
  r3FindingRound?: boolean
}

/**
 * R2 Batch R2f-h4 B5 (A1-§25) — the assignment area of the Repair / PM job
 * detail pages after the navigation cutover. It branches strictly on the job's
 * persisted `assignment_model`:
 * - TECHNICIAN_V2 → the V2 assignment panel (B4);
 * - anything else, LEGACY included → an explicit error with no control and no
 *   stored assignee shown (fail closed). DEC-ARCH-LEGACY-RUNTIME-CANCEL-CLEANUP-20261107:
 *   the Legacy runtime is cancelled; the old read-only Legacy user-id display is removed.
 */
export function JobAssignmentSection({
  kind,
  jobId,
  jobStatus,
  assignmentModel,
  onChanged,
  r3FindingRound = false,
}: JobAssignmentSectionProps) {
  if (assignmentModelOf(assignmentModel) === 'TECHNICIAN_V2') {
    return (
      <>
        <V2ContextBanner />
        <TechnicianAssignmentV2Panel
          kind={kind}
          jobId={jobId}
          jobStatus={jobStatus}
          onChanged={onChanged}
          r3FindingRound={r3FindingRound}
        />
      </>
    )
  }
  return (
    <ErrorState
      title="รูปแบบการมอบหมายของงานนี้ไม่ถูกต้อง"
      message="ระบบรองรับเฉพาะงานที่ใช้การมอบหมายช่าง V2 รูปแบบการมอบหมายที่บันทึกไว้ของงานนี้ไม่รองรับหรือไม่ถูกต้อง ระบบจึงไม่แสดงและไม่อนุญาตการมอบหมายช่าง กรุณาแจ้งผู้ดูแลข้อมูล"
      code="ASSIGNMENT_MODEL_INVALID"
    />
  )
}
