import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card } from '../components/Card'
import {
  ChangeEquipmentStatusDialog,
  type StatusDialogError,
} from '../components/ChangeEquipmentStatusDialog'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet, apiPost, type ApiResult } from '../lib/apiClient'
import {
  describeErrorCode,
  equipmentCategoryLabel,
  equipmentStatusLabel,
  equipmentStatusTone,
  formatThaiDateTime,
} from '../lib/labels'
import type { Equipment, EquipmentOperationalStatus, EquipmentStatusHistoryEntry } from '../lib/types'

interface PageWarning {
  message: string
  requestId?: string | null
}

/** History as displayed: the last successfully loaded entries (null when
 * none has loaded yet) and, separately, the latest history-load error — so a
 * failed refresh can show its error without discarding shown history. */
interface HistoryView {
  entries: EquipmentStatusHistoryEntry[] | null
  error: PageWarning | null
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; equipment: Equipment; history: HistoryView }

/**
 * Phase 7 Batch 7K2 (DEC-K6(a)) — Thai wording for status-write outcomes.
 * "ยืนยัน" (acknowledged) refers to the API's acknowledgement of the request,
 * never to a re-read stored value.
 */
const statusOutcomeMessages = {
  masterRejected:
    'Google Sheets ปฏิเสธคำขอเปลี่ยนสถานะ สถานะน่าจะยังไม่ถูกเปลี่ยน ระบบไม่ได้ลองใหม่อัตโนมัติ',
  masterUnknown:
    'ไม่ทราบผลการเปลี่ยนสถานะ (อาจเปลี่ยนแล้วหรือยังไม่เปลี่ยน) กรุณาตรวจสอบสถานะปัจจุบันก่อนลองใหม่',
  historyRejected:
    'ระบบได้รับการยืนยันการเปลี่ยนสถานะแล้ว แต่คำขอบันทึกประวัติถูกปฏิเสธ ประวัติของการเปลี่ยนครั้งนี้น่าจะไม่ถูกบันทึก ระบบไม่ได้ลองใหม่อัตโนมัติ กรุณาแจ้งผู้ดูแลข้อมูล',
  historyUnknown:
    'ระบบได้รับการยืนยันการเปลี่ยนสถานะแล้ว แต่ไม่ทราบผลการบันทึกประวัติ (อาจบันทึกแล้วหรือไม่ก็ได้) กรุณาตรวจสอบประวัติก่อนดำเนินการต่อ',
  stale: 'โหลดข้อมูลล่าสุดไม่สำเร็จ ข้อมูลที่แสดงอาจไม่เป็นปัจจุบัน',
} as const

type StatusFailure =
  | { kind: 'inline'; message: string; requestId?: string | null }
  | { kind: 'page'; message: string; requestId?: string | null }

/**
 * P (pre-write) and R (rejected update) stay in the open dialog; U (update
 * outcome unknown, INTERNAL_ERROR, no usable response) and H (update
 * acknowledged, history failed) become a page-level warning plus one
 * non-destructive refresh. The mutation itself is never retried.
 */
function classifyStatusFailure(error: ApiError | Error): StatusFailure {
  if (!(error instanceof ApiError)) {
    return { kind: 'page', message: statusOutcomeMessages.masterUnknown }
  }
  const requestId = error.requestId
  if (error.code === 'EQUIPMENT_MASTER_WRITE_FAILED') {
    return error.details?.equipment_write_outcome === 'rejected'
      ? { kind: 'inline', message: statusOutcomeMessages.masterRejected, requestId }
      : { kind: 'page', message: statusOutcomeMessages.masterUnknown, requestId }
  }
  if (error.code === 'EQUIPMENT_STATUS_HISTORY_WRITE_FAILED') {
    return error.details?.history_write_outcome === 'rejected'
      ? { kind: 'page', message: statusOutcomeMessages.historyRejected, requestId }
      : { kind: 'page', message: statusOutcomeMessages.historyUnknown, requestId }
  }
  if (error.code === 'INTERNAL_ERROR') {
    return { kind: 'page', message: statusOutcomeMessages.masterUnknown, requestId }
  }
  return { kind: 'inline', message: describeErrorCode(error.code), requestId }
}

function historyEntries(data: EquipmentStatusHistoryEntry[]): EquipmentStatusHistoryEntry[] {
  return Array.isArray(data) ? data : []
}

function readError(error: ApiError | Error): PageWarning {
  return {
    message: error instanceof ApiError ? describeErrorCode(error.code) : error.message,
    requestId: error instanceof ApiError ? error.requestId : null,
  }
}

function historyViewFrom(result: ApiResult<EquipmentStatusHistoryEntry[]>): HistoryView {
  return result.ok
    ? { entries: historyEntries(result.data), error: null }
    : { entries: null, error: readError(result.error) }
}

