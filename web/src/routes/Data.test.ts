import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Data from './Data.svelte'
import * as api from '../lib/api'

describe('Data signals Tab', () => {
  it('signals tab shows dot matrix and ratio', async () => {
    vi.spyOn(api, 'getMarketSignals').mockResolvedValue({
      rows: [
        { signal_date: '2026-07-01', market_status: 'green', spy_close: 1, vix_close: 1, spy_above_200ma: true },
        { signal_date: '2026-07-02', market_status: 'red', spy_close: 1, vix_close: 22, spy_above_200ma: false },
      ],
    } as any)
    vi.spyOn(api, 'getMarketSignalsTrend').mockResolvedValue({
      window: 30, judgement: 'risk_on', summary: '偏积极', status_counts: { green: 1, yellow: 0, red: 1 },
    } as any)
    vi.spyOn(api, 'getFilingRecords').mockResolvedValue({ records: [], tickers: [], degraded: false } as any)
    render(Data, { props: { sub: 'signals' } })
    const dots = await screen.findAllByTestId('dot')
    expect(dots.length).toBe(2)
  })
})

describe('Data 财报 Tab', () => {
  it('renders filing records with download link', async () => {
    vi.spyOn(api, 'getMarketSignals').mockResolvedValue({ rows: [] } as any)
    vi.spyOn(api, 'getMarketSignalsTrend').mockResolvedValue(null as any)
    vi.spyOn(api, 'getFilingRecords').mockResolvedValue({
      records: [{
        id: 7, ticker: 'AAPL', form: '10-Q', filing_date: '2026-06-28',
        accession_number: 'acc-1', primary_document: 'q.htm',
        file_path: '/x/q.htm', downloaded_at: '2026-06-29T01:00:00+00:00',
        created_at: '2026-06-29T01:00:00+00:00',
      }],
      tickers: ['AAPL'],
      degraded: false,
    })
    render(Data, { props: { sub: 'filings' } })
    // Wait for table to render with AAPL in table body
    const cells = await screen.findAllByText('AAPL')
    expect(cells.length).toBeGreaterThan(0)
    // Verify all expected cells are in the table
    expect(screen.getAllByText('10-Q').length).toBeGreaterThan(0)
    expect(screen.getByText('2026-06-28')).toBeTruthy()
    const link = screen.getByText('下载 htm') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/api/filings/records/7/download')
  })
})
