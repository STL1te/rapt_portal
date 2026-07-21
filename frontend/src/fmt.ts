export const grav = (n: number | null) => (n == null ? '—' : n.toFixed(1))

// density conversions from RAPT "points" (e.g. 1048.4 -> SG 1.0484)
export const sg = (points: number | null) =>
  points == null ? '—' : (points / 1000).toFixed(3)

export const brix = (points: number | null) => {
  if (points == null) return '—'
  const s = points / 1000
  const b = 182.4601 * s ** 3 - 775.6821 * s ** 2 + 1262.7794 * s - 669.5622
  return b.toFixed(1)
}
export const temp = (n: number | null) => (n == null ? '—' : `${n.toFixed(1)}°C`)
export const pct = (n: number | null) => (n == null ? '—' : `${Math.round(n)}%`)
export const dbm = (n: number | null) => (n == null ? '—' : `${Math.round(n)} dBm`)
export const date = (s: string | null) =>
  s ? new Date(s).toLocaleDateString() : '—'

export function stepLen(seconds: number | null): string {
  if (seconds == null) return '—'
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} мин`
  return `${Math.floor(m / 60)} ч ${m % 60} мин`
}

export function duration(start: string | null, end: string | null): string {
  if (!start) return '—'
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime()
  const days = Math.floor(ms / 86400000)
  const hours = Math.floor((ms % 86400000) / 3600000)
  return `${days}d ${hours}h`
}
