import { Card } from './Card'

interface PermissionDeniedStateProps {
  message?: string
}

export function PermissionDeniedState({
  message = 'คุณไม่มีสิทธิ์เข้าถึงหน้านี้ กรุณาติดต่อผู้ดูแลระบบ',
}: PermissionDeniedStateProps) {
  return (
    <Card className="state-panel state-panel--denied">
      <div role="alert">
        <p className="state-panel__title">ไม่มีสิทธิ์เข้าถึง</p>
        <p>{message}</p>
      </div>
    </Card>
  )
}
