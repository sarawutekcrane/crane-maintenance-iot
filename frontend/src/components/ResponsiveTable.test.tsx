import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ResponsiveTable } from './ResponsiveTable'

interface Row {
  id: string
  name: string
}

describe('ResponsiveTable', () => {
  it('renders each row with a data-label per cell for the mobile stacked layout', () => {
    const rows: Row[] = [{ id: '1', name: 'แถวที่หนึ่ง' }]

    render(
      <ResponsiveTable<Row>
        columns={[{ key: 'name', header: 'ชื่อรายการ', render: (row) => row.name }]}
        rows={rows}
        getRowKey={(row) => row.id}
      />,
    )

    const cell = screen.getByText('แถวที่หนึ่ง').closest('td')
    expect(cell).toHaveAttribute('data-label', 'ชื่อรายการ')
  })

  it('renders the Thai empty state when there are no rows', () => {
    render(
      <ResponsiveTable<Row>
        columns={[{ key: 'name', header: 'ชื่อรายการ', render: (row) => row.name }]}
        rows={[]}
        getRowKey={(row) => row.id}
        emptyTitle="ไม่มีข้อมูล"
      />,
    )

    expect(screen.getByText('ไม่มีข้อมูล')).toBeInTheDocument()
  })
})
