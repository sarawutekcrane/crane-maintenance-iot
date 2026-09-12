interface PermissionDeniedStateProps {
  message?: string
}

export function PermissionDeniedState({
  message = 'คุณไม่มีสิทธิ์เข้าถึงหน้านี้ กรุณาติดต่อผู้ดูแลระบบ',
}: PermissionDeniedStateProps) {
  return (
    <div className="state-panel state-panel--denied" role="alert">
      <p className="state-panel__title">ไม่มีสิทธิ์เข้าถึง</p>
      <p>{message}</p>
    </div>
  )
}
