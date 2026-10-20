import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { PermissionDeniedState } from '../components/PermissionDeniedState'
import {
  ALL_EMPLOYEES,
  AUDIT_KIND_LABELS,
  ROOT_MODE_LABELS,
  accessApi,
  EXCLUSION_LABELS,
  bulkEligible,
  bulkExcluded,
  employeesForPosition,
  holderCount,
  switchView,
  toggleDraft,
  type AccessAuditEntry,
  type AccessDelegation,
  type AccessDepartment,
  type AccessEmployees,
  type AccessMe,
  type AccessTarget,
  type CatalogCategory,
  type GrantPlan,
  type RootView,
} from '../lib/accessManagement'
import { ApiError } from '../lib/apiClient'
import { useCapabilities } from '../lib/capabilities'
import { CAN_VIEW_ACCESS_AUDIT } from '../lib/capabilityNames'
import { describeErrorCode, formatThaiDateTime } from '../lib/labels'
import { newRequestId } from '../lib/registryPending'

interface Failure {
  message: string
  code?: string
  requestId?: string | null
}

function failureOf(error: Error): Failure {
  return error instanceof ApiError
    ? { message: describeErrorCode(error.code), code: error.code, requestId: error.requestId }
    : { message: 'เชื่อมต่อระบบไม่สำเร็จ กรุณาลองใหม่อีกครั้ง' }
}

type Boot =
  | { kind: 'loading' }
  | { kind: 'disabled' }
  | { kind: 'error'; failure: Failure }
  | { kind: 'ready'; me: AccessMe }

function bootOf(result: Awaited<ReturnType<typeof accessApi.me>>): Boot {
  if (result.ok) return { kind: 'ready', me: result.data }
  if (result.error instanceof ApiError && result.error.code === 'ACCESS_MANAGEMENT_NOT_ENABLED') return { kind: 'disabled' }
  return { kind: 'error', failure: failureOf(result.error) }
}

/**
 * Access Management (Owner-approved Mock implementation) — ONE screen:
 * department → position filter → employee ("ทุกคนในแผนก" or one person), the
 * A–J permission switches, a preview with counts and a confirmation before any
 * save. Every permission is stored per employee: a department change is a bulk
 * operation over the employees eligible now, never a baseline. The backend
 * derives the actor, re-checks the scope and recounts on every save.
 */
