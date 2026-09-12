interface EmptyStateProps {
  title?: string
  description?: string
}

export function EmptyState({
  title = 'ไม่พบข้อมูล',
  description = 'ยังไม่มีรายการที่จะแสดงในขณะนี้',
}: EmptyStateProps) {
  return (
    <div className="state-panel state-panel--empty">
      <p className="state-panel__title">{title}</p>
      <p>{description}</p>
    </div>
  )
}
