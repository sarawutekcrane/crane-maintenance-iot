import { Card } from './Card'

interface ErrorStateProps {
  title?: string
  message: string
  requestId?: string | null
  /** Optional backend error code, shown verbatim next to the message. */
  code?: string | null
  onRetry?: () => void
}

export function ErrorState({
  title = 'เกิดข้อผิดพลาด',
  message,
  requestId,
  code,
  onRetry,
}: ErrorStateProps) {
  return (
    <Card className="state-panel state-panel--error">
      <div role="alert">
        <p className="state-panel__title">{title}</p>
        <p>{message}</p>
        {code && <p className="state-panel__meta">รหัสข้อผิดพลาด: {code}</p>}
        {requestId && <p className="state-panel__meta">รหัสอ้างอิง: {requestId}</p>}
      </div>
      {onRetry && (
        <button
          type="button"
          className="button button--secondary button--full-width"
          onClick={onRetry}
        >
          ลองใหม่อีกครั้ง
        </button>
      )}
    </Card>
  )
}
