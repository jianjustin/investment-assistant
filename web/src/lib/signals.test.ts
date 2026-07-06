import { describe, it, expect } from 'vitest'
import { buildDayCells, countStatuses, STATUS_COLORS } from './signals'

const rows = [
  { signal_date: '2026-07-03', market_status: 'green' },
  { signal_date: '2026-07-02', market_status: 'RED' },
  { signal_date: '2026-07-01', market_status: 'weird' },
]

describe('signals helpers', () => {
  it('buildDayCells sorts ascending and normalizes status', () => {
    const cells = buildDayCells(rows)
    expect(cells.map((c) => c.date)).toEqual(['2026-07-01', '2026-07-02', '2026-07-03'])
    expect(cells.map((c) => c.status)).toEqual(['none', 'red', 'green'])
  })

  it('buildDayCells caps to last N days', () => {
    expect(buildDayCells(rows, 2).length).toBe(2)
    expect(buildDayCells(rows, 2)[0].date).toBe('2026-07-02')
  })

  it('countStatuses tallies case-insensitively', () => {
    expect(countStatuses(rows)).toEqual({ green: 1, yellow: 0, red: 1 })
  })

  it('exposes status colors', () => {
    expect(STATUS_COLORS.green).toBe('#22c55e')
    expect(STATUS_COLORS.none).toBe('#2a2a2a')
  })
})
