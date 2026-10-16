import { describe, it, expect } from 'vitest'
import { parseHash } from './router'

describe('parseHash', () => {
  it('parses technicals zone with ticker sub', () => {
    expect(parseHash('#technicals/AAPL')).toEqual({ zone: 'technicals', sub: 'AAPL' })
  })
  it('parses data/signals', () => {
    expect(parseHash('#data/signals')).toEqual({ zone: 'data', sub: 'signals' })
  })
  it('falls back to tools for unknown zone', () => {
    expect(parseHash('#nope')).toEqual({ zone: 'tools', sub: undefined })
  })
})

describe('research hash query', () => {
  it('query parameters never become part of route sub', () => {
    expect(parseHash('#data/ashares?market=CN&symbol=600519.SH')).toEqual({ zone: 'data', sub: 'ashares' })
  })
})
