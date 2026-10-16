import { describe, it, expect } from 'vitest'
import { researchHash, readResearchSelection } from './research-navigation'

describe('research navigation identity', () => {
  it('round-trips market and symbol without mixing them into the page route', () => {
    const hash = researchHash('strategy', 'observation', 'CN', '600519.SH')
    expect(hash).toBe('#strategy/observation?market=CN&symbol=600519.SH')
    expect(readResearchSelection(hash)).toEqual({ market:'CN', symbol:'600519.SH' })
  })
  it('does not accept a CN identity under a US query or incomplete numeric identities', () => {
    expect(readResearchSelection('#data/ashares?market=US&symbol=600519.SH')).toBeNull()
    expect(readResearchSelection('#data/ashares?market=CN&symbol=600519')).toBeNull()
  })
})
