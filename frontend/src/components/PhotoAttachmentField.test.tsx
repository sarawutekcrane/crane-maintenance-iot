import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AttachmentInfo } from '../lib/types'
import { PhotoAttachmentField } from './PhotoAttachmentField'

// R2 Batch R2f-h4 B5 responsive fix — the CSS-only correction must leave the
// component's behaviour untouched (layout itself is covered by
// e2e/photo-attachment-responsive.spec.ts in a real browser).

const ATTACHED = [{ attachment_id: 'ATT-SYN-1', url: '/files/ATT-SYN-1.png' }] as unknown as AttachmentInfo[]

function renderField(props: Partial<Parameters<typeof PhotoAttachmentField>[0]> = {}) {
  const onAddFile = vi.fn()
  const onRemove = vi.fn()
  render(
    <PhotoAttachmentField
      id="syn-photo"
      label="แนบรูปถ่าย (ถ้ามี)"
      attachments={[]}
      uploading={false}
      onAddFile={onAddFile}
      onRemove={onRemove}
      altPrefix="รูปแนบทดสอบ"
      {...props}
    />,
  )
  return { onAddFile, onRemove }
}

describe('PhotoAttachmentField', () => {
  it('keeps the native file input, reachable through its labelled trigger, with unchanged accept / capture', () => {
    renderField()
    const input = screen.getByLabelText('ถ่ายรูป / เลือกรูป')
    expect(input).toHaveAttribute('type', 'file')
    expect(input).toHaveAttribute('id', 'syn-photo')
    expect(input).toHaveAttribute('accept', 'image/*')
    expect(input).toHaveAttribute('capture', 'environment')
    expect(input).toHaveClass('photo-attachment-field__input')
    expect(input).toBeEnabled()
    expect(input.closest('.photo-attachment-field')).not.toBeNull() // the scoped CSS rule applies
    expect(screen.getByText('ยังไม่มีรูปแนบ')).toBeInTheDocument()
  })

  it('hands the chosen file to onAddFile exactly once and resets the input for the next choice', async () => {
    const { onAddFile } = renderField()
    const input = screen.getByLabelText('ถ่ายรูป / เลือกรูป') as HTMLInputElement
    const file = new File(['x'], 'evidence.png', { type: 'image/png' })
    await userEvent.upload(input, file)
    expect(onAddFile).toHaveBeenCalledTimes(1)
    expect(onAddFile).toHaveBeenCalledWith(file)
    expect(input.value).toBe('')
  })

  it('ignores an empty selection', () => {
    const { onAddFile } = renderField()
    fireEvent.change(screen.getByLabelText('ถ่ายรูป / เลือกรูป'), { target: { files: [] } })
    expect(onAddFile).not.toHaveBeenCalled()
  })

  it('shows the uploading state and disables the input while uploading', () => {
    renderField({ uploading: true })
    expect(screen.getByText('กำลังอัปโหลดรูปภาพ...')).toBeInTheDocument()
    expect(screen.getByLabelText('ถ่ายรูป / เลือกรูป')).toBeDisabled()
  })

  it('shows the attached count and thumbnails, and removes by attachment id', async () => {
    const { onRemove } = renderField({ attachments: ATTACHED })
    expect(screen.getByText('แนบแล้ว 1 รูป')).toBeInTheDocument()
    expect(screen.getByAltText('รูปแนบทดสอบ')).toHaveAttribute('src', '/files/ATT-SYN-1.png')
    await userEvent.click(screen.getByRole('button', { name: 'ลบรูป' }))
    expect(onRemove).toHaveBeenCalledWith('ATT-SYN-1')
  })
})
