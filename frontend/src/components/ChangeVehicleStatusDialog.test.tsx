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

    // R5 (deliberate migration): the third argument is the optional effective time; blank = now (null).
    expect(onSubmit).toHaveBeenCalledWith('MAINTENANCE', 'เข้าซ่อมตามแผน', null)
  })

  it('R5: submits an explicit effective time as an Asia/Bangkok instant', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<ChangeVehicleStatusDialog open currentStatus="WORKING" submitting={false} onCancel={vi.fn()} onSubmit={onSubmit} />)
    await user.selectOptions(screen.getByLabelText('สถานะใหม่'), 'OUT_OF_SERVICE')
    await user.type(screen.getByLabelText('เวลาที่มีผลจริง (ไม่บังคับ — เว้นว่าง = ตอนนี้)'), '2026-11-02T08:30')
    await user.click(screen.getByRole('button', { name: 'ยืนยันเปลี่ยนสถานะ' }))
    expect(onSubmit).toHaveBeenCalledWith('OUT_OF_SERVICE', '', '2026-11-02T08:30:00+07:00')
  })

  it('R5: shows the server refusal inside the dialog', () => {
    render(
      <ChangeVehicleStatusDialog open currentStatus="WORKING" submitting={false} error="คุณไม่มีสิทธิ์เปลี่ยนสถานะรถ" onCancel={vi.fn()} onSubmit={vi.fn()} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('คุณไม่มีสิทธิ์เปลี่ยนสถานะรถ')
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
