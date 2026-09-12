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
  it('renders PASS/FAIL/N/A as large touch controls with Thai labels', () => {
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

    expect(screen.getByRole('radio', { name: 'ผ่าน' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'ไม่ผ่าน' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'ไม่เกี่ยวข้อง' })).toBeInTheDocument()
    // Remark/evidence controls must not appear until FAIL is selected.
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

    await user.click(screen.getByRole('radio', { name: 'ผ่าน' }))
    expect(onResultChange).toHaveBeenCalledWith('PASS')
  })

  it('shows remark and required-photo controls immediately once FAIL is selected', () => {
    render(
      <ChecklistItemCard
        item={item}
        answer={{ result: 'FAIL', remark: '', evidence: [] }}
        uploading={false}
        onResultChange={vi.fn()}
        onRemarkChange={vi.fn()}
        onAddEvidence={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />,
    )

    expect(screen.getByLabelText(/หมายเหตุ/)).toBeInTheDocument()
    expect(screen.getByText(/รูปถ่ายหลักฐาน \(จำเป็น\)/)).toBeInTheDocument()
  })

  it('labels remark and photo as optional when the item does not require them', () => {
    render(
      <ChecklistItemCard
        item={{ ...item, required_remark_on_fail: false, required_photo_on_fail: false }}
        answer={{ result: 'FAIL', remark: '', evidence: [] }}
        uploading={false}
        onResultChange={vi.fn()}
        onRemarkChange={vi.fn()}
        onAddEvidence={vi.fn()}
        onRemoveEvidence={vi.fn()}
      />,
    )

    expect(screen.getByLabelText('หมายเหตุ (ถ้ามี)')).toBeInTheDocument()
    expect(screen.getByText('รูปถ่ายหลักฐาน (ถ้ามี)')).toBeInTheDocument()
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
