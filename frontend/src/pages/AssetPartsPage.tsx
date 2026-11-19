import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { FormField } from '../components/FormField'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPostWithRequestId } from '../lib/apiClient'
import { CAN_TEST_MANAGE_PARTS } from '../lib/capabilityNames'
import { useTestGrantControlVisible } from '../lib/masterRecords'
import {
  describeErrorCode,
  dueActionLabel,
  dueStatusLabel,
  dueStatusTone,
  formatThaiDateTime,
  partInstanceStatusLabel,
  priorUsageQualityLabel,
} from '../lib/labels'
import { basisText, isUncertain, newRequestId, quantityText } from '../lib/partLifetime'
import type { AssetPartLifetime, AssetType, LifetimeRule, LifetimeStatus, PositionLifetimeRecord } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; records: PositionLifetimeRecord[]; summary: AssetPartLifetime | null; summaryError: string | null }

/** Historical declaration choices for a position record. A KNOWN non-zero
 * value needs evidence (FINAL §7.3a) and is entered through the API; the page
 * offers the two evidence-free cases: unknown, or a brand-new part (value 0). */
type PriorChoice = 'UNKNOWN' | 'NEW_PART'

function StatusSummary({ status }: { status: LifetimeStatus }) {
  return (
    <div data-testid="asset-status-summary">
      {status.counters.map((c) => (
        <div key={basisText(c)} className="status-card__row">
          <span>{basisText(c)} — รอบปัจจุบัน (ยืนยันแล้ว)</span>
          <span>{quantityText(c.verified_current_cycle)}</span>
        </div>
      ))}
      {status.rules.map((rule) => (
        <p key={rule.due_key} className="form-field__hint">
          {rule.due_action ? dueActionLabel[rule.due_action] : '—'}:{' '}
          <StatusBadge label={dueStatusLabel[rule.status]} tone={dueStatusTone[rule.status]} />
        </p>
      ))}
    </div>
  )
}

/**
 * Asset-scoped "อะไหล่/อายุการใช้งาน" page (Phase 5). Shows/creates
 * POSITION_LIFETIME enrollments for this asset. INSTANCE_TRACKED
 * components installed on this asset are tracked and viewed from their
 * own Part Instance detail page (reached via the Part Master catalog),
 * since their identity/history follows the physical component, not the
 * asset.
 */
