import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { VehicleStatusEvent } from '../lib/types'
import { VehicleStatusTimeCorrectionDialog } from './VehicleStatusTimeCorrectionDialog'

// R5 OD-3 — effective-time correction of a vehicle status event. Synthetic data only.

const EVENT: VehicleStatusEvent = {
  history_id: 'STH-0002', status: 'MAINTENANCE', effective_at: '2026-11-01T01:00:00Z', effective_source: 'EXPLICIT',
  recorded_at: '2026-11-03T01:00:00Z', changed_by: 'm', note: null, corrections: [],
}

describe('VehicleStatusTimeCorrectionDialog', () => {
  it('renders nothing without an event', () => {
    const { container } = render(<VehicleStatusTimeCorrectionDialog event={null} submitting={false} error={null} onCancel={vi.fn()} onSubmit={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('requires a new time and a reason, then submits an Asia/Bangkok instant', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<VehicleStatusTimeCorrectionDialog event={EVENT} submitting={false} error={null} onCancel={vi.fn()} onSubmit={onSubmit} />)
    expect(screen.getByRole('dialog')).toHaveTextContent('ซ่อมบำรุง')
    await user.click(screen.getByRole('button', { name: 'บันทึกการแก้ไข' }))
    expect(screen.getByRole('alert')).toHaveTextContent('กรุณาระบุเวลาที่มีผลใหม่')
    await user.type(screen.getByLabelText('เวลาที่มีผลใหม่ (เวลาประเทศไทย)'), '2026-11-01T07:30')
    await user.click(screen.getByRole('button', { name: 'บันทึกการแก้ไข' }))
    expect(screen.getByRole('alert')).toHaveTextContent('กรุณาระบุเหตุผลการแก้ไข')
    expect(onSubmit).not.toHaveBeenCalled()
    await user.type(screen.getByLabelText('เหตุผลการแก้ไข'), 'เวลาจริงตามใบสั่งงาน')
    await user.click(screen.getByRole('button', { name: 'บันทึกการแก้ไข' }))
    expect(onSubmit).toHaveBeenCalledWith('2026-11-01T07:30:00+07:00', 'เวลาจริงตามใบสั่งงาน')
  })

  it('shows the server refusal', () => {
    render(<VehicleStatusTimeCorrectionDialog event={EVENT} submitting={false} error="เวลาที่มีผลต้องอยู่ระหว่างสถานะข้างเคียง" onCancel={vi.fn()} onSubmit={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('เวลาที่มีผลต้องอยู่ระหว่างสถานะข้างเคียง')
  })
})
