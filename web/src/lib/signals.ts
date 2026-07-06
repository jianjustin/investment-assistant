export type Status = 'green' | 'yellow' | 'red' | 'none'
export type SignalRow = { signal_date: string; market_status: string }
export type DayCell = { date: string; status: Status }

export const STATUS_COLORS: Record<Status, string> = {
  green: '#22c55e',
  yellow: '#eab308',
  red: '#ef4444',
  none: '#2a2a2a',
}

function normalize(status: string): Status {
  const s = (status ?? '').toLowerCase()
  return s === 'green' || s === 'yellow' || s === 'red' ? s : 'none'
}

export function buildDayCells(rows: SignalRow[], days = 30): DayCell[] {
  const asc = [...rows].sort((a, b) => a.signal_date.localeCompare(b.signal_date))
  const cells = asc.map((r) => ({ date: r.signal_date, status: normalize(r.market_status) }))
  return days && cells.length > days ? cells.slice(cells.length - days) : cells
}

export function countStatuses(rows: SignalRow[]): { green: number; yellow: number; red: number } {
  const out = { green: 0, yellow: 0, red: 0 }
  for (const r of rows) {
    const s = normalize(r.market_status)
    if (s !== 'none') out[s] += 1
  }
  return out
}
