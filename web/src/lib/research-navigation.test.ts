import { describe, it, expect } from 'vitest'
import { researchHash, readResearchSelection } from './research-navigation'

describe('research navigation identity', () => {
  it('round-trips market and symbol without mixing them into the page route', () => {
    const hash = researchHash('strategy', 'observation', 'US', 'BRK.B')
    expect(hash).toBe('#strategy/observation?market=US&symbol=BRK.B')
    expect(readResearchSelection(hash)).toEqual({ market:'US', symbol:'BRK.B' })
  })
  it('readResearchSelection rejects CN selections', () => {
    expect(readResearchSelection('#strategy/observation?market=CN&symbol=688008.SH')).toBeNull()
    expect(readResearchSelection('#strategy/observation?market=US&symbol=MU')).toEqual({ market:'US', symbol:'MU' })
  })
})
