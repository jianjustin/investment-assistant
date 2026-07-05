import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Data from './Data.svelte'
import * as api from '../lib/api'

describe('Data 财报 Tab', () => {
  it('renders filing records with download link', async () => {
    vi.spyOn(api, 'getMarketSignals').mockResolvedValue({ rows: [] } as any)
    vi.spyOn(api, 'getMarketSignalsTrend').mockResolvedValue(null as any)
    vi.spyOn(api, 'getTickerTrends').mockResolvedValue({ rows: [] } as any)
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
