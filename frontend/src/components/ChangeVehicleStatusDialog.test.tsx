import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChangeVehicleStatusDialog } from './ChangeVehicleStatusDialog'

describe('ChangeVehicleStatusDialog', () => {
  it('submits the selected status and note', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(
      <ChangeVehicleStatusDialog
        open
        currentStatus="WORKING"
        submitting={false}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    )

    await user.selectOptions(screen.getByLabelText('สถานะใหม่'), 'MAINTENANCE')
    await user.type(screen.getByLabelText('หมายเหตุ (ไม่บังคับ)'), 'เข้าซ่อมตามแผน')
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))

    expect(onSubmit).toHaveBeenCalledWith('MAINTENANCE', 'เข้าซ่อมตามแผน')
  })

  it('renders nothing when closed', () => {
    render(
      <ChangeVehicleStatusDialog
        open={false}
        currentStatus="WORKING"
        submitting={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    )
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
})
