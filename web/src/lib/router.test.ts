import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import SideNav from './components/SideNav.svelte'
import { parseHash, workbenchZones, zones } from './router'

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
  it('routes #plan/<id> to the plan zone; #plan without an id falls back to today', () => {
    expect(zones).toContain('plan')
    expect(workbenchZones).not.toContain('plan')   // 独立页，不属于工作台分区
    expect(parseHash('#plan/abc')).toEqual({ zone: 'plan', sub: 'abc' })
    expect(parseHash('#plan')).toEqual({ zone: 'today', sub: undefined })
  })
  it('keeps the plan zone out of the side nav', () => {
    render(SideNav, { current: 'plan', sub: 'abc' })
    expect(screen.queryByText('计划')).toBeNull()
    const hrefs = screen.getAllByRole('link').map(a => a.getAttribute('href'))
    expect(hrefs.every(href => !href!.startsWith('#plan'))).toBe(true)
  })
  it('#knowledge/plan.stop@1 parses to knowledge zone with sub', () => {
    expect(zones).toContain('knowledge')
    expect(workbenchZones).not.toContain('knowledge')
    expect(parseHash('#knowledge/plan.stop@1')).toEqual({ zone: 'knowledge', sub: 'plan.stop@1' })
    expect(parseHash('#knowledge/principles')).toEqual({ zone: 'knowledge', sub: 'principles' })
    expect(parseHash('#knowledge')).toEqual({ zone: 'knowledge', sub: undefined })
  })
})
