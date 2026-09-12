import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
}

/** Reusable mobile-friendly content card used across state panels and pages. */
export function Card({ children, className }: CardProps) {
  return <div className={className ? `card ${className}` : 'card'}>{children}</div>
}
