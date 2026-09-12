import { Card } from './Card'

interface LoadingStateProps {
  message?: string
}

export function LoadingState({ message = 'กำลังโหลดข้อมูล...' }: LoadingStateProps) {
  return (
    <Card className="state-panel state-panel--loading">
      <div role="status" aria-live="polite" className="state-panel__inline">
        <span className="state-panel__spinner" aria-hidden="true" />
        <p>{message}</p>
      </div>
    </Card>
  )
}
