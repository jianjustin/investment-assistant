import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { render } from '@testing-library/svelte'

const made = vi.hoisted(() => ({ candles: [] as any[], lines: [] as any[], chart: null as any }))

vi.mock('lightweight-charts', () => {
  const series = (bucket: any[]) => () => {
    const s = { setData: vi.fn(), setMarkers: vi.fn(), options: undefined as unknown }
    bucket.push(s)
    return s
  }
  return {
    createChart: vi.fn(() => {
      made.chart = {
        addCandlestickSeries: vi.fn(series(made.candles)),
        addLineSeries: vi.fn((options: unknown) => { const s = series(made.lines)(); s.options = options; return s }),
        removeSeries: vi.fn(), applyOptions: vi.fn(), remove: vi.fn(),
      }
      return made.chart
    }),
  }
})

import CandleChart from './CandleChart.svelte'

beforeEach(() => { made.candles.length = 0; made.lines.length = 0 })
afterEach(() => vi.unstubAllGlobals())

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
    { time: '2026-10-22', position: 'belowBar', shape: 'arrowUp', text: 'B 10', kind: 'trade', refs: [] },
    { time: '2026-10-21', position: 'aboveBar', shape: 'arrowDown', text: 'S 5', kind: 'trade', refs: [] },
  ] as any })
  const set = made.candles[0].setMarkers
  expect(set).toHaveBeenCalledTimes(1)
  const marks = set.mock.calls[0][0] as { time: string; text: string; position: string; shape: string; color: string }[]
  expect(marks.map(m => m.time)).toEqual(['2026-10-20', '2026-10-21', '2026-10-22', '2026-10-22'])
  expect(marks.map(m => m.text)).toEqual(['异常', 'S 5', '回踩', 'B 10'])       // stable within one day
  expect(marks[2]).toMatchObject({ position: 'belowBar', shape: 'arrowUp' })
  expect(marks.every(m => typeof m.color === 'string' && m.color.length > 0)).toBe(true)
})

it('draws one line series per segment', () => {
  render(CandleChart, {
    data: [],
    overlays: [{ color: '#22c55e', data: [{ time: '2026-10-20', value: 1 }] }],
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

it('replaces segment lines when the segments change', async () => {
  const { rerender } = render(CandleChart, { data: [], segments: [
    { plan_id: 'p1', kind: 'rule', label: '规则', level: 'stop', from: '2026-10-20', to: '2026-10-27', value: '94' }] as any })
  await rerender({ data: [], segments: [] })
  expect(made.chart.removeSeries).toHaveBeenCalledTimes(1)
})
