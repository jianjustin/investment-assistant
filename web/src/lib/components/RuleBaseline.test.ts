import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte'
import RuleBaseline from './RuleBaseline.svelte'
import * as api from '../api'
import { resetConceptIndex } from '../knowledge'

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

const plan = (over: Record<string, unknown> = {}) => ({
  id: 'b1', ticker: 'MU', signal_date: '2026-10-29', kind: 'rule', plan_version: 'plan-2', status: 'ok',
  entry_low: '95.00', entry_high: '97.00', stop: '91.00', target1: '104.00', ref_price: '96.00', atr: '2.10',
  valid_from: '2026-10-31', valid_until: '2026-11-04', sizing: { status: 'sized', shares: 110 },
  invalid_reasons: [], warnings: [], inputs: {}, ...over,
}) as any

describe('RuleBaseline', () => {
  it('folded: one standard line with the validity, and a toggle that reports aria-expanded', async () => {
    const ontoggle = vi.fn()
    render(RuleBaseline, { plan: plan(), expanded: false, ontoggle })
    expect(screen.getByTestId('rule-baseline')).toHaveTextContent('规则基线 plan-2：入场 95.00–97.00 · 止损 91.00 · T1 104.00 · 建议 110 股（有效）')
    const toggle = screen.getByRole('button', { name: '展开' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle.className).toContain('h-auto')                 // a link-variant Button, not a bare <button>
    await fireEvent.click(toggle)
    expect(ontoggle).toHaveBeenCalledTimes(1)
  })

  it('expanded: details, a 收起 toggle, and the derivation opens on demand', async () => {
    const ontoggle = vi.fn()
    vi.spyOn(api, 'getPlanDerivation').mockRejectedValue(new Error('offline'))
    render(RuleBaseline, { plan: plan(), expanded: true, ontoggle })
    const box = screen.getByTestId('rule-baseline')
    expect(box).toHaveTextContent('入场区间 95.00–97.00 · 止损 91.00 · T1 104.00 · 有效期至 2026-11-04')
    expect(box).toHaveTextContent('建议 110 股')
    const toggle = screen.getByRole('button', { name: '收起' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle.className).toContain('h-auto')
    await fireEvent.click(screen.getByRole('button', { name: '展开推导' }))
    expect(api.getPlanDerivation).toHaveBeenCalledWith('b1')
  })

  it('collapsible=false shows the expanded block with no toggle', () => {
    render(RuleBaseline, { plan: plan(), expanded: false, ontoggle: vi.fn(), collapsible: false })
    expect(screen.queryByRole('button', { name: '收起' })).toBeNull()
    expect(screen.queryByRole('button', { name: '展开' })).toBeNull()
    expect(screen.getByTestId('rule-baseline')).toHaveTextContent('入场区间 95.00–97.00')
  })

  it('an invalid plan lists its reasons in the danger tone, a missing equity snapshot says so', () => {
    render(RuleBaseline, { plan: plan({ status: 'invalid', invalid_reasons: ['财报在 3 日内'], sizing: { status: 'no_equity', shares: null } }),
      expanded: true, ontoggle: vi.fn() })
    expect(screen.getByText('作废：财报在 3 日内').className).toContain('text-destructive')
    expect(screen.getByText('缺资金快照，无法计算建议股数').className).toContain('text-warn')
  })
})
