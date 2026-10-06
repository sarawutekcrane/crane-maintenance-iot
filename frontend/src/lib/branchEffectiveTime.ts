/** Phase 7 Batch 7O2c — Bangkok wall-clock helpers for the branch dialog's
 * effective time (contract Final Rev2 §5.2: a DATE is 00:00 Asia/Bangkok; a
 * DATETIME is sent with an explicit offset, whole seconds only). */
const BANGKOK_MS = 7 * 60 * 60 * 1000

/** A stored instant as Bangkok wall-clock text: 'YYYY-MM-DDTHH:mm:ss'. */
export function bangkokWallClock(iso: string | null): string {
  if (iso === null) return ''
  const at = Date.parse(iso)
  return Number.isNaN(at) ? '' : new Date(at + BANGKOK_MS).toISOString().slice(0, 19)
}

/** datetime-local text (with or without seconds) → ISO 8601 with +07:00. */
export function bangkokDateTimeToIso(local: string): string {
  return `${local.length === 16 ? `${local}:00` : local}+07:00`
}
