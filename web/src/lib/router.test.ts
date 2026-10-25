import { describe, it, expect } from 'vitest'
import { isLegacyZone, parseHash } from './router'

describe('parseHash', () => {
  it('parses technicals zone with ticker sub', () => {
    expect(parseHash('#technicals/AAPL')).toEqual({ zone: 'technicals', sub: 'AAPL' })
  })
  it('parses data/signals', () => {
    expect(parseHash('#data/signals')).toEqual({ zone: 'data', sub: 'signals' })
  })
  it('falls back to today for unknown zone', () => {
    expect(parseHash('#nope')).toEqual({ zone: 'today', sub: undefined })
  })
  it('parses the workbench zones and keeps legacy zones reachable', () => {
    expect(parseHash('#instrument/NVDA')).toEqual({ zone: 'instrument', sub: 'NVDA' })
    expect(parseHash('#review/weekly')).toEqual({ zone: 'review', sub: 'weekly' })
    expect(parseHash('#strategy/event-study')).toEqual({ zone: 'strategy', sub: 'event-study' })
    expect(isLegacyZone('strategy')).toBe(true)
    expect(isLegacyZone('today')).toBe(false)
  })
})

describe('research hash query', () => {
  it('query parameters never become part of route sub', () => {
    expect(parseHash('#data/us-research?market=US&symbol=MU')).toEqual({ zone: 'data', sub: 'us-research' })
  })
})
