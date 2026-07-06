import { describe, it, expect } from 'vitest'
import { toLineData, deriveCards } from './technicals'

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

  it('deriveCards computes change/volume-ratio/dist200', () => {
    const ma200 = bars.map(() => 100) // 距200线 = 200/100 - 1 = +100%
    const cards = deriveCards(bars, ma200, { relative_strength_spy: 0.031 })
    expect(cards.map((c) => c.label)).toEqual(['收盘', '开盘', '涨跌', '量比', 'RS·SPY', '距200线'])
    expect(cards[0].value).toBe('200.00')      // 收盘
    expect(cards[2].tone).toBe('up')           // 涨跌为正
    expect(cards[3].value).toBe('3.0×')        // 量比 = 3000 / 1000
    expect(cards[5].value).toBe('+100.0%')     // 距200线
  })

  it('deriveCards shows dash when snapshot missing RS', () => {
    const ma200 = bars.map(() => 100)
    const cards = deriveCards(bars, ma200, undefined)
    expect(cards[4].value).toBe('—')
  })
})
