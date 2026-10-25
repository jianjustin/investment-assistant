import { afterEach, expect, it, vi } from 'vitest'
import { render } from '@testing-library/svelte'

vi.mock('lightweight-charts', () => {
  const series = () => ({ setData: vi.fn() })
  return {
    createChart: vi.fn(() => ({
      addCandlestickSeries: vi.fn(series), addLineSeries: vi.fn(series),
      removeSeries: vi.fn(), applyOptions: vi.fn(), remove: vi.fn(),
    })),
  }
})

import CandleChart from './CandleChart.svelte'

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
