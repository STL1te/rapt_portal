import type { Batch } from '@/types'

// Batch dates are calendar days (YYYY-MM-DD): parse them as local midnight, not UTC.
export const day = (s: string) => new Date(`${s}T00:00`).getTime()
export const dayFmt = (s: string | null) => (s ? new Date(day(s)).toLocaleDateString() : '—')

export function today(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export type BatchStatus = 'carbonating' | 'conditioning' | 'ready' | 'finished'

export const STATUS: Record<BatchStatus, { label: string; color: string }> = {
  carbonating: { label: 'газация', color: '#e0a93a' },
  conditioning: { label: 'созревание', color: '#4ea1ff' },
  ready: { label: 'готово', color: '#35c28a' },
  finished: { label: 'завершена', color: '#8a92a0' },
}

// ISO day strings compare correctly as plain strings.
export function batchStatus(b: Batch, now = today()): BatchStatus {
  if (b.finished_on) return 'finished'
  if (now < b.carbonation_until) return 'carbonating'
  if (now < b.conditioning_until) return 'conditioning'
  return 'ready'
}

/** Phase segments for the calendar: planned phases ahead, cut at the day the batch ended. */
export function phases(b: Batch, now = today()) {
  const end = b.finished_on ?? (now > b.conditioning_until ? now : b.conditioning_until)
  const all = [
    ['carbonating', b.bottled_on, b.carbonation_until],
    ['conditioning', b.carbonation_until, b.conditioning_until],
    ['ready', b.conditioning_until, end],
  ] as const
  return all
    .map(([status, from, to]) => ({ status, from, to: to < end ? to : end }))
    .filter((p) => p.from < p.to)
}
