import type { Bar } from './api'

export function toLineData(bars: Bar[], ma: (number | null)[]): { time: string; value: number }[] {
  const out: { time: string; value: number }[] = []
  for (let i = 0; i < bars.length; i++) {
    const v = ma[i]
    if (v != null) out.push({ time: bars[i].date, value: v })
  }
  return out
}