export function EquipmentDetailPage() {
  const { equipmentId = '' } = useParams<{ equipmentId: string }>()
  // Route-specific state (dialog, submitting, inline error, mutation warning,
  // stale/refreshing, data) belongs to ONE equipment id: a new id gets a fresh
  // instance. The previous instance's effect cleanup still advances its read
  // generation and route epoch, so its pending POST/read completions return
  // without touching any state.
  return <EquipmentDetailView key={equipmentId} equipmentId={equipmentId} />
}

function EquipmentDetailView({ equipmentId }: { equipmentId: string }) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [statusDialogOpen, setStatusDialogOpen] = useState(false)
  const [statusSubmitting, setStatusSubmitting] = useState(false)
  const [dialogError, setDialogError] = useState<StatusDialogError | null>(null)
  const [mutationWarning, setMutationWarning] = useState<PageWarning | null>(null)
  const [stale, setStale] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const warningRef = useRef<HTMLDivElement>(null)
  // Read ordering: every load()/refresh() takes a new generation; a read may
  // apply data, history errors, staleness or the refreshing state only while
  // its generation is still current. A new submission, a route change and
  // unmount also advance it, so reads started earlier can never apply.
  const readGeneration = useRef(0)
  // A status POST result applies only if the route has not changed since.
  const routeEpoch = useRef(0)

  // The warning is rendered near the top while the user is usually scrolled
  // down at the dialog: bring it into view and move focus to it.
  useEffect(() => {
    if (mutationWarning && warningRef.current) {
      warningRef.current.scrollIntoView?.({ block: 'start' })
      warningRef.current.focus()
    }
  }, [mutationWarning])

  const fetchBoth = useCallback(
    () =>
      Promise.all([
        apiGet<Equipment>(`/equipment/${equipmentId}`),
        apiGet<EquipmentStatusHistoryEntry[]>(`/equipment/${equipmentId}/status-history`),
      ]),
    [equipmentId],
  )

  const load = useCallback(async () => {
    const generation = ++readGeneration.current
    setState({ kind: 'loading' })
    const [equipmentResult, historyResult] = await fetchBoth()
    if (generation !== readGeneration.current) return
    setRefreshing(false)
    if (!equipmentResult.ok) {
      setState({ kind: 'error', ...readError(equipmentResult.error) })
      return
    }
    setStale(false)
    setState({
      kind: 'ready',
      equipment: equipmentResult.data,
      history: historyViewFrom(historyResult),
    })
  }, [fetchBoth])

  /** Separate read requests after a U/H outcome: they show whatever is stored
   * when they run. Only when BOTH reads succeed is the displayed data
   * replaced; otherwise the previously displayed equipment and history are
   * kept, marked stale, and a history failure is shown alongside the kept
   * history. Nothing is re-requested automatically. */
  const refresh = useCallback(async () => {
    const generation = ++readGeneration.current
    setRefreshing(true)
    const [equipmentResult, historyResult] = await fetchBoth()
    if (generation !== readGeneration.current) return
    setRefreshing(false)
    if (equipmentResult.ok && historyResult.ok) {
      setStale(false)
      setState({
        kind: 'ready',
        equipment: equipmentResult.data,
        history: { entries: historyEntries(historyResult.data), error: null },
      })
      return
    }
    setStale(true)
    if (!historyResult.ok) {
      const error = readError(historyResult.error)
      setState((previous) =>
        previous.kind === 'ready' ? { ...previous, history: { ...previous.history, error } } : previous,
      )
    }
  }, [fetchBoth])

  useEffect(() => {
    void load()
    return () => {
      // Route change or unmount: pending reads and status results of the
      // previous equipment id must not apply.
      readGeneration.current += 1
      routeEpoch.current += 1
    }
  }, [load])

  const submitStatusChange = useCallback(
    async (status: EquipmentOperationalStatus, reason: string) => {
      // Reads started before this submission must not apply during or after
      // it; the submission's own outcome decides the next read.
      readGeneration.current += 1
      const epoch = routeEpoch.current
      setRefreshing(false)
      setStatusSubmitting(true)
      setDialogError(null)
      setMutationWarning(null)
      const result = await apiPost<Equipment>(`/equipment/${equipmentId}/status`, {
        status,
        reason: reason || null,
      })
      if (epoch !== routeEpoch.current) return
      setStatusSubmitting(false)
      if (result.ok) {
        setStatusDialogOpen(false)
        void load()
        return
      }
      const failure = classifyStatusFailure(result.error)
      if (failure.kind === 'inline') {
        setDialogError({ message: failure.message, requestId: failure.requestId })
        return
      }
      setStatusDialogOpen(false)
      setMutationWarning({ message: failure.message, requestId: failure.requestId })
      void refresh()
    },
    [equipmentId, load, refresh],
  )

  if (state.kind === 'loading') {
    return (
      <section className="page">
        <LoadingState message="กำลังโหลดข้อมูลเครื่องมือ..." />
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="page">
        <h1>รายละเอียดเครื่องมือ</h1>
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      </section>
    )
  }

  const { equipment, history } = state
  const isRetired = equipment.operational_status === 'RETIRED'

  return (
    <section className="page">
      <h1>{equipment.name}</h1>
      <p>รหัสเครื่องมือ: {equipment.equipment_id}</p>

      {mutationWarning && (
        <Card className="state-panel state-panel--error">
          <div role="alert" ref={warningRef} tabIndex={-1}>
            <p className="state-panel__title">ผลการเปลี่ยนสถานะไม่ครบถ้วน</p>
            <p>{mutationWarning.message}</p>
            {mutationWarning.requestId && (
              <p className="state-panel__meta">รหัสอ้างอิง: {mutationWarning.requestId}</p>
            )}
          </div>
          <button
            type="button"
            className="button button--secondary button--full-width"
            onClick={() => setMutationWarning(null)}
          >
            ปิดคำเตือน
          </button>
        </Card>
      )}

      {stale && (
        <Card className="state-panel state-panel--denied">
          <p role="status">{statusOutcomeMessages.stale}</p>
          <button
            type="button"
            className="button button--secondary button--full-width"
            disabled={refreshing}
            onClick={() => void refresh()}
          >
            {refreshing ? 'กำลังโหลด...' : 'โหลดใหม่'}
          </button>
        </Card>
      )}

      {isRetired && (
        <Card className="state-panel state-panel--denied">
          <p className="state-panel__title">เครื่องมือนี้ถูกปลดระวางแล้ว</p>
          <p>ไม่สามารถเริ่มงานตรวจเช็ค PM หรือแจ้งซ่อมใหม่สำหรับเครื่องมือนี้ได้ (ประวัติเดิมยังคงอยู่ครบถ้วน)</p>
        </Card>
      )}

      <Card>
        <div className="status-card__actions">
          <Link
            to={`/equipment/${equipment.equipment_id}/inspect`}
            className="button button--primary button--full-width"
            aria-disabled={isRetired}
            onClick={(event) => isRetired && event.preventDefault()}
          >
            ตรวจเช็ค
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/inspections`}
            className="button button--secondary button--full-width"
          >
            ประวัติการตรวจเช็ค
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/pm`}
            className="button button--primary button--full-width"
            aria-disabled={isRetired}
            onClick={(event) => isRetired && event.preventDefault()}
          >
            PM
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/repairs/new`}
            className="button button--primary button--full-width"
            aria-disabled={isRetired}
            onClick={(event) => isRetired && event.preventDefault()}
          >
            แจ้งซ่อม
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/repairs`}
            className="button button--secondary button--full-width"
          >
            ประวัติการซ่อม
          </Link>
          <Link
            to={`/equipment/${equipment.equipment_id}/parts`}
            className="button button--secondary button--full-width"
          >
            อะไหล่/อายุการใช้งาน
          </Link>
        </div>
      </Card>

      <Card>
        <div className="status-card__row">
          <span>รหัส</span>
          <span>{equipment.equipment_code}</span>
        </div>
        <div className="status-card__row">
          <span>ประเภท</span>
          <span>{equipmentCategoryLabel[equipment.category] ?? equipment.category}</span>
        </div>
        <div className="status-card__row">
          <span>หมายเลขซีเรียล</span>
          <span>{equipment.serial_number ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>ตำแหน่งที่ตั้ง</span>
          <span>{equipment.location ?? 'ไม่มีข้อมูล'}</span>
        </div>
        <div className="status-card__row">
          <span>สถานะการใช้งาน</span>
          <StatusBadge
            label={equipmentStatusLabel[equipment.operational_status] ?? equipment.operational_status}
            tone={equipmentStatusTone[equipment.operational_status]}
          />
        </div>
        <button
          type="button"
          className="button button--secondary button--full-width"
          onClick={() => {
            setDialogError(null)
            setStatusDialogOpen(true)
          }}
        >
          เปลี่ยนสถานะการใช้งาน
        </button>
        {history.error && (
          <div className="form-field__error" role="alert">
            <p>แสดงประวัติการเปลี่ยนสถานะไม่ได้: {history.error.message}</p>
            {history.error.requestId && (
              <p className="state-panel__meta">รหัสอ้างอิง: {history.error.requestId}</p>
            )}
          </div>
        )}
        {history.entries && history.entries.length > 0 && (
          <details className="disclosure">
            <summary>ประวัติการเปลี่ยนสถานะ ({history.entries.length})</summary>
            <ul>
              {[...history.entries].reverse().map((entry, index) => (
                <li key={`${entry.history_id}-${index}`}>
                  {equipmentStatusLabel[entry.status] ?? entry.status} —{' '}
                  {formatThaiDateTime(entry.changed_at)}
                  {entry.changed_by ? ` โดย ${entry.changed_by}` : ''}
                  {entry.reason ? ` (${entry.reason})` : ''}
                </li>
              ))}
            </ul>
          </details>
        )}
      </Card>

      <ChangeEquipmentStatusDialog
        open={statusDialogOpen}
        currentStatus={equipment.operational_status}
        submitting={statusSubmitting}
        error={dialogError}
        onCancel={() => {
          setDialogError(null)
          setStatusDialogOpen(false)
        }}
        onSubmit={(status, reason) => void submitStatusChange(status, reason)}
      />
    </section>
  )
}
