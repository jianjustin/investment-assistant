import type { Bar } from './api'

export function toLineData(bars: Bar[], ma: (number | null)[]): { time: string; value: number }[] {
  const out: { time: string; value: number }[] = []
  for (let i = 0; i < bars.length; i++) {
    const v = ma[i]
    if (v != null) out.push({ time: bars[i].date, value: v })
  }
  return out
}

export type Card = { label: string; value: string; tone: 'up' | 'down' | 'flat' }

function pct(x: number): string {
  const sign = x > 0 ? '+' : ''
  return `${sign}${(x * 100).toFixed(1)}%`
}
function tone(x: number): 'up' | 'down' | 'flat' {
  return x > 0 ? 'up' : x < 0 ? 'down' : 'flat'
}

export function deriveCards(
  bars: Bar[],
  ma200: (number | null)[],
  snapshot?: { relative_strength_spy?: number | null },
): Card[] {
  const last = bars[bars.length - 1]
  const prev = bars[bars.length - 2]
  const change = prev ? last.close / prev.close - 1 : 0
  // 取最后 20 根（不包括当前）的平均 volume
  const prev20 = bars.length > 1 ? bars.slice(-21, -1) : []
  const vol20 = prev20.length > 0 ? prev20.reduce((s, b) => s + b.volume, 0) / prev20.length : 1
  const volRatio = vol20 ? last.volume / vol20 : 0
  const ma200Last = ma200[ma200.length - 1]
  const dist200 = ma200Last ? last.close / ma200Last - 1 : null
  const rs = snapshot?.relative_strength_spy

  return [
    { label: '收盘', value: last.close.toFixed(2), tone: 'flat' },
    { label: '开盘', value: last.open.toFixed(2), tone: 'flat' },
    { label: '涨跌', value: pct(change), tone: tone(change) },
    { label: '量比', value: `${volRatio.toFixed(1)}×`, tone: volRatio >= 1 ? 'up' : 'down' },
    { label: 'RS·SPY', value: rs == null ? '—' : (rs > 0 ? '+' : '') + rs.toFixed(3), tone: tone(rs ?? 0) },
    { label: '距200线', value: dist200 == null ? '—' : pct(dist200), tone: tone(dist200 ?? 0) },
  ]
}
