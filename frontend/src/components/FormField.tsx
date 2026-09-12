import type { ReactNode } from 'react'

interface FormFieldProps {
  label: string
  htmlFor: string
  children: ReactNode
  hint?: string
  error?: string
}

/**
 * Reusable responsive form field pattern: label above a full-width,
 * touch-sized (min 44px) input. Later phases (inspection, PM, repair
 * forms, ...) compose real inputs inside this wrapper instead of
 * hand-rolling form markup per page. Combine multiple fields inside a
 * `.form-grid` (optionally `.form-grid--two-column` from tablet width up).
 */
export function FormField({ label, htmlFor, children, hint, error }: FormFieldProps) {
  return (
    <div className="form-field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && <p className="form-field__hint">{hint}</p>}
      {error && (
        <p className="form-field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
