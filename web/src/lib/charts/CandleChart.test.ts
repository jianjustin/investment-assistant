import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/svelte'

const made = vi.hoisted(() => ({ candles: [] as any[], lines: [] as any[], chart: null as any, charts: [] as any[], chartOptions: [] as any[] }))

vi.mock('lightweight-charts', () => {
  const series = (bucket: any[]) => () => {
    const s = { setData: vi.fn(), setMarkers: vi.fn(), options: undefined as unknown }
    bucket.push(s)
    return s
  }
  return {
    createChart: vi.fn((_el: unknown, options: unknown) => {
      made.chartOptions.push(options)
      made.chart = {
        addCandlestickSeries: vi.fn((options: unknown) => { const s = series(made.candles)(); s.options = options; return s }),
        addLineSeries: vi.fn((options: unknown) => { const s = series(made.lines)(); s.options = options; return s }),
        removeSeries: vi.fn(), applyOptions: vi.fn(), remove: vi.fn(),
      }
      made.charts.push(made.chart)
      return made.chart
    }),
  }
})

import CandleChart from './CandleChart.svelte'

// Distinct sentinel values for every token the chart reads, so a test can tell which token a colour came from.
const TOKENS: Record<string, string> = {
  '--foreground': '#101010', '--muted-foreground': '#222222', '--border': '#333333', '--chart-grid': '#444444',
  '--background': '#555555', '--card': '#666666', '--up': '#00aa00', '--down': '#aa0000',
  '--chart-rule': '#0000ff', '--chart-own': '#ffaa00', '--chart-agent': '#aa00ff', '--chart-fill': '#88888833',
  '--chart-1': '#010101', '--chart-2': '#020202', '--chart-3': '#030303', '--chart-4': '#040404', '--chart-5': '#050505',
}
const setTokens = (over: Record<string, string> = {}) => {
  for (const [k, v] of Object.entries({ ...TOKENS, ...over })) document.documentElement.style.setProperty(k, v)
}
beforeEach(() => {
  made.candles.length = 0; made.lines.length = 0; made.charts.length = 0; made.chartOptions.length = 0
  setTokens()
})
afterEach(() => {
  vi.unstubAllGlobals()
  for (const k of Object.keys(TOKENS)) document.documentElement.style.removeProperty(k)
  document.documentElement.removeAttribute('data-theme')
})

it('stops observing resizes once destroyed', () => {
  const observers: { callback: () => void; disconnect: ReturnType<typeof vi.fn> }[] = []
  vi.stubGlobal('ResizeObserver', class {
    disconnect = vi.fn()
    constructor(public callback: () => void) { observers.push(this) }
    observe() {}
    unobserve() {}
  })
  const { unmount } = render(CandleChart, { data: [] })
  unmount()
  expect(observers).toHaveLength(1)
  expect(observers[0].disconnect).toHaveBeenCalled()
  // A late callback after leaving the instrument page must not touch the removed element.
  expect(() => observers[0].callback()).not.toThrow()
})

it('no annotations behaves as before', () => {
  render(CandleChart, { data: [{ time: '2026-10-20', open: 1, high: 2, low: 1, close: 2 }] as any })
  expect(made.candles).toHaveLength(1)
  expect(made.candles[0].setData).toHaveBeenCalled()
  expect(made.candles[0].setMarkers).not.toHaveBeenCalled()
  expect(made.chart.addLineSeries).not.toHaveBeenCalled()
  // empty arrays are the same as not passing them
  render(CandleChart, { data: [], markers: [], segments: [] })
  expect(made.candles[1].setMarkers).not.toHaveBeenCalled()
  expect(made.chart.addLineSeries).not.toHaveBeenCalled()
})

it('sets markers sorted', () => {
  render(CandleChart, { data: [], markers: [
    { time: '2026-10-22', position: 'belowBar', shape: 'arrowUp', text: '回踩', kind: 'candidate', refs: ['c2'] },
    { time: '2026-10-20', position: 'aboveBar', shape: 'circle', text: '异常', kind: 'candidate', refs: ['c1'] },
    { time: '2026-10-22', position: 'belowBar', shape: 'square', text: 'B 10', kind: 'trade', refs: [] },
    { time: '2026-10-21', position: 'aboveBar', shape: 'square', text: 'S 5', kind: 'trade', refs: [] },
  ] as any })
  const set = made.candles[0].setMarkers
  expect(set).toHaveBeenCalledTimes(1)
  const marks = set.mock.calls[0][0] as { time: string; text: string; position: string; shape: string; color: string }[]
  expect(marks.map(m => m.time)).toEqual(['2026-10-20', '2026-10-21', '2026-10-22', '2026-10-22'])
  expect(marks.map(m => m.text)).toEqual(['异常', 'S 5', '回踩', 'B 10'])       // stable within one day
  expect(marks[2]).toMatchObject({ position: 'belowBar', shape: 'arrowUp' })
  // real trade fills are squares: buys and sells get different colours (decided by the B / S text), candidates by shape
  const [watch, sell, candidate, buy] = marks
  expect(buy).toMatchObject({ shape: 'square' })
  expect(sell).toMatchObject({ shape: 'square' })
  expect(buy.color).not.toBe(sell.color)
  expect(candidate.color).not.toBe(buy.color)
  expect(watch.color).toBe(TOKENS['--chart-rule'])             // candidates come from the rules: the rule role colour
  expect(candidate.color).toBe(TOKENS['--chart-rule'])
  expect(marks.every(m => typeof m.color === 'string' && m.color.length > 0)).toBe(true)
})

