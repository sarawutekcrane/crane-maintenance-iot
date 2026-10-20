import { assignmentModelOf, type WorkKind } from '../lib/technicianV2'
import { Card } from './Card'
import { ErrorState } from './ErrorState'
import { TechnicianAssignmentV2Panel } from './TechnicianAssignmentV2Panel'
import { V2ContextBanner } from './V2ContextBanner'

interface JobAssignmentSectionProps {
  kind: WorkKind
  jobId: string
  jobStatus: string
  /** The job's persisted `assignment_model` read signal (B1), raw. */
  assignmentModel: unknown
  /** The legacy header mirror, raw — shown read-only for a LEGACY job only. */
  legacyPrimary: unknown
  legacyCollaborators: unknown
  onChanged?: () => void
  /** R3 L8 / L9: the job is an R3 Finding round (server-stored `finding_id`). */
  r3FindingRound?: boolean
}

function rawText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '(ว่าง)'
  return typeof value === 'string' ? value : JSON.stringify(value)
}

/**
 * R2 Batch R2f-h4 B5 (A1-§25) — the assignment area of the Repair / PM job
 * detail pages after the navigation cutover. It branches strictly on the job's
 * persisted `assignment_model`:
 * - TECHNICIAN_V2 → the V2 assignment panel (B4);
 * - LEGACY → a read-only display of the stored legacy user ids (never
 *   converted to V2, never editable: the legacy free-text assignment is removed);
 * - anything else → an explicit error with no control (fail closed).
 */
export function JobAssignmentSection({
  kind,
  jobId,
  jobStatus,
  assignmentModel,
  legacyPrimary,
  legacyCollaborators,
  onChanged,
  r3FindingRound = false,
}: JobAssignmentSectionProps) {
  const model = assignmentModelOf(assignmentModel)
  if (model === 'TECHNICIAN_V2') {
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
  if (model === 'LEGACY') {
    const collaborators = Array.isArray(legacyCollaborators) ? legacyCollaborators : []
    return (
      <Card>
        <h2>ผู้รับผิดชอบ (รูปแบบเดิม — อ่านอย่างเดียว)</h2>
        <p className="form-field__hint" data-testid="legacy-assignment-readonly">
          งานนี้สร้างด้วยรูปแบบการมอบหมายเดิม (LEGACY) ค่าด้านล่างเป็นรหัสผู้ใช้เดิม (LEGACY_USER_ID) ตามที่บันทึกไว้
          ไม่ใช่รหัสช่าง และไม่สามารถแก้ไขหรือมอบหมายช่าง V2 กับงานนี้ได้
        </p>
        <div className="status-card__row">
          <span>LEGACY_USER_ID (หลัก)</span>
          <code>{rawText(legacyPrimary)}</code>
        </div>
        <div className="status-card__row">
          <span>LEGACY_USER_ID (ร่วม)</span>
          <code>{collaborators.length ? collaborators.map(rawText).join(', ') : '(ว่าง)'}</code>
        </div>
      </Card>
    )
  }
  return (
    <ErrorState
      title="รูปแบบการมอบหมายของงานนี้ไม่ถูกต้อง"
      message="ข้อมูลรูปแบบการมอบหมายที่บันทึกไว้ไม่ใช่ค่าที่ระบบรู้จัก ระบบจึงไม่แสดงและไม่อนุญาตการมอบหมายช่าง กรุณาแจ้งผู้ดูแลข้อมูล"
      code="ASSIGNMENT_MODEL_INVALID"
    />
  )
}
