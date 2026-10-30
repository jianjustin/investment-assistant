import { describe, it, expect, afterEach } from 'vitest'
import { readChartTheme, echartsTheme, candleOptions, roleColor, type ChartTheme } from './theme'

const VARS: Record<string, string> = {
  '--foreground': '#111111', '--muted-foreground': '#222222', '--border': '#333333', '--chart-grid': '#444444',
  '--background': '#555555', '--card': '#666666', '--up': '#00aa00', '--down': '#aa0000',
  '--chart-rule': '#0000ff', '--chart-own': '#ffaa00', '--chart-agent': '#aa00ff', '--chart-fill': '#88888833',
  '--chart-1': '#010101', '--chart-2': '#020202', '--chart-3': '#030303', '--chart-4': '#040404', '--chart-5': '#050505',
}

function setVars() {
  for (const [k, v] of Object.entries(VARS)) document.documentElement.style.setProperty(k, `  ${v}  `)
}
afterEach(() => {
  for (const k of Object.keys(VARS)) document.documentElement.style.removeProperty(k)
})

describe('chart theme', () => {
  it('reads resolved values from CSS variables', () => {
    setVars()
    const t = readChartTheme()
    expect(t).toEqual({
      foreground: '#111111', mutedForeground: '#222222', border: '#333333', grid: '#444444',
      background: '#555555', card: '#666666', up: '#00aa00', down: '#aa0000',
      rule: '#0000ff', own: '#ffaa00', agent: '#aa00ff', fill: '#88888833',
      series: ['#010101', '#020202', '#030303', '#040404', '#050505'],
    })
  })

  it('reads from a given root element', () => {
    const el = document.createElement('div')
    el.style.setProperty('--foreground', '#abcdef')
    document.body.appendChild(el)
    expect(readChartTheme(el).foreground).toBe('#abcdef')
    el.remove()
  })

  it('returns empty strings, not fallbacks, when a variable is missing', () => {
    expect(readChartTheme().up).toBe('')
  })

  it('echartsTheme uses series and text colors', () => {
    setVars()
    const t = readChartTheme()
    const theme = echartsTheme(t) as any
    expect(theme.color).toEqual(t.series)
    expect(theme.textStyle.color).toBe(t.mutedForeground)
    expect(theme.valueAxis.axisLabel.color).toBe(t.mutedForeground)
    expect(theme.valueAxis.splitLine.lineStyle.color).toBe(t.grid)
    expect(theme.categoryAxis.axisLine.lineStyle.color).toBe(t.border)
    expect(theme.tooltip.backgroundColor).toBe(t.card)
    expect(theme.tooltip.borderColor).toBe(t.border)
    expect(theme.tooltip.textStyle.color).toBe(t.foreground)
  })

  it('candleOptions colors the layout, grid and candles from the theme', () => {
    setVars()
    const t = readChartTheme()
    const { chart, series } = candleOptions(t) as any
    expect(chart.layout.textColor).toBe(t.mutedForeground)
    expect(chart.layout.background.color).toBe(t.card)
    expect(chart.grid.vertLines.color).toBe(t.grid)
    expect(chart.grid.horzLines.color).toBe(t.grid)
    expect(series).toMatchObject({
      upColor: t.up, downColor: t.down, borderUpColor: t.up, borderDownColor: t.down, wickUpColor: t.up, wickDownColor: t.down,
    })
  })

  it('roleColor maps rule/own/agent', () => {
    setVars()
    const t: ChartTheme = readChartTheme()
    expect(roleColor(t, 'rule')).toBe('#0000ff')
    expect(roleColor(t, 'own')).toBe('#ffaa00')
    expect(roleColor(t, 'agent')).toBe('#aa00ff')
  })
})
