import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Plan from './Plan.svelte'
import * as api from '../lib/api'
import type { Derivation } from '../lib/derivation'

// fixture 形状沿用 web/src/lib/components/PlanDerivation.test.ts，只留页面标题与四段渲染所需。
const derivation = (over: Partial<Derivation> = {}): Derivation => ({
  derivation_version: 'derivation-1',
  plan: { id: 'p1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'rule', plan_version: 'plan-1', status: 'ok' },
  trigger: { note: '触发段只复核候选冻结的取值是否满足阈值。', candidates: [] },
  inputs: {
    bar_ids: [1], bars: null, bars_note: '',
    ref_price: { value: '110.750000', source_bar_id: 1 },
    earnings: null, earnings_note: '无记录',
    snapshot: null, snapshot_note: '无记录',
    exposure: null, sizing_params: null, regime: null, sector: null,
    next_earnings: null, pool_tier: null, source: null, screen: null, agent_run: null,
  },
  steps: [], checks: [],
  consistency: { status: 'consistent', mismatches: [], missing: [] },
  evidence: '规则 v1 与 `plan-1` 都未经验证（Phase 0 Gate HOLD）。',
  run: { ready: false, note: '迁移 025 未执行，暂无阶段证据' },
  ...over,
})

describe('Plan', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders the ticker · date title, the back link and the derivation component', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation())
    render(Plan, { sub: 'p1' })
    expect(await screen.findByRole('heading', { name: 'NVDA · 2026-10-22' })).toBeInTheDocument()
    const back = screen.getByRole('link', { name: '返回' })
    expect(back.getAttribute('href')).toBe('#today')   // 没有历史时的落点
    expect(await screen.findByText('触发')).toBeInTheDocument()       // PlanDerivation 已嵌入
    expect(screen.getByText('输入快照')).toBeInTheDocument()
  })

  it('shows not-found for unknown plan id', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockRejectedValue(new Error('计划不存在：nope'))
    render(Plan, { sub: 'nope' })
    expect(await screen.findByRole('alert')).toHaveTextContent('计划不存在')
    expect(screen.getByRole('heading')).toHaveTextContent('nope')   // 标题退化为 id，不白屏
  })

  it('shows the backend reason for a bad plan id', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockRejectedValue(new Error('计划 ID 不是合法 UUID'))
    render(Plan, { sub: 'not-a-uuid' })
    expect(await screen.findByRole('alert')).toHaveTextContent('计划 ID 不是合法 UUID')
  })
})