it('draws one line series per segment', () => {
  render(CandleChart, {
    data: [],
    overlays: [{ color: TOKENS['--chart-1'], data: [{ time: '2026-10-20', value: 1 }] }],
    segments: [
      { plan_id: 'p1', kind: 'rule', label: '规则', level: 'entry_high', from: '2026-10-20', to: '2026-10-27', value: '101.50' },
      { plan_id: 'p1', kind: 'rule', label: '规则', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: '94.00' },
      { plan_id: 'p2', kind: 'agent', label: 'Agent v2', level: 'target1', from: '2026-10-22', to: '2026-10-27', value: 112 },
    ] as any,
  })
  expect(made.lines).toHaveLength(1 + 3)           // the MA overlay plus three segments
  const segmentLines = made.lines.slice(1)
  expect(segmentLines[0].setData).toHaveBeenCalledWith([
    { time: '2026-10-20', value: 101.5 }, { time: '2026-10-27', value: 101.5 }])
  expect(segmentLines[2].setData).toHaveBeenCalledWith([
    { time: '2026-10-22', value: 112 }, { time: '2026-10-27', value: 112 }])
  for (const line of segmentLines) {
    expect(line.options).toMatchObject({ lastValueVisible: false, priceLineVisible: false })
  }
  // stop is dashed (LineStyle.Dashed = 2), others are solid; same kind shares a colour
  expect(segmentLines[1].options.lineStyle).toBe(2)
  expect(segmentLines[0].options.lineStyle ?? 0).toBe(0)
  expect(segmentLines[0].options.color).toBe(segmentLines[1].options.color)
  expect(segmentLines[2].options.color).not.toBe(segmentLines[0].options.color)
})

it('draws segments of voided plans faded', () => {
  render(CandleChart, {
    data: [],
    segments: [
      { plan_id: 'p1', kind: 'rule', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 94, status: 'ok' },
      { plan_id: 'p2', kind: 'rule', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 94, status: 'invalid' },
      { plan_id: 'p3', kind: 'rule', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 94 },
    ] as any,
  })
  const [ok, voided, unmarked] = made.lines
  expect(ok.options.color).toBe(TOKENS['--chart-rule'])
  expect(unmarked.options.color).toBe(ok.options.color)            // no status reads as ok
  expect(voided.options.color).not.toBe(ok.options.color)
})

it('replaces segment lines when the segments change', async () => {
  const { rerender } = render(CandleChart, { data: [], segments: [
    { plan_id: 'p1', kind: 'rule', label: '规则', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: '94' }] as any })
  await rerender({ data: [], segments: [] })
  expect(made.chart.removeSeries).toHaveBeenCalledTimes(1)
})

const NOW_SEGMENTS = [
  { plan_id: 'p1', kind: 'rule', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 94 },
  { plan_id: 'p2', kind: 'own', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 93 },
  { plan_id: 'p3', kind: 'agent', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 95 },
] as any

it('role colors from tokens', () => {
  render(CandleChart, {
    data: [{ time: '2026-10-20', open: 1, high: 2, low: 1, close: 2 }] as any,
    segments: NOW_SEGMENTS,
    markers: [
      { time: '2026-10-20', position: 'belowBar', shape: 'square', text: 'B 10', kind: 'trade', refs: [] },
      { time: '2026-10-21', position: 'aboveBar', shape: 'square', text: 'S 5', kind: 'trade', refs: [] },
      { time: '2026-10-22', position: 'belowBar', shape: 'arrowUp', text: '回踩', kind: 'candidate', refs: [] },
    ] as any,
  })
  // price lines by plan source
  expect(made.lines.map(l => l.options.color)).toEqual([TOKENS['--chart-rule'], TOKENS['--chart-own'], TOKENS['--chart-agent']])
  // candles up / down, on the card surface
  expect(made.candles[0].options).toMatchObject({
    upColor: TOKENS['--up'], downColor: TOKENS['--down'], borderUpColor: TOKENS['--up'], wickDownColor: TOKENS['--down'] })
  expect(made.chartOptions[0].layout.background.color).toBe(TOKENS['--card'])
  // fills: buy up, sell down; candidates carry the rule colour
  const marks = made.candles[0].setMarkers.mock.calls[0][0] as { text: string; color: string }[]
  expect(marks.find(m => m.text === 'B 10')!.color).toBe(TOKENS['--up'])
  expect(marks.find(m => m.text === 'S 5')!.color).toBe(TOKENS['--down'])
  expect(marks.find(m => m.text === '回踩')!.color).toBe(TOKENS['--chart-rule'])
})

