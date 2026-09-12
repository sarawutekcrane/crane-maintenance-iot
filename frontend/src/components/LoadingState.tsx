interface LoadingStateProps {
  message?: string
}

export function LoadingState({ message = 'กำลังโหลดข้อมูล...' }: LoadingStateProps) {
  return (
    <div className="state-panel state-panel--loading" role="status" aria-live="polite">
      <span className="state-panel__spinner" aria-hidden="true" />
      <p>{message}</p>
    </div>
  )
}
