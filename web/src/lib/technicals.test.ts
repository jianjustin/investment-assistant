import { describe, it, expect } from 'vitest'
import { toLineData } from './technicals'

const bars = Array.from({ length: 21 }, (_, i) => ({
  date: `2026-06-${String(i + 1).padStart(2, '0')}`,
  open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i, volume: 1000,
}))
bars[20] = { ...bars[20], volume: 3000, close: 200 } // 最后一日放量、拉高

describe('technicals helpers', () => {
  it('toLineData skips nulls and keeps time/value', () => {
    const ma = bars.map((_, i) => (i < 2 ? null : 100 + i))
    const line = toLineData(bars, ma)
    expect(line.length).toBe(19)
    expect(line[0]).toEqual({ time: '2026-06-03', value: 102 })
  })

})
