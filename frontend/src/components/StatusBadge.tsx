export type StatusTone = 'success' | 'warning' | 'danger' | 'neutral' | 'info'

interface StatusBadgeProps {
  label: string
  tone?: StatusTone
}

const toneClassName: Record<StatusTone, string> = {
  success: 'status-badge status-badge--success',
  warning: 'status-badge status-badge--warning',
  danger: 'status-badge status-badge--danger',
  neutral: 'status-badge status-badge--neutral',
  info: 'status-badge status-badge--info',
}

/** Generic status pill. Callers pass the already-translated Thai label. */
export function StatusBadge({ label, tone = 'neutral' }: StatusBadgeProps) {
  return <span className={toneClassName[tone]}>{label}</span>
}
