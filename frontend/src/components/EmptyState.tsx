import { Card } from './Card'

interface EmptyStateProps {
  title?: string
  description?: string
}

export function EmptyState({
  title = 'ไม่พบข้อมูล',
  description = 'ยังไม่มีรายการที่จะแสดงในขณะนี้',
}: EmptyStateProps) {
  return (
    <Card className="state-panel">
      <p className="state-panel__title">{title}</p>
      <p>{description}</p>
    </Card>
  )
}
