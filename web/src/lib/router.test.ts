import { describe, it, expect } from 'vitest'
import { parseHash } from './router'

describe('parseHash', () => {
  it('parses the workbench zones with subs', () => {
    expect(parseHash('#instrument/NVDA')).toEqual({ zone: 'instrument', sub: 'NVDA' })
    expect(parseHash('#review/weekly')).toEqual({ zone: 'review', sub: 'weekly' })
    expect(parseHash('#tools/filings')).toEqual({ zone: 'tools', sub: 'filings' })
  })
  it('falls back to today for unknown zone', () => {
    expect(parseHash('#nope')).toEqual({ zone: 'today', sub: undefined })
  })
  it('routes the data zone; other legacy zones still fall back to today', () => {
    expect(parseHash('#data')).toEqual({ zone: 'data', sub: undefined })
    expect(parseHash('#data/signals')).toEqual({ zone: 'data', sub: 'signals' })
    for (const hash of ['#technicals/MU', '#strategy/scores', '#trade/macro']) {
      expect(parseHash(hash)).toEqual({ zone: 'today', sub: undefined })
    }
  })
  it('query parameters never become part of route sub', () => {
    expect(parseHash('#tools/runs?task=filings')).toEqual({ zone: 'tools', sub: 'runs' })
  })
})