it('voided plan uses chart-fill', () => {
  render(CandleChart, { data: [], segments: [
    { plan_id: 'p1', kind: 'agent', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 94, status: 'invalid' },
    { plan_id: 'p2', kind: 'own', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 94, status: 'ok' }] as any })
  expect(made.lines[0].options.color).toBe(TOKENS['--chart-fill'])      // whatever the source, a voided plan is the fill colour
  expect(made.lines[1].options.color).toBe(TOKENS['--chart-own'])
})

it('recreates on theme change', async () => {
  const data = [{ time: '2026-10-20', open: 1, high: 2, low: 1, close: 2 }] as any
  const overlays = [{ color: '#abcdef', data: [{ time: '2026-10-20', value: 1 }] }]
  document.documentElement.setAttribute('data-theme', 'light')
  const { unmount } = render(CandleChart, { data, overlays, segments: NOW_SEGMENTS,
    markers: [{ time: '2026-10-20', position: 'aboveBar', shape: 'circle', text: '异常', kind: 'candidate', refs: [] }] as any })
  expect(made.charts).toHaveLength(1)
  const first = made.charts[0]
  setTokens({ '--chart-rule': '#111111', '--up': '#222222', '--card': '#333333' })
  document.documentElement.setAttribute('data-theme', 'dark')
  await waitFor(() => expect(made.charts).toHaveLength(2))
  expect(first.remove).toHaveBeenCalledTimes(1)
  expect(made.chartOptions[1].layout.background.color).toBe('#333333')
  const second = made.candles.at(-1)
  expect(second.options.upColor).toBe('#222222')
  // data, overlays, markers and segments are all drawn again on the new instance
  await waitFor(() => expect(second.setData).toHaveBeenCalledWith(data))
  await waitFor(() => expect(second.setMarkers).toHaveBeenCalled())
  const lines = made.lines.slice(-4)
  expect(lines.map(l => l.options.color)).toEqual(['#abcdef', '#111111', TOKENS['--chart-own'], TOKENS['--chart-agent']])
  unmount()
  expect(made.charts[1].remove).toHaveBeenCalledTimes(1)
  // after unmount a theme change must not build another chart
  document.documentElement.setAttribute('data-theme', 'light')
  await new Promise(r => setTimeout(r, 20))
  expect(made.charts).toHaveLength(2)
})

it('no hex in series options', () => {
  // every token resolves to a sentinel word: any colour that is not one of them was written in the component
  setTokens(Object.fromEntries(Object.keys(TOKENS).map(k => [k, `tok${k.replace(/-/g, '_')}`])))
  const sentinels = new Set(Object.keys(TOKENS).map(k => `tok${k.replace(/-/g, '_')}`))
  render(CandleChart, {
    data: [{ time: '2026-10-20', open: 1, high: 2, low: 1, close: 2 }] as any,
    segments: [...NOW_SEGMENTS, { plan_id: 'p4', kind: 'rule', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 1, status: 'invalid' },
               { plan_id: 'p5', kind: 'mystery', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: 1 }] as any,
    markers: [
      { time: '2026-10-20', position: 'belowBar', shape: 'square', text: 'B 10', kind: 'trade', refs: [] },
      { time: '2026-10-21', position: 'aboveBar', shape: 'square', text: 'S 5', kind: 'trade', refs: [] },
      { time: '2026-10-22', position: 'belowBar', shape: 'arrowUp', text: 'a', kind: 'candidate', refs: [] },
      { time: '2026-10-23', position: 'aboveBar', shape: 'arrowDown', text: 'b', kind: 'candidate', refs: [] },
      { time: '2026-10-24', position: 'aboveBar', shape: 'circle', text: 'c', kind: 'candidate', refs: [] },
    ] as any,
  })
  const colours: string[] = []
  const collect = (value: unknown) => {
    if (typeof value === 'string') colours.push(value)
    else if (value && typeof value === 'object') Object.values(value).forEach(collect)
  }
  collect(made.chartOptions); collect(made.candles.map(c => c.options)); collect(made.lines.map(l => l.options))
  collect(made.candles[0].setMarkers.mock.calls.flatMap((c: any[]) => c[0].map((m: any) => m.color)))
  expect(colours.length).toBeGreaterThan(10)
  expect(colours.filter(c => /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i.test(c))).toEqual([])
  expect(colours.filter(c => c.startsWith('tok') && !sentinels.has(c))).toEqual([])
})
