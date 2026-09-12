import { Card } from './Card'

interface ErrorStateProps {
  title?: string
  message: string
  requestId?: string | null
  onRetry?: () => void
}

export function ErrorState({
  title = 'เกิดข้อผิดพลาด',
  message,
  requestId,
  onRetry,
}: ErrorStateProps) {
  return (
    <Card className="state-panel state-panel--error">
      <div role="alert">
        <p className="state-panel__title">{title}</p>
        <p>{message}</p>
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
