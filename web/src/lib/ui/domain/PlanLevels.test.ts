import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/svelte'
import PlanLevels from './PlanLevels.svelte'
import PlanTable from '$lib/components/PlanTable.svelte'
import PlanHistoryTable from '$lib/components/PlanHistoryTable.svelte'
import { groups } from '$lib/plan-table-fixtures'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({}), { status: 200 })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const text = (container: HTMLElement) => container.textContent?.replace(/\s+/g, ' ').trim()

describe('PlanLevels', () => {
  it('pins the current PlanTable price cells (the format PlanLevels extracts)', () => {
    render(PlanTable, { groups: groups(), onRecheck: vi.fn(), onNote: vi.fn(async () => {}) })
    const row = within(screen.getByRole('table', { name: '入场期计划' })).getAllByRole('row')[1]
    // entry cell, stop cell, T1 cell and shares cell, as the table prints them today
    expect(row).toHaveTextContent('区间限价 95.10–97.30')
    expect(row).toHaveTextContent('91.40')
    expect(row).toHaveTextContent('104.70')
    expect(row).toHaveTextContent('120 股')
    expect(row.textContent).toContain('95.10–97.30')   // en dash U+2013
  })

  it('pins the one-line history format', () => {
    // PlanHistoryTable.levelsText: `入场 L–H · 止损 S · T1 T`
    render(PlanHistoryTable, {
      ticker: 'MU',
      rows: [{
        kind: 'version', at: '2026-10-28T22:31:00Z', session: '2026-10-28', chain_signal_date: '2026-10-28', version_no: 0,
        levels: { entry_low: '95.10', entry_high: '97.30', stop: '91.40', target1: '104.70' }, text: '第 0 版',
      }],
    })
    expect(document.body.textContent).toContain('入场 95.10–97.30 · 止损 91.40 · T1 104.70')
  })

  it('renders the same one-line standard', () => {
    const { container } = render(PlanLevels, { low: 95.1, high: 97.3, stop: 91.4, target1: 104.7 })
    expect(text(container)).toBe('入场 95.10–97.30 · 止损 91.40 · T1 104.70')
  })

  it('adds the suggested shares', () => {
    // PlanRowDetail: ` · 建议 ${shares} 股`
    const { container } = render(PlanLevels, { low: 95.1, high: 97.3, stop: 91.4, target1: 104.7, shares: 120 })
    expect(text(container)).toBe('入场 95.10–97.30 · 止损 91.40 · T1 104.70 · 建议 120 股')
  })

  it('shares null or absent adds nothing', () => {
    const { container } = render(PlanLevels, { low: 1, high: 2, stop: 0.5, target1: 3, shares: null })
    expect(text(container)).toBe('入场 1.00–2.00 · 止损 0.50 · T1 3.00')
  })

  it('a missing level says 没算, never a dash', () => {
    const { container } = render(PlanLevels, { low: 95.1, high: 97.3, stop: null, target1: 104.7 })
    expect(text(container)).toBe('入场 95.10–97.30 · 止损 没算 · T1 104.70')
    expect(text(container)).not.toContain('—')
  })

  it('all levels missing is one not-computed badge', () => {
    const { container } = render(PlanLevels, { low: null, high: null, stop: null, target1: null })
    expect(screen.getByText('没算').closest('[data-slot="badge"]')).toHaveAttribute('data-tone', 'warn')
    expect(text(container)).toBe('没算')
  })
})