export function AssetPartsPage() {
  const { vehicleId, equipmentId } = useParams<{ vehicleId?: string; equipmentId?: string }>()
  const assetType: AssetType = vehicleId ? 'VEHICLE' : 'EQUIPMENT'
  const assetId = vehicleId ?? equipmentId ?? ''

  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [formOpen, setFormOpen] = useState(false)
  const [positionCode, setPositionCode] = useState('')
  const [partId, setPartId] = useState('')
  const [prior, setPrior] = useState<PriorChoice>('UNKNOWN')
  const [newPartReference, setNewPartReference] = useState('')
  const [usageNote, setUsageNote] = useState('')
  const [intentId, setIntentId] = useState(newRequestId)
  const [replaceError, setReplaceError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const [result, summary] = await Promise.all([
      apiGet<PositionLifetimeRecord[]>(`/position-lifetime?asset_type=${assetType}&asset_id=${assetId}`),
      apiGet<AssetPartLifetime>(`/${assetType === 'VEHICLE' ? 'vehicles' : 'equipment'}/${assetId}/part-lifetime`),
    ])
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    // A summary load failure is shown as such — never as "nothing installed".
    setState({
      kind: 'ready',
      records: result.data,
      summary: summary.ok && Array.isArray(summary.data?.instances) ? summary.data : null,
      summaryError: summary.ok
        ? (Array.isArray(summary.data?.instances) ? null : 'ข้อมูลไม่อยู่ในรูปแบบที่คาดไว้')
        : summary.error instanceof ApiError ? describeErrorCode(summary.error.code) : summary.error.message,
    })
  }, [assetType, assetId])

  useEffect(() => {
    void load()
  }, [load])

  const submit = async () => {
    if (!positionCode.trim()) {
      setFormError('กรุณาระบุตำแหน่ง (position code)')
      return
    }
    setSubmitting(true)
    setFormError(null)
    const result = await apiPostWithRequestId<PositionLifetimeRecord>('/position-lifetime', {
      asset_type: assetType,
      asset_id: assetId,
      position_code: positionCode.trim(),
      part_id: partId.trim() || null,
      prior_usage: priorBody(),
    }, intentId)
    setSubmitting(false)
    if (result.ok) {
      setIntentId(newRequestId())
      setFormOpen(false)
      setPositionCode('')
      setPartId('')
      setPrior('UNKNOWN')
      setNewPartReference('')
      setUsageNote('')
      void load()
    } else {
      const err = result.error
      if (err instanceof ApiError && !isUncertain(err.status)) {
        setIntentId(newRequestId())
        setFormError(describeErrorCode(err.code))
      } else {
        setFormError('ไม่ทราบผลการบันทึก — กดบันทึกอีกครั้งเพื่อส่งคำขอเดิมซ้ำอย่างปลอดภัย')
      }
    }
  }

  function priorBody() {
    return prior === 'NEW_PART'
      ? { quality: 'KNOWN', value: 0, as_of: new Date().toISOString().slice(0, 10), evidence_type: 'NEW_PART',
          evidence_reference: newPartReference.trim() || null, note: usageNote.trim() || null }
      : { quality: 'UNKNOWN', value: null, note: usageNote.trim() || null }
  }

  // R8 PRE-UAT (workstream F): the existing position maintenance-event route (inspect / repair in
  // place) had no UI. It never opens or closes a lifetime and never resets anything. The backend
  // requires the event to anchor exactly one INSPECT / REPAIR rule (or one condition group) of the
  // position's part, so the user picks it from that part's rules.
  type MaintAction = 'INSPECTED' | 'REPAIRED_IN_PLACE'
  const maintVisible = useTestGrantControlVisible(CAN_TEST_MANAGE_PARTS)
  const [maint, setMaint] = useState<{ recordId: string; action: MaintAction; rules: LifetimeRule[] | null;
    target: string; requestId: string } | null>(null)
  const [maintMessage, setMaintMessage] = useState<string | null>(null)
  const openMaintenance = async (record: PositionLifetimeRecord, action: MaintAction) => {
    setMaintMessage(null)
    setMaint({ recordId: record.position_lifetime_id, action, rules: null, target: '', requestId: newRequestId() })
    // A position with no part on record has no rule to anchor: nothing can be recorded.
    const result = record.part_id
      ? await apiGet<LifetimeRule[]>(`/lifetime-rules?part_id=${encodeURIComponent(record.part_id)}`) : null
    setMaint((m) => (m && m.recordId === record.position_lifetime_id && m.action === action
      ? { ...m, rules: result?.ok ? result.data : [] } : m))
  }
  const maintTargets = (rules: LifetimeRule[], action: MaintAction) => {
    const due = action === 'INSPECTED' ? 'INSPECT' : 'REPAIR'
    const seen = new Set<string>()
    return rules.filter((r) => r.due_action === due).flatMap((r) => {
      const value = r.condition_group_key ? `group:${r.condition_group_key}` : `rule:${r.lifetime_rule_id}`
      if (seen.has(value)) return []
      seen.add(value)
      return [{ value, label: r.condition_group_key ? `กลุ่มเงื่อนไข ${r.condition_group_key}` : `${r.lifetime_rule_id}${r.note ? ` — ${r.note}` : ''}` }]
    })
  }
  const recordMaintenance = async () => {
    if (!maint || !maint.target) return
    const target = maint.target.startsWith('group:') ? { condition_group_key: maint.target.slice(6) }
      : { lifetime_rule_id: maint.target.slice(5) }
    const result = await apiPostWithRequestId(`/position-lifetime/${maint.recordId}/maintenance-events`,
      { action: maint.action, ...target }, maint.requestId)
    if (result.ok) {
      setMaintMessage(maint.action === 'INSPECTED' ? 'บันทึกการตรวจแล้ว' : 'บันทึกการซ่อมในที่แล้ว')
      setMaint(null)
      void load()
      return
    }
    const err = result.error
    if (err instanceof ApiError && !isUncertain(err.status)) {
      setMaint({ ...maint, requestId: newRequestId() })
      setMaintMessage(describeErrorCode(err.code))
    } else {
      // Unknown outcome: keep the same request id so a retry is the same intent (no duplicate).
      setMaintMessage('ไม่ทราบผลการบันทึก (การเชื่อมต่อขัดข้อง) — กดยืนยันอีกครั้งเพื่อส่งคำขอเดิมซ้ำอย่างปลอดภัย')
    }
  }

  const replaceRecord = async (recordId: string) => {
    setReplaceError(null)
    const result = await apiPostWithRequestId(`/position-lifetime/${recordId}/replace`, {
      reason: 'เปลี่ยนชิ้นส่วนตามตำแหน่ง',
      prior_usage: priorBody(),
    }, newRequestId())
    if (result.ok) {
      void load()
    } else {
      const err = result.error
      setReplaceError(err instanceof ApiError ? describeErrorCode(err.code) : err.message)
    }
  }

  return (
    <section className="page">
      <h1>อะไหล่/อายุการใช้งาน</h1>
      <p>รหัสอ้างอิง: {assetId}</p>
      <p className="form-field__hint">
        รหัสตำแหน่ง (position code) ด้านล่างเป็นข้อมูลตัวอย่างสำหรับพัฒนา/ทดสอบระบบเท่านั้น
        ยังไม่มีรหัสตำแหน่งมาตรฐานที่ได้รับการอนุมัติจากบริษัท
      </p>

      <Card>
        <Link to="/parts" className="button button--secondary button--full-width">
          ดูรายการอะไหล่ทั้งหมด (Part Master)
        </Link>
        <button
          type="button"
          className="button button--primary button--full-width"
          onClick={() => setFormOpen((open) => !open)}
        >
          + ลงทะเบียนอายุการใช้งานตามตำแหน่ง
        </button>
      </Card>

      {formOpen && (
        <Card>
          <h2>ลงทะเบียนอายุการใช้งานตามตำแหน่ง</h2>
          <div className="form-grid">
            <FormField label="ตำแหน่ง (position code)" htmlFor="position-code">
              <input
                id="position-code"
                type="text"
                value={positionCode}
                onChange={(event) => setPositionCode(event.target.value)}
                placeholder="เช่น BOOM-CYL-1 (ตัวอย่าง)"
              />
            </FormField>
            <FormField label="รหัสอะไหล่ (ถ้ามี)" htmlFor="position-part-id">
              <input
                id="position-part-id"
                type="text"
                value={partId}
                onChange={(event) => setPartId(event.target.value)}
                placeholder="เช่น PART-0004"
              />
            </FormField>
            <FormField label="ประวัติการใช้งานก่อนเริ่มติดตาม" htmlFor="position-quality">
              <select
                id="position-quality"
                value={prior}
                onChange={(event) => setPrior(event.target.value as PriorChoice)}
              >
                <option value="UNKNOWN">{priorUsageQualityLabel.UNKNOWN}</option>
                <option value="NEW_PART">ชิ้นใหม่ทั้งชิ้น (ค่า 0)</option>
              </select>
            </FormField>
            {prior === 'NEW_PART' && (
              <FormField label="เลขอ้างอิงหลักฐาน (เช่น เลขใบงาน)" htmlFor="position-evidence">
                <input id="position-evidence" type="text" value={newPartReference}
                  onChange={(event) => setNewPartReference(event.target.value)} />
              </FormField>
            )}
            {(
              <FormField label="หมายเหตุประวัติการใช้งาน" htmlFor="position-note">
                <textarea
                  id="position-note"
                  value={usageNote}
                  onChange={(event) => setUsageNote(event.target.value)}
                />
              </FormField>
            )}
            {formError && (
              <p className="form-field__error" role="alert">
                {formError}
              </p>
            )}
            <button
              type="button"
              className="button button--primary button--full-width"
              disabled={submitting}
              onClick={() => void submit()}
            >
              {submitting ? 'กำลังบันทึก...' : 'บันทึก'}
            </button>
          </div>
        </Card>
      )}

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดข้อมูลอายุการใช้งานตามตำแหน่ง..." />}

      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && state.summaryError && (
        <ErrorState message={`โหลดสถานะชิ้นงานที่ติดตั้งไม่สำเร็จ: ${state.summaryError}`} onRetry={load} />
      )}

      {state.kind === 'ready' && state.summary && (
        <Card>
          <h2>ชิ้นงานรายชิ้นที่ติดตั้งอยู่</h2>
          {state.summary.instances.length === 0 && <p>ไม่มีชิ้นงานรายชิ้นติดตั้งอยู่บนสินทรัพย์นี้</p>}
          <ul>
            {state.summary.instances.map((instance) => (
              <li key={instance.target_id} data-testid="installed-instance">
                <p>
                  <Link to={`/part-instances/${instance.target_id}`}>{instance.target_id}</Link> ({instance.part_id})
                  {instance.host?.position_code ? ` — ตำแหน่ง ${instance.host.position_code}` : ''} —{' '}
                  {partInstanceStatusLabel[instance.status] ?? instance.status}
                </p>
                <StatusSummary status={instance} />
                {(instance.hosted_positions ?? []).map((hosted) => (
                  <div key={hosted.target_id} className="part-hosted" data-testid="hosted-position">
                    <p>↳ ชิ้นส่วนภายใน: {hosted.host?.position_code} ({hosted.part_id ?? 'ไม่ระบุอะไหล่'})</p>
                    <StatusSummary status={hosted} />
                  </div>
                ))}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {replaceError && <p className="form-field__error" role="alert">{replaceError}</p>}

      {state.kind === 'ready' && state.records.length === 0 && (
        <Card>
          <p>ยังไม่มีข้อมูลอายุการใช้งานตามตำแหน่งสำหรับสินทรัพย์นี้</p>
        </Card>
      )}

      {state.kind === 'ready' &&
        state.records.map((record) => (
          <Card key={record.position_lifetime_id}>
            <h2>ตำแหน่ง: {record.position_code}</h2>
            {record.part_id && <p className="form-field__hint">รหัสอะไหล่: {record.part_id}</p>}
            <div className="status-card__row">
              <span>ประวัติการใช้งานก่อนเริ่มติดตาม</span>
              <span>{priorUsageQualityLabel[record.prior_usage.quality]}</span>
            </div>
            <div className="status-card__row">
              <span>ค่าที่ทราบ</span>
              <span>
                {record.prior_usage.quality === 'UNKNOWN' || record.prior_usage.value === null
                  ? 'ไม่ทราบค่า'
                  : record.prior_usage.value}
              </span>
            </div>
            {(() => {
              const status = state.summary?.positions.find((p) => p.target_id === record.position_lifetime_id)
              return status ? <StatusSummary status={status} /> : null
            })()}
            <p className="form-field__hint">
              ค่ากำหนดอายุจริงและช่วงเตือนยังรอข้อมูลที่ได้รับอนุมัติ (G01/G02) — ไม่มีการเดาค่า
            </p>
            <p className="form-field__hint">เริ่มติดตามเมื่อ {formatThaiDateTime(record.started_at)}</p>
            {record.ended_at ? (
              <p className="form-field__hint">ถูกเปลี่ยนแล้ว (รายการใหม่: {record.superseded_by_id})</p>
            ) : (
              <>
                <button type="button" className="button button--secondary button--full-width"
                  onClick={() => void replaceRecord(record.position_lifetime_id)}>
                  เปลี่ยนชิ้นส่วนที่ตำแหน่งนี้ (ตามประวัติที่เลือกด้านบน)
                </button>
                {maintVisible && (<>
                <button type="button" className="button button--secondary button--full-width"
                  onClick={() => void openMaintenance(record, 'INSPECTED')}>
                  ตรวจที่ตำแหน่งนี้ (ไม่รีเซ็ตอายุ)
                </button>
                <button type="button" className="button button--secondary button--full-width"
                  onClick={() => void openMaintenance(record, 'REPAIRED_IN_PLACE')}>
                  ซ่อมในที่ที่ตำแหน่งนี้ (ไม่รีเซ็ตอายุ)
                </button>
                </>)}
                {maint?.recordId === record.position_lifetime_id && (
                  <div className="form-grid">
                    <FormField label={maint.action === 'INSPECTED' ? 'การตรวจตามกฎ' : 'การซ่อมในที่ตามกฎ'}
                      htmlFor={`maint-target-${record.position_lifetime_id}`}>
                      <select id={`maint-target-${record.position_lifetime_id}`} value={maint.target} disabled={!maint.rules}
                        onChange={(e) => setMaint({ ...maint, target: e.target.value, requestId: newRequestId() })}>
                        <option value="">{maint.rules ? '— เลือกกฎ —' : 'กำลังโหลดกฎ...'}</option>
                        {maintTargets(maint.rules ?? [], maint.action).map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                      </select>
                    </FormField>
                    {maint.rules && maintTargets(maint.rules, maint.action).length === 0 && (
                      <p className="form-field__hint" role="status">
                        อะไหล่นี้ยังไม่มีกฎ{maint.action === 'INSPECTED' ? 'การตรวจ (INSPECT)' : 'การซ่อม (REPAIR)'} — บันทึกไม่ได้จนกว่าจะมีกฎที่อนุมัติ
                      </p>
                    )}
                    <button type="button" className="button button--primary button--full-width" disabled={!maint.target}
                      onClick={() => void recordMaintenance()}>
                      ยืนยันการตรวจ/ซ่อม
                    </button>
                  </div>
                )}
              </>
            )}
            {maintMessage && <p role="status">{maintMessage}</p>}
          </Card>
        ))}
    </section>
  )
}
