import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  assetTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  inspectionResultLabel,
  inspectionResultTone,
} from '../lib/labels'
import type { InspectionDetail } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; detail: InspectionDetail }

/**
 * Read-only immutable inspection record. Shows the checklist item text
 * exactly as snapshotted at submission time (Phase 3 scope: "Historical
 * inspection must show the actual checklist revision used at submission
 * time") — this page never offers an edit/void action.
 */
export function InspectionDetailPage() {
  const { inspectionId = '' } = useParams<{ inspectionId: string }>()
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<InspectionDetail>(`/inspections/${inspectionId}`)
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', detail: result.data })
  }, [inspectionId])

  useEffect(() => {
    void load()
  }, [load])

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดผลการตรวจเช็ค..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>ผลการตรวจเช็ค</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { header, items, findings } = state.detail

  return (
    <section className="page">
      <h1>ผลการตรวจเช็ค</h1>
      <p>รหัสผลการตรวจ: {header.inspection_id}</p>

      <Card>
        <div className="status-card__row">
          <span>ประเภทสินทรัพย์</span>
          <span>{assetTypeLabel[header.asset_type] ?? header.asset_type}</span>
        </div>
        <div className="status-card__row">
          <span>รหัสสินทรัพย์</span>
          <span>{header.asset_id}</span>
        </div>
        <div className="status-card__row">
          <span>วันที่ตรวจ</span>
          <span>{formatThaiDateTime(header.submitted_at)}</span>
        </div>
        <div className="status-card__row">
          <span>ผู้ตรวจ</span>
          <span>{header.inspector_user_id ?? 'ไม่ทราบ'}</span>
        </div>
        <div className="status-card__row">
          <span>รุ่นรายการตรวจเช็คที่ใช้</span>
          <span>รุ่นที่ {header.revision_number}</span>
        </div>
      </Card>

      {findings.length > 0 && (
        <Card className="state-panel--denied">
          <h2>ข้อบกพร่องที่พบ</h2>
          <ul>
            {findings.map((finding) => {
              const assetPrefix = finding.asset_type === 'VEHICLE' ? 'vehicle' : 'equipment'
              return (
                <li key={finding.finding_id}>
                  {finding.item_title}{' '}
                  <Link
                    to={`/${assetPrefix}/${finding.asset_id}/repairs/new?source_type=FINDING&source_id=${finding.finding_id}`}
                    className="button button--secondary"
                  >
                    แจ้งซ่อม
                  </Link>
                </li>
              )
            })}
          </ul>
          <p className="state-panel__meta">
            สามารถเลือกแจ้งซ่อมจากข้อบกพร่องแต่ละรายการได้ตามความจำเป็น
            (ระบบไม่สร้างใบแจ้งซ่อมให้อัตโนมัติทุกข้อบกพร่อง)
          </p>
        </Card>
      )}

      {items.map((item) => (
        <Card key={item.result_id}>
          <div className="checklist-item-card__header">
            <span className="checklist-item-card__sequence">{item.sequence}</span>
            <h3>{item.title}</h3>
          </div>
          {item.inspection_point && <p>จุดตรวจ: {item.inspection_point}</p>}
          <StatusBadge
            label={inspectionResultLabel[item.result] ?? item.result}
            tone={inspectionResultTone[item.result]}
          />
          {item.remark && <p>หมายเหตุ: {item.remark}</p>}
          {item.evidence.length > 0 && (
            <div className="checklist-item-card__reference">
              <p className="form-field__hint">รูปถ่ายหลักฐาน</p>
              <ul className="checklist-item-card__evidence-list">
                {item.evidence.map((evidence) => (
                  <li key={evidence.attachment_id}>
                    <img src={evidence.url} alt={`หลักฐานสำหรับ ${item.title}`} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      ))}
    </section>
  )
}
