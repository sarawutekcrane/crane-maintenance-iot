import type { AttachmentInfo } from '../lib/types'

interface PhotoAttachmentFieldProps {
  id: string
  label: string
  attachments: AttachmentInfo[]
  uploading: boolean
  onAddFile: (file: File) => void
  onRemove: (attachmentId: string) => void
  altPrefix: string
}

/**
 * Core Demo Fixes, FILE ATTACHMENT UX: a single reusable photo-attachment
 * control used everywhere a form captures evidence photos (inspection
 * findings, PM task evidence, repair action photos).
 *
 * - Thai label "ถ่ายรูป / เลือกรูป" instead of the ambiguous native file
 *   input text.
 * - The native `<input type="file">` is visually hidden and triggered via
 *   its `<label>` styled as a button, so the browser's own "No file
 *   chosen" text — which would otherwise sit right next to a successfully
 *   attached photo and contradict it — is never shown at all.
 * - Attached count and thumbnail previews (with a remove action) make the
 *   attached state unambiguous.
 */
export function PhotoAttachmentField({
  id,
  label,
  attachments,
  uploading,
  onAddFile,
  onRemove,
  altPrefix,
}: PhotoAttachmentFieldProps) {
  return (
    <div className="form-field photo-attachment-field">
      <span className="photo-attachment-field__label">{label}</span>
      <label htmlFor={id} className="button button--secondary photo-attachment-field__trigger">
        ถ่ายรูป / เลือกรูป
      </label>
      <input
        id={id}
        type="file"
        accept="image/*"
        capture="environment"
        disabled={uploading}
        className="photo-attachment-field__input"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onAddFile(file)
          event.target.value = ''
        }}
      />
      <p className="photo-attachment-field__status" aria-live="polite">
        {uploading
          ? 'กำลังอัปโหลดรูปภาพ...'
          : attachments.length > 0
            ? `แนบแล้ว ${attachments.length} รูป`
            : 'ยังไม่มีรูปแนบ'}
      </p>
      {attachments.length > 0 && (
        <ul className="checklist-item-card__evidence-list">
          {attachments.map((attachment) => (
            <li key={attachment.attachment_id}>
              <img src={attachment.url} alt={`${altPrefix}`} />
              <button
                type="button"
                className="button button--secondary"
                onClick={() => onRemove(attachment.attachment_id)}
              >
                ลบรูป
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
