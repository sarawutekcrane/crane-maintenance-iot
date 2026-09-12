import type { ReactNode } from 'react'
import { EmptyState } from './EmptyState'

export interface ResponsiveTableColumn<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
}

interface ResponsiveTableProps<T> {
  columns: ResponsiveTableColumn<T>[]
  rows: T[]
  getRowKey: (row: T) => string
  emptyTitle?: string
  emptyDescription?: string
}

/**
 * Reusable responsive table/list pattern (CSS-only, see `.responsive-table`
 * in index.css): renders as an ordinary table from tablet width up, and as
 * stacked touch-friendly cards on smartphone widths — each cell keeps its
 * column header as a `data-label` so it can show a label next to the value
 * when stacked.
 */
export function ResponsiveTable<T>({
  columns,
  rows,
  getRowKey,
  emptyTitle,
  emptyDescription,
}: ResponsiveTableProps<T>) {
  if (rows.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />
  }

  return (
    <div className="responsive-table">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={getRowKey(row)}>
              {columns.map((column) => (
                <td key={column.key} data-label={column.header}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
