import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Technicals from './Technicals.svelte'
import * as api from '../lib/api'

// CandleChart 依赖 canvas，jsdom 下 mock 掉
vi.mock('../lib/charts/CandleChart.svelte', async () => {
  // @ts-ignore – stub has no declaration file; only used in tests
  const Stub = (await import('./__stub__.svelte')).default
  return { default: Stub }
})

describe('Technicals page', () => {
  it('renders ticker tabs and stat cards for the active ticker', async () => {
    vi.spyOn(api, 'getTickerTrends').mockResolvedValue({
      rows: [{ ticker: 'AAPL', relative_strength_spy: 0.03, trend_state: 'uptrend', attention_level: 'high' }],
    } as any)
    vi.spyOn(api, 'getTickerOhlcv').mockResolvedValue({
      ticker: 'AAPL',
      bars: [
        { date: '2026-06-01', open: 100, high: 101, low: 99, close: 100, volume: 1000 },
        { date: '2026-06-02', open: 100, high: 103, low: 100, close: 102, volume: 3000 },
      ],
      ma20: [null, 101], ma50: [null, 101], ma200: [null, 100],
    } as any)
    render(Technicals, { props: { sub: 'AAPL' } })
    expect(await screen.findByRole('tab', { name: /AAPL/ })).toBeTruthy()
    const cards = await screen.findAllByTestId('stat-card')
    expect(cards.length).toBe(6)
  })
})
