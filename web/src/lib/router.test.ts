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
  it('legacy zones fall back to today', () => {
    for (const hash of ['#data/signals', '#technicals/MU', '#strategy/scores', '#trade/macro']) {
      expect(parseHash(hash)).toEqual({ zone: 'today', sub: undefined })
    }
  })
  it('query parameters never become part of route sub', () => {
    expect(parseHash('#tools/runs?task=filings')).toEqual({ zone: 'tools', sub: 'runs' })
  })
})
