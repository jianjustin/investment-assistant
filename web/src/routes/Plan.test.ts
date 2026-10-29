import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
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

  it('agent-2 plan shows PlanTimeline and UserInputs', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation({
      plan: { id: 'p1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'agent', plan_version: 'agent-2', status: 'ok' },
    }))
    const getChain = vi.spyOn(api, 'getChain').mockResolvedValue({
      ticker: 'NVDA', signal_date: '2026-10-22', session: '2026-10-24',
      state: { state: 'entry', mode: 'entry', basis: '尚未决定' }, head_plan_id: 'p2', version_no: 1,
      latest_review: null, shadow_version: 'plan-shadow-1', versions: [], reviews: [], inputs: [],
    } as any)
    const getInputs = vi.spyOn(api, 'getUserInputs').mockResolvedValue({ inputs: [] })
    render(Plan, { sub: 'p1' })
    expect(await screen.findByRole('region', { name: '版本链' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '我的补充' })).toBeInTheDocument()
    expect(getChain).toHaveBeenCalledWith('NVDA', '2026-10-22')
    expect(getInputs).toHaveBeenCalledWith('NVDA', '2026-10-22')
    expect(await screen.findByText('触发')).toBeInTheDocument()      // 推导照旧嵌入
  })

  it('rule plan page unchanged', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation())
    const getChain = vi.spyOn(api, 'getChain')
    const getInputs = vi.spyOn(api, 'getUserInputs')
    render(Plan, { sub: 'p1' })
    expect(await screen.findByRole('heading', { name: 'NVDA · 2026-10-22' })).toBeInTheDocument()
    expect(await screen.findByText('触发')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '版本链' })).toBeNull()
    expect(screen.queryByRole('region', { name: '我的补充' })).toBeNull()
    expect(getChain).not.toHaveBeenCalled()
    expect(getInputs).not.toHaveBeenCalled()
  })

  it('agent-1 plan offers 看推理过程 for its generating run', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation({
      plan: { id: 'p1', ticker: 'ROP', signal_date: '2026-10-26', kind: 'agent', plan_version: 'agent-1', status: 'ok' },
      inputs: { ...derivation().inputs, agent_run: { id: 'run-1', model: 'glm', agent_version: 'agent-1' } },
    }))
    const getChain = vi.spyOn(api, 'getChain')
    const getReasoning = vi.spyOn(api, 'getReasoning').mockResolvedValue({
      run: { id: 'run-1', ticker: 'ROP', signal_date: '2026-10-26', mode: 'propose', agent_version: 'agent-1',
             status: 'ok', reason: null, reason_text: null },
      legacy: true, version: null, review: null, steps: [],
      notes: ['agent-1（旧版）：没有失效条件、下次复查条件与逐条对应的反证，也不参与复查；以下按原样显示'],
    } as any)
    render(Plan, { sub: 'p1' })
    const region = await screen.findByRole('region', { name: 'Agent 推理' })
    expect(region).toHaveTextContent('agent-1（旧版，不参与复查）')
    expect(getReasoning).not.toHaveBeenCalled()                       // 展开时才请求
    await fireEvent.click(screen.getByRole('button', { name: '看推理过程' }))
    expect(getReasoning).toHaveBeenCalledWith('run-1')
    expect(await screen.findByText(/agent-1（旧版）：没有失效条件/)).toBeInTheDocument()
    expect(getChain).not.toHaveBeenCalled()                           // agent-1 没有版本链
  })

  it('rule plan and agent-2 plan have no separate reasoning section', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation())
    render(Plan, { sub: 'p1' })
    expect(await screen.findByText('触发')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Agent 推理' })).toBeNull()
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

  it('header links to instrument page', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation())
    render(Plan, { sub: 'p1' })
    await screen.findByRole('heading', { name: 'NVDA · 2026-10-22' })
    expect(screen.getByRole('link', { name: '标的页' }).getAttribute('href')).toBe('#instrument/NVDA')
  })

  it('header DiscussButton and discussion list', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation())
    const list = vi.spyOn(api, 'getDiscussions').mockResolvedValue({ discussions: [
      { id: 5, created_at: '2026-10-28T10:00:00Z', turn_count: 2, first_question: '这个止损怎么来的？' },
      { id: 6, created_at: '2026-10-28T11:00:00Z', turn_count: 0, first_question: null }] })
    const post = vi.spyOn(api, 'postDiscussion').mockResolvedValue({ id: 7 } as any)
    location.hash = ''
    render(Plan, { sub: 'p1' })
    const header = (await screen.findByRole('heading', { name: 'NVDA · 2026-10-22' })).closest('header')!
    await fireEvent.click(await within(header).findByRole('button', { name: '就此计划讨论' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0].context).toEqual({ kind: 'plan', plan_id: 'p1' })
    expect(list).toHaveBeenCalledWith({ plan_id: 'p1' })
    const section = await screen.findByRole('region', { name: '讨论' })
    const links = within(section).getAllByRole('link')
    expect(links[0]).toHaveAttribute('href', '#discuss/5')
    expect(links[0]).toHaveTextContent('2 轮')
    expect(links[0]).toHaveTextContent('这个止损怎么来的？')
    expect(links[1]).toHaveAttribute('href', '#discuss/6')
    expect(links[1]).toHaveTextContent('0 轮')
  })

  it('says so when there is no discussion yet, and survives a failing list', async () => {
    vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation())
    vi.spyOn(api, 'getDiscussions').mockResolvedValue({ discussions: [] })
    const first = render(Plan, { sub: 'p1' })
    expect(await screen.findByText('还没有讨论')).toBeInTheDocument()
    first.unmount()
    vi.spyOn(api, 'getDiscussions').mockRejectedValue(new Error('迁移 027 未执行'))
    render(Plan, { sub: 'p1' })
    expect(await screen.findByText(/讨论不可用：迁移 027 未执行/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '标的页' })).toBeInTheDocument()
  })

  describe('重新运行 Agent', () => {
    const run = (over: Record<string, unknown>) => ({
      id: 'r', ticker: 'NVDA', signal_date: '2026-10-22', mode: 'propose', status: 'ok', reason: null,
      created_at: '2026-10-22T22:00:00Z', ...over,
    })

    it('rerun agent button for max_attempts and error runs', async () => {
      vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation())
      const list = vi.spyOn(api, 'getAgentRuns').mockResolvedValue({ runs: [
        run({ id: 'a', status: 'error', reason: 'model_error', created_at: '2026-10-22T20:00:00Z' }),
        run({ id: 'b', status: 'skipped', reason: 'max_attempts', created_at: '2026-10-22T22:00:00Z' }),
        run({ id: 'c', ticker: 'AMD', status: 'skipped', reason: 'max_attempts' }),         // another ticker
        run({ id: 'd', mode: 'interpret', status: 'ok' }),                                   // latest of its mode is fine
      ] })
      const rerun = vi.spyOn(api, 'rerunAgent').mockResolvedValue({ reset_id: 3, run_id: 'run-new', replayed: false })
      render(Plan, { sub: 'p1' })
      const section = await screen.findByRole('region', { name: 'Agent 重新运行' })
      expect(list).toHaveBeenCalledWith('2026-10-22')
      expect(section).toHaveTextContent('Agent 建议：最近一次跳过（已达重试上限）')
      const button = within(section).getByRole('button', { name: '重新运行 Agent' })
      expect(within(section).getAllByRole('button')).toHaveLength(1)
      await fireEvent.click(button)
      expect(rerun).toHaveBeenCalledWith({
        ticker: 'NVDA', signal_date: '2026-10-22', mode: 'propose',
        request_id: expect.stringMatching(/^[0-9a-f-]{36}$/), origin: 'plan',
      })
      expect(await screen.findByText('已重置尝试次数，并已在后台重新运行')).toBeInTheDocument()
    })

    it('shows the error text of the latest error run, and the 409 text on rerun', async () => {
      vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation())
      vi.spyOn(api, 'getAgentRuns').mockResolvedValue({ runs: [run({ mode: 'interpret', status: 'error', reason: 'not_connected' })] })
      vi.spyOn(api, 'rerunAgent').mockRejectedValue(new api.ApiError('not_needed', 409, 'not_needed'))
      render(Plan, { sub: 'p1' })
      const section = await screen.findByRole('region', { name: 'Agent 重新运行' })
      expect(section).toHaveTextContent('Agent 简报解读：最近一次出错（ChatGPT 未连接）')
      await fireEvent.click(within(section).getByRole('button', { name: '重新运行 Agent' }))
      expect(await screen.findByText('这个单元不需要重跑')).toBeInTheDocument()
    })

    it('no entry when the runs are fine or the list cannot be read', async () => {
      vi.spyOn(api, 'getPlanDerivation').mockResolvedValue(derivation())
      const list = vi.spyOn(api, 'getAgentRuns').mockResolvedValue({ runs: [run({ status: 'ok' })] })
      const first = render(Plan, { sub: 'p1' })
      await screen.findByRole('heading', { name: 'NVDA · 2026-10-22' })
      await waitFor(() => expect(list).toHaveBeenCalled())
      expect(screen.queryByRole('region', { name: 'Agent 重新运行' })).toBeNull()
      first.unmount()
      list.mockRejectedValue(new Error('HTTP 503'))
      render(Plan, { sub: 'p1' })
      await screen.findByRole('heading', { name: 'NVDA · 2026-10-22' })
      await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
      expect(screen.queryByRole('region', { name: 'Agent 重新运行' })).toBeNull()
      expect(screen.queryByRole('alert')).toBeNull()
    })
  })
})