export function AccessManagementPage() {
  const [boot, setBoot] = useState<Boot>({ kind: 'loading' })

  const loadMe = useCallback(async () => {
    setBoot(bootOf(await accessApi.me()))
  }, [])

  useEffect(() => {
    let cancelled = false
    void accessApi.me().then((result) => {
      if (!cancelled) setBoot(bootOf(result))
    })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="page access-page">
      <h1>จัดการสิทธิ์ผู้ใช้งาน</h1>
      <p className="form-field__hint">
        สิทธิ์ทุกข้อเก็บเป็นรายบุคคล — แผนกและตำแหน่งใช้สำหรับเลือกพนักงานเท่านั้น ไม่มีสิทธิ์ตั้งต้นตามแผนกหรือตำแหน่ง
        พนักงานใหม่เริ่มต้นโดยไม่มีสิทธิ์ใด ๆ (ข้อมูลทดสอบ Mock — ไม่ใช่ระบบจริง)
      </p>
      {boot.kind === 'loading' && <LoadingState />}
      {boot.kind === 'disabled' && (
        <Card className="state-panel">
          <p className="state-panel__title">ยังไม่เปิดใช้การจัดการสิทธิ์</p>
          <p>{describeErrorCode('ACCESS_MANAGEMENT_NOT_ENABLED')}</p>
        </Card>
      )}
      {boot.kind === 'error' && (
        <ErrorState message={boot.failure.message} code={boot.failure.code} requestId={boot.failure.requestId} onRetry={() => void loadMe()} />
      )}
      {boot.kind === 'ready' && <AccessWorkspace me={boot.me} reloadMe={loadMe} />}
    </section>
  )
}

function AccessWorkspace({ me, reloadMe }: { me: AccessMe; reloadMe: () => Promise<void> }) {
  const administers = me.is_root || me.delegations.length > 0
  const auditViewer = me.capabilities.includes(CAN_VIEW_ACCESS_AUDIT)

  return (
    <>
      <AuthorityBanner me={me} />
      {!administers && !auditViewer && !me.recovery && (
        <PermissionDeniedState message="คุณไม่ได้ดำรงตำแหน่งผู้จัดการแผนกซ่อมบำรุงและไม่ได้รับมอบอำนาจจัดการสิทธิ์" />
      )}
      {administers && <GrantEditor me={me} reloadMe={reloadMe} />}
      {(me.is_root || me.recovery) && <RootPositionSection me={me} reloadMe={reloadMe} />}
      {(me.is_root || auditViewer) && <DelegationList me={me} reloadMe={reloadMe} />}
      {(administers || auditViewer) && <AuditSection me={me} />}
    </>
  )
}

function AuthorityBanner({ me }: { me: AccessMe }) {
  return (
    <Card>
      <p data-testid="access-actor">
        ผู้ใช้งาน: <strong>{me.name || 'ไม่พบข้อมูลพนักงานที่เชื่อมกับบัญชีนี้'}</strong>
        {me.personnel_id && <span> ({me.personnel_id})</span>}
      </p>
      {me.is_root && <p data-testid="access-authority">อำนาจ: ผู้จัดการแผนกซ่อมบำรุง (ผู้ดำรงตำแหน่งปัจจุบัน)</p>}
      {!me.is_root && me.delegations.length > 0 && (
        <div data-testid="access-authority">
          <p>อำนาจ: ได้รับมอบอำนาจจัดการสิทธิ์ (ห้ามมอบต่อ และแก้ไขสิทธิ์ของตนเองไม่ได้)</p>
          <ul>
            {me.delegations.map((d) => (
              <li key={d.delegation_id}>
                แผนก {d.department_name_th || d.department_id}: {d.capabilities.length} สิทธิ์
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Grants: selection → switches → preview → confirm
// ---------------------------------------------------------------------------

function GrantEditor({ me, reloadMe }: { me: AccessMe; reloadMe: () => Promise<void> }) {
  const { refresh } = useCapabilities()
  const [catalog, setCatalog] = useState<CatalogCategory[] | null>(null)
  const [departments, setDepartments] = useState<AccessDepartment[] | null>(null)
  const [loadFailure, setLoadFailure] = useState<Failure | null>(null)
  const [departmentId, setDepartmentId] = useState('')
  const [positionKey, setPositionKey] = useState('')
  const [selection, setSelection] = useState('')
  const [roster, setRoster] = useState<AccessEmployees | null>(null)
  const [draft, setDraft] = useState<Record<string, boolean>>({})
  const [plan, setPlan] = useState<GrantPlan | null>(null)
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actionFailure, setActionFailure] = useState<Failure | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const intent = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void Promise.all([accessApi.catalog(), accessApi.departments()]).then(([c, d]) => {
      if (cancelled) return
      if (!c.ok) return setLoadFailure(failureOf(c.error))
      if (!d.ok) return setLoadFailure(failureOf(d.error))
      setCatalog(c.data.categories)
      setDepartments(d.data)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const loadRoster = useCallback(async (dept: string) => {
    if (!dept) return setRoster(null)
    const result = await accessApi.employees(dept)
    if (result.ok) setRoster(result.data)
    else setLoadFailure(failureOf(result.error))
  }, [])

  const resetChange = () => {
    setDraft({})
    setPlan(null)
    setReason('')
    setActionFailure(null)
    intent.current = null
  }

  const chooseDepartment = (dept: string) => {
    setDepartmentId(dept)
    setPositionKey('')
    setSelection('')
    setSaved(null)
    resetChange()
    setRoster(null)
    void loadRoster(dept)
  }

  const employees = roster?.employees ?? []
  const listed = employeesForPosition(employees, positionKey)
  const eligible = bulkEligible(employees)
  const excludedNow = bulkExcluded(employees)
  const employee = selection && selection !== ALL_EMPLOYEES ? employees.find((e) => e.personnel_id === selection) ?? null : null
  const grantable = new Set(roster?.grantable ?? [])
  // Server-derived (D1–D3): inactive, a delegate's own record, or the root holder for a delegate.
  const locked = employee?.exclusion ?? null
  const selfLocked = locked === 'SELF_NOT_EDITABLE'
  const target: AccessTarget | null =
    selection === ALL_EMPLOYEES && departmentId
      ? { kind: 'DEPARTMENT', department_id: departmentId }
      : employee
        ? { kind: 'EMPLOYEE', personnel_id: employee.personnel_id }
        : null
  const editable = target !== null && locked === null
  const changeCount = Object.keys(draft).length

  const preview = async () => {
    if (!target || !roster || changeCount === 0) return
    setBusy(true)
    setActionFailure(null)
    const result = await accessApi.preview(target, draft, roster.revision)
    setBusy(false)
    if (result.ok) setPlan(result.data)
    else setActionFailure(failureOf(result.error))
  }

  const apply = async () => {
    setConfirming(false)
    if (!target || !plan) return
    if (!reason.trim()) return setActionFailure({ message: describeErrorCode('ACCESS_REASON_REQUIRED') })
    setBusy(true)
    setActionFailure(null)
    intent.current ??= newRequestId()
    const result = await accessApi.apply(target, draft, reason.trim(), plan.revision, intent.current)
    setBusy(false)
    if (result.ok) {
      const changed = result.data.per_capability.reduce((sum, c) => sum + c.changed, 0)
      setSaved(`บันทึกแล้ว: เปลี่ยนสิทธิ์ ${changed} รายการ กับพนักงาน ${result.data.target_count} คน`)
      resetChange()
      await loadRoster(departmentId)
      await reloadMe()
      refresh()
      return
    }
    const failure = failureOf(result.error)
    setActionFailure(failure)
    if (failure.code === 'ACCESS_STALE_REVISION') {
      // Nothing was written: reload the counts and ask for a fresh preview.
      setPlan(null)
      intent.current = null
      await loadRoster(departmentId)
    } else if (result.error instanceof ApiError) {
      intent.current = null
    }
  }

  if (loadFailure) return <ErrorState message={loadFailure.message} code={loadFailure.code} requestId={loadFailure.requestId} />
  if (!catalog || !departments) return <LoadingState />

  const labelOf = (code: string) =>
    catalog.flatMap((c) => c.capabilities).find((c) => c.code === code)?.label_th ?? code

  return (
    <Card className="access-editor">
      <h2>กำหนดสิทธิ์</h2>
      <div className="form-grid form-grid--two-column">
        <div className="form-field">
          <label htmlFor="access-department">1. แผนก</label>
          <select id="access-department" value={departmentId} onChange={(e) => chooseDepartment(e.target.value)}>
            <option value="">— เลือกแผนก —</option>
            {departments.map((d) => (
              <option key={d.department_id} value={d.department_id}>
                {d.department_name_th || d.department_id} ({d.employee_count} คน){d.is_active ? '' : ' — ปิดใช้งาน'}
              </option>
            ))}
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="access-position">2. ตำแหน่ง (ตัวกรองรายชื่อ)</label>
          <select
            id="access-position"
            value={positionKey}
            disabled={!roster}
            onChange={(e) => {
              setPositionKey(e.target.value)
              if (selection !== ALL_EMPLOYEES) {
                setSelection('')
                resetChange()
              }
            }}
          >
            <option value="">ทุกตำแหน่ง</option>
            {roster?.positions.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="access-employee">3. พนักงาน</label>
          <select
            id="access-employee"
            value={selection}
            disabled={!roster}
            onChange={(e) => {
              setSelection(e.target.value)
              setSaved(null)
              resetChange()
            }}
          >
            <option value="">— เลือกพนักงาน —</option>
            <option value={ALL_EMPLOYEES}>ทุกคนในแผนก ({employees.length} คน)</option>
            {listed.map((e) => (
              <option key={e.personnel_id} value={e.personnel_id}>
                {e.name} — {e.position || 'ไม่ระบุตำแหน่ง'}
                {e.active ? '' : ' (ไม่อยู่ในสถานะใช้งาน)'}
                {e.is_self ? ' (ตัวคุณเอง)' : ''}
                {e.is_root ? ' (ผู้จัดการแผนกซ่อมบำรุง)' : ''}
              </option>
            ))}
          </select>
          {selection === ALL_EMPLOYEES && (
            <div className="form-field__hint" data-testid="access-bulk-note">
              <p>
                "ทุกคนในแผนก" คือพนักงานทุกคนของแผนกในขณะนี้ {employees.length} คน (ไม่ขึ้นกับตัวกรองตำแหน่ง):
                เปลี่ยนสิทธิ์ได้ {eligible.length} คน — พนักงานที่เข้ามาภายหลังจะไม่ได้รับสิทธิ์นี้อัตโนมัติ
                และสวิตช์ที่ไม่ได้แตะจะไม่เปลี่ยนแปลงสิทธิ์ใด ๆ
              </p>
              {excludedNow.length > 0 && (
                <ul data-testid="access-bulk-excluded">
                  {excludedNow.map((e) => (
                    <li key={e.personnel_id}>
                      ไม่รวม {e.name}: {EXCLUSION_LABELS[e.exclusion ?? ''] ?? e.exclusion}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

      {saved && (
        <p className="status-badge status-badge--success" role="status" data-testid="access-saved">
          {saved}
        </p>
      )}
      {employee && !employee.active && (
        <p className="form-field__error">{describeErrorCode('ACCESS_EMPLOYEE_INACTIVE')}</p>
      )}
      {selfLocked && <p className="form-field__error" data-testid="access-self-locked">ไม่สามารถแก้ไขสิทธิ์ของตนเองได้</p>}
      {locked === 'ROOT_PROTECTED' && (
        <p className="form-field__error" data-testid="access-root-locked">{EXCLUSION_LABELS.ROOT_PROTECTED}</p>
      )}
      {employee?.is_self && me.is_root && (
        <p className="form-field__hint">คุณกำลังแก้ไขสิทธิ์ของตนเองในฐานะผู้จัดการแผนกซ่อมบำรุง (ระบบบันทึกประวัติไว้)</p>
      )}

      {target && roster && (
        <div className="access-categories">
          {catalog.map((category) => (
            <fieldset key={category.code} className="access-category" data-testid={`access-category-${category.code}`}>
              <legend>
                {category.code}. {category.label_th}
              </legend>
              {category.note_th && <p className="form-field__hint">{category.note_th}</p>}
              {category.capabilities.map((cap) => {
                const view = switchView(cap.code, draft, employee ? { kind: 'EMPLOYEE', employee } : { kind: 'DEPARTMENT', eligible })
                const allowed = grantable.has(cap.code)
                const stored = employee ? employee.capabilities.includes(cap.code) : null
                const on = view.kind === 'ON'
                return (
                  <div key={cap.code} className="access-switch-row">
                    <div className="access-switch-row__text">
                      <span className="access-switch-row__label">{cap.label_th}</span>
                      <span className="form-field__hint">{cap.effect_th}</span>
                      {cap.sensitive && (
                        <span className="status-badge status-badge--warning" data-testid={`access-sensitive-${cap.code}`}>
                          สิทธิ์มีผลทั้งระบบ: ให้ได้โดยผู้จัดการแผนกซ่อมบำรุงเท่านั้น
                        </span>
                      )}
                      {!employee && (
                        <span className="form-field__hint" data-testid={`access-count-${cap.code}`}>
                          ปัจจุบันมีสิทธิ์ {holderCount(cap.code, eligible)} จาก {eligible.length} คน
                        </span>
                      )}
                      {!allowed && <span className="form-field__hint">อยู่นอกขอบเขตอำนาจของคุณ</span>}
                      {cap.code in draft && <span className="status-badge status-badge--info">จะเปลี่ยน</span>}
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={view.kind === 'MIXED' ? 'mixed' : on}
                      aria-label={cap.label_th}
                      className={`access-switch access-switch--${view.kind.toLowerCase()}`}
                      disabled={!editable || !allowed || busy}
                      onClick={() => {
                        setPlan(null)
                        setSaved(null)
                        setDraft((d) => toggleDraft(d, cap.code, view, stored))
                      }}
                    >
                      {view.kind === 'MIXED' ? `${view.holders} จาก ${view.total}` : on ? 'เปิด' : 'ปิด'}
                    </button>
                  </div>
                )
              })}
            </fieldset>
          ))}
        </div>
      )}

      {target && (
        <div className="access-actions">
          <p className="form-field__hint">สวิตช์ที่เปลี่ยน: {changeCount} รายการ</p>
          <button type="button" className="button button--secondary" disabled={changeCount === 0 || busy} onClick={resetChange}>
            ล้างการเปลี่ยนแปลง
          </button>
          <button type="button" className="button button--primary" disabled={changeCount === 0 || busy || !editable} onClick={() => void preview()}>
            ตรวจสอบก่อนบันทึก
          </button>
        </div>
      )}

      {actionFailure && (
        <p className="form-field__error" role="alert" data-testid="access-error">
          {actionFailure.message}
          {actionFailure.code ? ` (${actionFailure.code})` : ''}
        </p>
      )}

      {plan && (
        <div className="access-preview" data-testid="access-preview">
          <h3>ตัวอย่างการเปลี่ยนแปลง</h3>
          <p>
            {plan.target_kind === 'DEPARTMENT' ? 'ทุกคนในแผนก' : 'พนักงานรายบุคคล'}: มีผลกับพนักงาน {plan.target_count} คน
            {plan.target_kind === 'DEPARTMENT' && ` จากพนักงานในแผนก ${plan.eligible_count + plan.excluded.filter((e) => e.reason === 'INACTIVE').length} คน`}
          </p>
          {plan.excluded.length > 0 && (
            <ul data-testid="access-preview-excluded">
              {plan.excluded.map((e) => (
                <li key={e.personnel_id}>
                  ไม่รวม {e.name || e.personnel_id}: {EXCLUSION_LABELS[e.reason] ?? e.reason}
                </li>
              ))}
            </ul>
          )}
          <ul>
            {plan.per_capability.map((c) => (
              <li key={c.capability}>
                {c.action === 'GRANT' ? 'เปิด' : 'ปิด'} “{labelOf(c.capability)}”: เปลี่ยน {c.changed} คน, ไม่เปลี่ยน {c.unchanged} คน
              </li>
            ))}
          </ul>
          <div className="form-field">
            <label htmlFor="access-reason">เหตุผลของการเปลี่ยนสิทธิ์ (จำเป็น)</label>
            <textarea id="access-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </div>
          <button
            type="button"
            className="button button--primary"
            disabled={busy}
            onClick={() => (reason.trim() ? setConfirming(true) : setActionFailure({ message: describeErrorCode('ACCESS_REASON_REQUIRED') }))}
          >
            บันทึกการเปลี่ยนสิทธิ์
          </button>
        </div>
      )}
      <ConfirmDialog
        open={confirming}
        title="ยืนยันการเปลี่ยนสิทธิ์"
        description={
          plan
            ? `มีผลกับพนักงาน ${plan.target_count} คน${plan.excluded.length ? ` (ไม่รวม ${plan.excluded.length} คนตามเหตุผลที่แสดง)` : ''} — ระบบจะตรวจสอบสิทธิ์และจำนวนอีกครั้งก่อนบันทึก`
            : undefined
        }
        confirmLabel="ยืนยันบันทึก"
        onConfirm={() => void apply()}
        onCancel={() => setConfirming(false)}
      />
      {me.is_root && employee && employee.active && !employee.is_self && departments && (
        <DelegationForm key={employee.personnel_id} employeeId={employee.personnel_id} employeeName={employee.name} departments={departments} catalog={catalog} reloadMe={reloadMe} />
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Delegation (root only)
// ---------------------------------------------------------------------------

function DelegationForm({
  employeeId,
  employeeName,
  departments,
  catalog,
  reloadMe,
}: {
  employeeId: string
  employeeName: string
  departments: AccessDepartment[]
  catalog: CatalogCategory[]
  reloadMe: () => Promise<void>
}) {
  const [departmentId, setDepartmentId] = useState('')
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const intent = useRef<string | null>(null)

  const submit = async () => {
    if (!departmentId || chosen.size === 0) return setFailure({ message: 'กรุณาเลือกแผนกและสิทธิ์ที่มอบอำนาจอย่างน้อยหนึ่งข้อ' })
    if (!reason.trim()) return setFailure({ message: describeErrorCode('ACCESS_REASON_REQUIRED') })
    setBusy(true)
    setFailure(null)
    const me = await accessApi.me()
    if (!me.ok) {
      setBusy(false)
      return setFailure(failureOf(me.error))
    }
    intent.current ??= newRequestId()
    const result = await accessApi.delegate(
      { delegate_personnel_id: employeeId, department_id: departmentId, capabilities: [...chosen].sort(), reason_th: reason.trim(), expected_revision: me.data.revision },
      intent.current,
    )
    setBusy(false)
    if (result.ok) {
      intent.current = null
      setDone(`มอบอำนาจให้ ${employeeName} แล้ว (${result.data.capabilities.length} สิทธิ์)`)
      setChosen(new Set())
      setReason('')
      await reloadMe()
    } else {
      if (result.error instanceof ApiError) intent.current = null
      setFailure(failureOf(result.error))
    }
  }

  return (
    <details className="disclosure access-delegation-form">
      <summary>มอบอำนาจจัดการสิทธิ์ให้ {employeeName}</summary>
      <p className="form-field__hint">
        ผู้รับมอบอำนาจให้/ถอนได้เฉพาะสิทธิ์ที่เลือกและเฉพาะพนักงานในแผนกที่กำหนด มอบต่อไม่ได้ และแก้ไขสิทธิ์ของตนเองไม่ได้
        การยกเลิกการมอบอำนาจมีผลทันทีโดยไม่ย้อนสิทธิ์ที่ให้ไปแล้ว
      </p>
      <div className="form-field">
        <label htmlFor="delegation-department">แผนกที่มอบอำนาจ</label>
        <select id="delegation-department" value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
          <option value="">— เลือกแผนก —</option>
          {departments.map((d) => (
            <option key={d.department_id} value={d.department_id}>
              {d.department_name_th || d.department_id}
            </option>
          ))}
        </select>
      </div>
      <fieldset className="access-category">
        <legend>สิทธิ์ที่ผู้รับมอบอำนาจจัดการได้</legend>
        <p className="form-field__hint">สิทธิ์ที่มีผลทั้งระบบมอบอำนาจไม่ได้</p>
        {catalog.flatMap((c) => c.capabilities).filter((cap) => !cap.sensitive).map((cap) => (
          <label key={cap.code} className="checkbox-row">
            <input
              type="checkbox"
              checked={chosen.has(cap.code)}
              onChange={(e) => {
                const next = new Set(chosen)
                if (e.target.checked) next.add(cap.code)
                else next.delete(cap.code)
                setChosen(next)
              }}
            />
            {cap.label_th}
          </label>
        ))}
      </fieldset>
      <div className="form-field">
        <label htmlFor="delegation-reason">เหตุผลการมอบอำนาจ (จำเป็น)</label>
        <textarea id="delegation-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
      </div>
      {failure && (
        <p className="form-field__error" role="alert">
          {failure.message}
        </p>
      )}
      {done && <p role="status">{done}</p>}
      <button type="button" className="button button--primary" disabled={busy} onClick={() => void submit()}>
        มอบอำนาจ
      </button>
    </details>
  )
}

function DelegationList({ me, reloadMe }: { me: AccessMe; reloadMe: () => Promise<void> }) {
  const [items, setItems] = useState<AccessDelegation[] | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [revoking, setRevoking] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const intent = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void accessApi.delegations().then((result) => {
      if (cancelled) return
      if (result.ok) setItems(result.data)
      else setFailure(failureOf(result.error))
    })
    return () => {
      cancelled = true
    }
  }, [me.revision])

  const revoke = async (id: string) => {
    if (!reason.trim()) return setFailure({ message: describeErrorCode('ACCESS_REASON_REQUIRED') })
    setFailure(null)
    intent.current ??= newRequestId()
    const result = await accessApi.revokeDelegation(id, reason.trim(), me.revision, intent.current)
    if (result.ok) {
      intent.current = null
      setRevoking(null)
      setReason('')
      await reloadMe()
    } else {
      if (result.error instanceof ApiError) intent.current = null
      setFailure(failureOf(result.error))
      if (result.error instanceof ApiError && result.error.code === 'ACCESS_STALE_REVISION') await reloadMe()
    }
  }

  return (
    <Card>
      <h2>การมอบอำนาจ</h2>
      {failure && (
        <p className="form-field__error" role="alert">
          {failure.message}
        </p>
      )}
      {items === null && !failure && <LoadingState />}
      {items?.length === 0 && <p className="form-field__hint">ยังไม่มีการมอบอำนาจ</p>}
      <ul className="access-list" data-testid="access-delegations">
        {items?.map((d) => (
          <li key={d.delegation_id}>
            <strong>{d.delegate_name || d.delegate_personnel_id}</strong> — แผนก {d.department_name_th || d.department_id}:{' '}
            {d.capabilities.length} สิทธิ์ · มอบเมื่อ {formatThaiDateTime(d.granted_at)} · เหตุผล: {d.reason_th}
            <br />
            สถานะ:{' '}
            {d.revoked
              ? `ยกเลิกแล้ว ${d.revoked_at ? formatThaiDateTime(d.revoked_at) : ''} (${d.revoke_reason_th ?? ''})`
              : d.effective
                ? 'มีผล'
                : 'ไม่มีผล (ผู้รับมอบย้ายแผนกหรือไม่อยู่ในสถานะใช้งาน)'}
            {me.is_root && !d.revoked && (
              revoking === d.delegation_id ? (
                <div className="form-field">
                  <label htmlFor={`revoke-${d.delegation_id}`}>เหตุผลการยกเลิก (จำเป็น)</label>
                  <textarea id={`revoke-${d.delegation_id}`} value={reason} onChange={(e) => setReason(e.target.value)} />
                  <button type="button" className="button button--primary" onClick={() => void revoke(d.delegation_id)}>
                    ยืนยันยกเลิกการมอบอำนาจ
                  </button>
                </div>
              ) : (
                <button type="button" className="button button--secondary" onClick={() => setRevoking(d.delegation_id)}>
                  ยกเลิกการมอบอำนาจ
                </button>
              )
            )}
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Root position (current holder, handover, technical recovery)
// ---------------------------------------------------------------------------

function RootPositionSection({ me, reloadMe }: { me: AccessMe; reloadMe: () => Promise<void> }) {
  const [view, setView] = useState<RootView | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [successor, setSuccessor] = useState('')
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)
  const intent = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void accessApi.root().then((result) => {
      if (cancelled) return
      if (result.ok) setView(result.data)
      else setFailure(failureOf(result.error))
    })
    return () => {
      cancelled = true
    }
  }, [me.revision])

  const appoint = async () => {
    setConfirming(false)
    if (!view) return
    setFailure(null)
    intent.current ??= newRequestId()
    const result = await accessApi.appointRoot(successor.trim(), reason.trim(), view.revision, intent.current)
    if (result.ok) {
      intent.current = null
      setView(result.data)
      setSuccessor('')
      setReason('')
      await reloadMe()
    } else {
      if (result.error instanceof ApiError) intent.current = null
      setFailure(failureOf(result.error))
    }
  }

  const canAppoint = view !== null && (me.is_root || (me.recovery && !view.valid))

  return (
    <Card>
      <h2>ตำแหน่ง{view?.position_th ?? 'ผู้จัดการแผนกซ่อมบำรุง'}</h2>
      {failure && (
        <p className="form-field__error" role="alert">
          {failure.message}
        </p>
      )}
      {view && (
        <>
          <p data-testid="access-root-holder">
            ผู้ดำรงตำแหน่งปัจจุบัน: {view.holder ? `${view.holder.name} (${view.holder.personnel_id})` : 'ไม่มีผู้ดำรงตำแหน่งที่ถูกต้อง'}
          </p>
          <p className="form-field__hint">อำนาจสูงสุดเป็นของตำแหน่ง: เมื่อส่งมอบตำแหน่ง ผู้ดำรงตำแหน่งเดิมจะหมดอำนาจทันที</p>
          <details className="disclosure">
            <summary>ประวัติการแต่งตั้ง ({view.appointments.length})</summary>
            <ul className="access-list">
              {view.appointments.map((a, index) => (
                <li key={`${a.appointed_at}-${index}`}>
                  {formatThaiDateTime(a.appointed_at)} — {a.name || a.personnel_id} · {ROOT_MODE_LABELS[a.mode ?? ''] ?? a.mode} · โดย{' '}
                  {a.actor_name_snapshot || a.actor_user_id || 'ระบบ'} · {a.reason_th}
                </li>
              ))}
            </ul>
          </details>
          {canAppoint && (
            <details className="disclosure">
              <summary>{me.is_root ? 'ส่งมอบตำแหน่ง' : 'กู้คืนทางเทคนิค (ไม่มีผู้ดำรงตำแหน่งที่ถูกต้อง)'}</summary>
              <div className="form-field">
                <label htmlFor="root-successor">รหัสพนักงานผู้รับตำแหน่ง</label>
                <input id="root-successor" value={successor} onChange={(e) => setSuccessor(e.target.value)} />
              </div>
              <div className="form-field">
                <label htmlFor="root-reason">เหตุผลการแต่งตั้ง (จำเป็น)</label>
                <textarea id="root-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
              </div>
              <button
                type="button"
                className="button button--primary"
                disabled={!successor.trim() || !reason.trim()}
                onClick={() => setConfirming(true)}
              >
                แต่งตั้ง
              </button>
            </details>
          )}
        </>
      )}
      <ConfirmDialog
        open={confirming}
        title="ยืนยันการแต่งตั้งผู้ดำรงตำแหน่ง"
        description={`ผู้รับตำแหน่ง ${successor} จะได้อำนาจจัดการสิทธิ์สูงสุด และผู้ดำรงตำแหน่งเดิมจะหมดอำนาจทันที`}
        confirmLabel="ยืนยันแต่งตั้ง"
        onConfirm={() => void appoint()}
        onCancel={() => setConfirming(false)}
      />
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Audit history (read-only)
// ---------------------------------------------------------------------------

function AuditSection({ me }: { me: AccessMe }) {
  const [entries, setEntries] = useState<AccessAuditEntry[] | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [personnelId, setPersonnelId] = useState('')

  const load = useCallback(async (pid: string) => {
    const result = await accessApi.audit({ personnelId: pid.trim() || undefined })
    if (result.ok) {
      setEntries(result.data)
      setFailure(null)
    } else setFailure(failureOf(result.error))
  }, [])

  useEffect(() => {
    let cancelled = false
    void accessApi.audit({}).then((result) => {
      if (cancelled) return
      if (result.ok) setEntries(result.data)
      else setFailure(failureOf(result.error))
    })
    return () => {
      cancelled = true
    }
  }, [me.revision])

  const rows = useMemo(() => entries?.filter((e) => e.kind !== 'GRANT_BATCH') ?? [], [entries])

  return (
    <Card>
      <h2>ประวัติการเปลี่ยนสิทธิ์</h2>
      <div className="access-actions">
        <div className="form-field">
          <label htmlFor="audit-personnel">กรองตามรหัสพนักงาน</label>
          <input id="audit-personnel" value={personnelId} onChange={(e) => setPersonnelId(e.target.value)} />
        </div>
        <button type="button" className="button button--secondary" onClick={() => void load(personnelId)}>
          ค้นหา
        </button>
      </div>
      {failure && (
        <p className="form-field__error" role="alert">
          {failure.message}
        </p>
      )}
      {entries === null && !failure && <LoadingState />}
      {entries !== null && rows.length === 0 && <p className="form-field__hint">ไม่มีประวัติ</p>}
      <ul className="access-list" data-testid="access-audit">
        {rows.slice(0, 200).map((e) => (
          <li key={e.event_id}>
            <span>{formatThaiDateTime(e.recorded_at)}</span> · <strong>{AUDIT_KIND_LABELS[e.kind] ?? e.kind}</strong>
            {e.capability && ` “${e.capability}”`} · {e.target_name || e.personnel_id || e.department_id} · โดย{' '}
            {e.actor_name_snapshot || e.actor_user_id || 'ระบบ'}
            {e.reason_th && ` · เหตุผล: ${e.reason_th}`}
          </li>
        ))}
      </ul>
    </Card>
  )
}
