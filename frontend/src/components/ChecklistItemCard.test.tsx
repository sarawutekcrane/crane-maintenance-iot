import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChecklistItemCard, type ChecklistItemAnswer } from './ChecklistItemCard'
import type { ChecklistItem } from '../lib/types'

const item: ChecklistItem = {
  item_id: 'ITM-V-0001',
  revision_id: 'REV-0001',
  sequence: 1,
  title: 'รายการตรวจสอบตัวอย่างที่ 1',
  inspection_point: null,
  method: null,
  standard: null,
  instruction: null,
  frequency: null,
  required_photo_on_fail: true,
  required_remark_on_fail: true,
  is_critical: false,
  reference_image: null,
}

const emptyAnswer: ChecklistItemAnswer = { result: null, remark: '', evidence: [] }

describe('ChecklistItemCard', () => {
  // R3 (contract §4, deliberate test migration): the four R3 results replace
  // PASS/FAIL/N/A; legacy NA is never offered for new entry.
  it('renders the four R3 results as large touch controls with Thai labels', () => {
    render(
      <ChecklistItemCard
        item={item}
        answer={emptyAnswer}
        uploading={false}
        onResultChange={vi.fn()}
        onRemarkChange={vi.fn()}
        onAddEvidence={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />,
    )

    expect(screen.getAllByRole('radio').map((r) => r.textContent)).toEqual([
      'ปกติ',
      'ผิดปกติ',
      'ใช้งานได้รอการแก้ไข',
      'ไม่มีอุปกรณ์ติดตั้ง',
    ])
    expect(screen.queryByRole('radio', { name: /ไม่เกี่ยวข้อง/ })).not.toBeInTheDocument()
    // Remark/evidence controls must not appear until an abnormal result is selected.
    expect(screen.queryByLabelText(/หมายเหตุ/)).not.toBeInTheDocument()
  })

  it('calls onResultChange when a result button is tapped', async () => {
    const user = userEvent.setup()
    const onResultChange = vi.fn()
    render(
      <ChecklistItemCard
        item={item}
        answer={emptyAnswer}
        uploading={false}
        onResultChange={onResultChange}
        onRemarkChange={vi.fn()}
        onAddEvidence={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('radio', { name: 'ปกติ' }))
    expect(onResultChange).toHaveBeenCalledWith('PASS')
    await user.click(screen.getByRole('radio', { name: 'ใช้งานได้รอการแก้ไข' }))
    expect(onResultChange).toHaveBeenCalledWith('USABLE_PENDING_REPAIR')
  })

  it.each(['FAIL', 'USABLE_PENDING_REPAIR'] as const)(
    'R3-15: %s shows a required remark and an optional photo, whatever the old per-item flags say',
    (result) => {
    render(
      <ChecklistItemCard
        item={item}
        answer={{ result, remark: '', evidence: [] }}
        uploading={false}
        onResultChange={vi.fn()}
        onRemarkChange={vi.fn()}
        onAddEvidence={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />,
    )

    expect(screen.getByLabelText('หมายเหตุ (จำเป็น)')).toBeInTheDocument()
    expect(screen.getByText('รูปถ่ายหลักฐาน (ถ้ามี)')).toBeInTheDocument()
  })

  it('NOT_INSTALLED shows the no-exemption note and no remark field', () => {
    render(
      <ChecklistItemCard
        item={item}
        answer={{ result: 'NOT_INSTALLED', remark: '', evidence: [] }}
        uploading={false}
        onResultChange={vi.fn()}
        onRemarkChange={vi.fn()}
        onAddEvidence={vi.fn()}
        onRemoveEvidence={vi.fn()}
        dueReason="FIRST_WEEKLY"
      />,
    )

    expect(screen.getByTestId('not-installed-note')).toHaveTextContent('ไม่ใช่การยกเว้นข้อกำหนดด้านความปลอดภัย')
    expect(screen.queryByLabelText(/หมายเหตุ/)).not.toBeInTheDocument()
    expect(screen.getByTestId('inspection-due-reason')).toHaveTextContent('ทุก 7 วัน (ตรวจครั้งแรก)')
  })

  it('renders the reference image separately from evidence photos', () => {
    render(
      <ChecklistItemCard
        item={{
          ...item,
          reference_image: {
            attachment_id: 'ATT-REF-0001',
            purpose: 'CHECKLIST_REFERENCE_IMAGE',
            filename: 'ref.jpg',
            content_type: 'image/jpeg',
            size_bytes: 10,
            uploaded_at: '2026-01-01T00:00:00Z',
            uploaded_by: null,
            url: '/api/v1/attachments/ATT-REF-0001/file',
          },
        }}
        answer={{
          result: 'FAIL',
          remark: 'พบปัญหา',
          evidence: [
            {
              attachment_id: 'ATT-EVID-0001',
              purpose: 'INSPECTION_EVIDENCE',
              filename: 'evidence.jpg',
              content_type: 'image/jpeg',
              size_bytes: 20,
              uploaded_at: '2026-01-01T00:00:00Z',
              uploaded_by: 'dev-user',
              url: '/api/v1/attachments/ATT-EVID-0001/file',
            },
          ],
        }}
        uploading={false}
        onResultChange={vi.fn()}
        onRemarkChange={vi.fn()}
        onAddEvidence={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />,
    )

    const referenceImg = screen.getByAltText(`ภาพอ้างอิงสำหรับ ${item.title}`)
    const evidenceImg = screen.getByAltText(`หลักฐานสำหรับ ${item.title}`)
    expect(referenceImg).toHaveAttribute('src', '/api/v1/attachments/ATT-REF-0001/file')
    expect(evidenceImg).toHaveAttribute('src', '/api/v1/attachments/ATT-EVID-0001/file')
  })
})
