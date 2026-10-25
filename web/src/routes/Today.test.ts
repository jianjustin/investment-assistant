import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import Today from './Today.svelte'
import { confirmResearchNavigation } from '../lib/navigation-guard'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const plan = (overrides: Record<string, unknown> = {}) => ({
  id: 'p1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'rule', plan_version: 'plan-1', status: 'ok',
  entry_low: 98.5, entry_high: 101.5, stop: 94, target1: 112, ref_price: 100, atr: 2.11,
  valid_from: '2026-10-23', valid_until: '2026-10-27',
  sizing: { status: 'sized', shares: 166, risk_amount: 1000, snapshot_as_of: '2026-10-20' },
  invalid_reasons: [], warnings: [], ...overrides,
})

const holding = (overrides: Record<string, unknown> = {}) => ({
  ticker: 'NVDA', quantity: 10, avg_cost: 100, plan_id: 'p1', stop: 105, mode: 'trailing', t1_reached: true,
  target1: 112, last_close: 110, to_stop_pct: -0.045, to_target_pct: 0.018, next_earnings: null, ...overrides,
})

const unit = (overrides: Record<string, unknown> = {}) => ({
  plan: null,
  ticker: 'NVDA', signal_date: '2026-10-22', proposed_action: 'buy', labels: [], candidate_ids: ['c1'],
  rule_ids: ['trend_reclaim'], entry_passed: false, market_status: 'green', holding: false, position: null,
  candidates: [{ id: 'c1', signal_date: '2026-10-22', action: 'buy', rule_id: 'trend_reclaim',
                 inputs: { values: { close: 110.75, ma20: 108.1 } } }],
  brief: { id: 'b1', status: 'ok', output: { summary: '合成摘要', support: [{ text: '支持一', refs: ['news:2'] }],
                                             contra: [{ text: '反证一', refs: ['candidate:c1'] }], conflicts: [] } },
  filings: [],
  news: [{ id: 2, source: 'yfinance', title: '合成新闻', url: 'https://news.example.com/2', publisher: null,
           published_at: null, fetched_at: '2026-10-22T20:00:00Z' }],
  ...overrides,
})

let calls: { url: string; init?: RequestInit }[]
let respond: (url: string, init?: RequestInit) => Promise<Response>

beforeEach(() => {
  calls = []
  respond = async () => json({ session: '2026-10-22', units: [unit()], holdings: [] })
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => { calls.push({ url: String(url), init }); return respond(String(url), init) }))
  vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValueOnce('req-1').mockReturnValueOnce('req-2') })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('shows candidates, cited brief and undated news without inventing times', async () => {
  render(Today)
  expect(await screen.findByRole('heading', { name: /NVDA/ })).toBeInTheDocument()
  expect(screen.getByText('趋势回踩修复')).toBeInTheDocument()
  expect(screen.getByText('合成摘要')).toBeInTheDocument()
  expect(screen.getByText(/支持一/)).toHaveTextContent('news:2')
  expect(screen.getByText(/反证一/)).toBeInTheDocument()
  expect(screen.getByText(/发布时间未知/)).toBeInTheDocument()
  expect(screen.getByText(/大盘 green（仅背景）/)).toBeInTheDocument()
})

it('labels conflict, avoid, late entry and fallback or invalid briefs', async () => {
  respond = async () => json({ session: '2026-10-22', units: [
    unit({ ticker: 'MU', proposed_action: 'watch', labels: ['conflict'], entry_passed: true,
           brief: { id: 'b2', status: 'fallback', error: 'no key', output: { summary: '规则候选', support: [], contra: [], conflicts: [] } } }),
    unit({ ticker: 'RKLB', proposed_action: 'sell', labels: ['avoid'], brief: { id: 'b3', status: 'error', error: 'unknown refs: news:9' } }),
  ] })
  render(Today)
  await screen.findByRole('heading', { name: /MU/ })
  expect(screen.getByText('冲突')).toBeInTheDocument()
  expect(screen.getByText('回避')).toBeInTheDocument()
  expect(screen.getByText(/已过入场时点/)).toBeInTheDocument()
  expect(screen.getByText(/LLM 未参与/)).toBeInTheDocument()
  expect(screen.getByText(/解读无效，已隐藏/)).toHaveTextContent('unknown refs: news:9')
})

it('requires a reason, posts the decision with a stable request id and removes the unit', async () => {
  render(Today)
  await screen.findByRole('heading', { name: /NVDA/ })
  const submit = screen.getByRole('button', { name: '提交决定' })
  expect(submit).toBeDisabled()
  await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '合成理由' } })
  respond = async (url) => url.includes('/decisions') ? json({ status: 'created', record: { id: 'd1' } }) : json({ session: '2026-10-22', units: [] })
  await fireEvent.click(submit)
  await waitFor(() => expect(screen.getByText('今日没有待处理的信号')).toBeInTheDocument())
  const post = calls.find(c => c.url.includes('/decisions'))!
  expect(JSON.parse(String(post.init!.body))).toMatchObject({ request_id: 'req-1', decision: 'accept', final_action: 'buy',
                                                              reason: '合成理由', brief_id: 'b1' })
})

it('keeps the draft and the request id when the server reports a conflict', async () => {
  render(Today)
  await screen.findByRole('heading', { name: /NVDA/ })
  await fireEvent.click(screen.getByLabelText('否决'))
  await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '保留的草稿' } })
  respond = async (url) => url.includes('/decisions') ? json({ error: 'newer decision' }, 409) : json({ session: '2026-10-22', units: [unit()] })
  await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
  expect(await screen.findByText(/已有更新的记录/)).toBeInTheDocument()
  expect((screen.getByLabelText('理由') as HTMLTextAreaElement).value).toBe('保留的草稿')
  await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
  const ids = calls.filter(c => c.url.includes('/decisions')).map(c => JSON.parse(String(c.init!.body)).request_id)
  expect(ids).toEqual(['req-1', 'req-1'])
})

it('reports a missing database instead of an empty list', async () => {
  respond = async () => json({ error: '工作台数据表未就绪' }, 503)
  render(Today)
  expect(await screen.findByText(/数据库未就绪/)).toBeInTheDocument()
  expect(screen.queryByText('今日没有待处理的信号')).not.toBeInTheDocument()
})

it('guards unsent decision drafts on navigation', async () => {
  render(Today)
  await screen.findByRole('heading', { name: /NVDA/ })
  await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '未提交' } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  expect(confirmResearchNavigation()).toBe(false)
  expect(confirm).toHaveBeenCalled()
})


describe('trade plans', () => {
  it('renders plan levels and shares', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan() })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(screen.getByText(/入场区间 98\.5–101\.5/)).toBeInTheDocument()
    expect(screen.getByText(/止损 94/)).toBeInTheDocument()
    expect(screen.getByText(/T1 112/)).toBeInTheDocument()
    expect(screen.getByText(/建议 166 股/)).toBeInTheDocument()
    expect(screen.getByText(/证据：未验证/)).toBeInTheDocument()
  })

  it('shows the no_equity hint without inventing a size', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan(
      { sizing: { status: 'no_equity', shares: null, snapshot_as_of: null } }) })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(screen.getByText(/缺资金快照，无法计算/)).toBeInTheDocument()
  })

  it('only allows own levels when the rule plan is invalid', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan(
      { status: 'invalid', invalid_reasons: ['earnings_in_validity'] }) })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    expect(screen.getByText(/作废：earnings_in_validity/)).toBeInTheDocument()
    expect(screen.getByLabelText('规则计划')).toBeDisabled()
    expect(screen.getByLabelText('自定价位')).toBeChecked()
  })

  it('blocks own levels with stop >= entry_low', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan({ status: 'invalid' }) })],
                                 holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '自定价位' } })
    await fireEvent.input(screen.getByLabelText('入场下限'), { target: { value: '99' } })
    await fireEvent.input(screen.getByLabelText('入场上限'), { target: { value: '101' } })
    await fireEvent.input(screen.getByLabelText('止损价'), { target: { value: '100' } })
    await fireEvent.input(screen.getByLabelText('T1 价'), { target: { value: '112' } })
    expect(screen.getByText(/价位需满足/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交决定' })).toBeDisabled()
  })

  it('accept sends plan_id for a healthy rule plan', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan() })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '按规则计划' } })
    respond = async (url) => url.includes('/decisions')
      ? json({ status: 'created', record: { id: 'd1' } })
      : json({ session: '2026-10-22', units: [], holdings: [] })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => expect(screen.getByText('今日没有待处理的信号')).toBeInTheDocument())
    const post = calls.find(c => c.url.includes('/decisions'))!
    const body = JSON.parse(String(post.init!.body))
    expect(body.plan_id).toBe('p1')
    expect(body.own_plan).toBeNull()
  })

  it('accept with own levels sends own_plan', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan() })], holdings: [] })
    render(Today)
    await screen.findByRole('heading', { name: /NVDA/ })
    await fireEvent.click(screen.getByLabelText('自定价位'))
    await fireEvent.input(screen.getByLabelText('入场下限'), { target: { value: '97' } })
    await fireEvent.input(screen.getByLabelText('入场上限'), { target: { value: '101' } })
    await fireEvent.input(screen.getByLabelText('止损价'), { target: { value: '94' } })
    await fireEvent.input(screen.getByLabelText('T1 价'), { target: { value: '110' } })
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '自定' } })
    respond = async (url) => url.includes('/decisions')
      ? json({ status: 'created', record: { id: 'd2' } })
      : json({ session: '2026-10-22', units: [], holdings: [] })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => expect(screen.getByText('今日没有待处理的信号')).toBeInTheDocument())
    const body = JSON.parse(String(calls.find(c => c.url.includes('/decisions'))!.init!.body))
    expect(body.plan_id).toBeNull()
    expect(body.own_plan).toMatchObject({ entry_low: '97', entry_high: '101', stop: '94', target1: '110' })
    expect(body.own_plan.request_id).toBeTruthy()
  })

  it('holdings show stop and t1 state', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [holding()] })
    render(Today)
    expect(await screen.findByText(/持仓止损/)).toBeInTheDocument()
    expect(screen.getByText(/NVDA/)).toBeInTheDocument()
    expect(screen.getByText(/止损 105/)).toBeInTheDocument()
    expect(screen.getByText(/已触 T1/)).toBeInTheDocument()
  })

  it('repush button calls pushToday and shows the result', async () => {
    respond = async (url) => url.includes('/api/workbench/push')
      ? json({ session: '2026-10-22', sent: true, messages: 4 })
      : json({ session: '2026-10-22', units: [], holdings: [] })
    render(Today)
    await screen.findByText('今日没有待处理的信号')
    await fireEvent.click(screen.getByRole('button', { name: '重新推送今日计划' }))
    await waitFor(() => expect(screen.getByText(/已推送 4 条/)).toBeInTheDocument())
    const push = calls.find(c => c.url.includes('/api/workbench/push'))!
    expect(push.init?.method).toBe('POST')
  })
})

describe('market context and extended pool', () => {
  const market = { id: 'r1', session: '2026-10-22', calc_version: 'regime-1', label: 'risk_off',
    breadth: { tickers: 40, eligible_50: 40, above_50: 12, pct_50: 0.3, eligible_200: 40, above_200: 10,
               pct_200: 0.25, eligible_52w: 38, new_highs: 3, new_lows: 5 },
    sectors: { SMH: { rs20: -0.12, rs60: -0.2, state: 'weak' } }, macro: { BAMLH0A0HYM2: null, T10Y2Y: null },
    inputs: {}, created_at: '2026-10-22T23:00:00Z' }
  const contextPlan = (overrides: Record<string, unknown> = {}) => plan({
    inputs: { context: { context_version: 'context-1', pool_tier: 'core',
                         regime: { id: 'r1', label: 'risk_off' },
                         sector: { etf: 'SMH', rs20: -0.12, rs60: -0.2, state: 'weak' },
                         next_earnings: '2026-11-20' } }, ...overrides,
  })

  it('market card shows label and breadth', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], extended_units: [], market })
    render(Today)
    expect(await screen.findByText('防守')).toBeTruthy()
    expect(screen.getByText(/站上 MA50 30\.0%/)).toBeTruthy()
    expect(screen.getByText(/新高 3 \/ 新低 5/)).toBeTruthy()
    expect(screen.getByText(/SMH/)).toBeTruthy()
  })
  it('market card shows FRED not configured', async () => {
    const unconfigured = { ...market, inputs: { macro_status: { BAMLH0A0HYM2: 'not_configured', T10Y2Y: 'not_configured' } } }
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], extended_units: [], market: unconfigured })
    render(Today)
    expect(await screen.findByText('FRED 未配置')).toBeTruthy()
  })
  it('market card tells a FRED failure apart from no key', async () => {
    const failed = { ...market, inputs: { macro_status: { BAMLH0A0HYM2: 'error', T10Y2Y: 'error' } } }
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], extended_units: [], market: failed })
    render(Today)
    expect(await screen.findByText(/FRED 采集失败/)).toBeTruthy()
    expect(screen.queryByText('FRED 未配置')).toBeNull()
  })
  it('market card without recorded FRED status says no data', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], extended_units: [], market })
    render(Today)
    expect(await screen.findByText('FRED 无数据')).toBeTruthy()
  })
  it('extended units show the plan status', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], market: null,
                                 extended_units: [
                                   { ticker: 'AMD', signal_date: '2026-10-22', proposed_action: 'buy',
                                     rule_ids: ['trend_reclaim'], plan: contextPlan({ status: 'invalid' }) },
                                   { ticker: 'ARM', signal_date: '2026-10-22', proposed_action: 'buy',
                                     rule_ids: ['trend_reclaim'], plan: contextPlan() }] })
    render(Today)
    await screen.findByText(/扩展池（只影子跟踪）/)
    const items = [...document.querySelectorAll('details li')].map(li => li.textContent ?? '')
    expect(items.find(t => t.includes('AMD'))).toContain('已作废')
    expect(items.find(t => t.includes('ARM'))).toContain('有效')
  })
  it('plan card shows regime, next earnings and sector', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: contextPlan() })], holdings: [],
                                 extended_units: [], market })
    render(Today)
    expect(await screen.findByText(/区制 防守 · 下次财报 2026-11-20 · 行业 SMH 弱/)).toBeTruthy()
  })
  it('plan card falls back to unknown context', async () => {
    respond = async () => json({ session: '2026-10-22', units: [unit({ plan: plan() })], holdings: [], extended_units: [], market: null })
    render(Today)
    expect(await screen.findByText(/下次财报 未知 · 行业 未映射/)).toBeTruthy()
  })
  it('extended units are collapsed and have no decision controls', async () => {
    respond = async () => json({ session: '2026-10-22', units: [], holdings: [], market: null,
                                 extended_units: [{ ticker: 'AMD', signal_date: '2026-10-22', proposed_action: 'buy',
                                                    rule_ids: ['trend_reclaim'], plan: contextPlan() }] })
    render(Today)
    expect(await screen.findByText(/扩展池（只影子跟踪）/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '提交决定' })).toBeNull()
    expect(screen.queryByLabelText('理由')).toBeNull()
    const details = document.querySelector('details')!
    expect(details.open).toBe(false)
    expect(details.textContent).toContain('AMD')
  })
})

describe('agent track', () => {
  const agentPlan = (overrides: Record<string, unknown> = {}) => ({
    id: 'ap1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'agent', plan_version: 'agent-1', status: 'ok',
    entry_low: 98.5, entry_high: 101.5, stop: 96, target1: 108, ref_price: 100, atr: 2,
    valid_from: '2026-10-23', valid_until: '2026-10-27',
    sizing: { status: 'sized', shares: 166, risk_amount: 1000, snapshot_as_of: '2026-10-20' },
    invalid_reasons: [], warnings: [], ...overrides,
  })

  const agentOk = (overrides: Record<string, unknown> = {}) => ({
    id: 'r1', status: 'ok', model: 'glm-5.3', agent_version: 'agent-1',
    output: { action: 'buy', summary: '回踩修复放量',
              levels: { entry_low: { value: '98.50', refs: ['call:1'] },
                        entry_high: { value: '101.50', refs: ['call:1'] },
                        stop: { value: '96.00', refs: ['call:1'] },
                        target1: { value: '108.00', refs: ['call:1'] } },
              thesis: [{ text: '放量突破 20 日线', refs: ['call:1'] }] },
    counter: { status: 'ok', risks: [{ text: '财报临近', refs: ['call:1'] }], dropped: 0 },
    plan: agentPlan(), input_tokens: 40, output_tokens: 20, created_at: '2026-10-22T23:00:00Z',
    ...overrides,
  })

  const agentRejected = {
    id: 'r2', status: 'rejected', reason: 'invalid_citation', created_at: '2026-10-22T23:00:00Z',
  }

  const toolCallDetail = () => ({
    ...agentOk(), tool_calls: [
      { seq: 1, phase: 'propose', tool: 'get_indicators', args: { ticker: 'NVDA' },
        result: { ref: 'call:1', data: { last_close: 100 } },
        result_sha256: 'abcd1234ef567890abcd1234ef567890abcd1234ef567890abcd1234ef567890',
        called_at: '2026-10-22T22:31:00Z' }],
  })

  const todayWith = (units: any[], extended: any[] = []) =>
    async () => json({ session: '2026-10-22', units, extended_units: extended, holdings: [] })

  it('agent block shows action, levels, thesis refs and counter', async () => {
    respond = todayWith([unit({ agent: agentOk() })])
    render(Today)
    expect(await screen.findByText('Agent 建议（glm-5.3 · agent-1）买入')).toBeInTheDocument()
    expect(screen.getByText('入场区间 98.50–101.50 · 止损 96.00 · T1 108.00')).toBeInTheDocument()
    expect(screen.getByText('建议 166 股')).toBeInTheDocument()
    expect(screen.getByText('回踩修复放量')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'call:1' }).length).toBeGreaterThan(0)
    expect(screen.getByText(/反方：/)).toBeInTheDocument()
    expect(screen.getByText(/财报临近/)).toBeInTheDocument()
  })

  it('clicking a ref opens the tool call', async () => {
    respond = async (url: string) =>
      url.includes('/agent-runs/r1') ? json(toolCallDetail()) : await todayWith([unit({ agent: agentOk() })])()
    render(Today)
    await fireEvent.click((await screen.findAllByRole('button', { name: 'call:1' }))[0])
    expect(await screen.findByText(/get_indicators/)).toBeInTheDocument()
    expect(screen.getByText(/abcd1234/)).toBeInTheDocument()          // 哈希前 8 位
    expect(screen.getByText(/ticker/)).toBeInTheDocument()            // 调用参数
    expect(screen.getByRole('button', { name: /关闭/ })).toBeInTheDocument()
  })

  it('rejected agent shows reason and rerun button', async () => {
    respond = todayWith([unit({ agent: agentRejected })])
    render(Today)
    expect(await screen.findByText('Agent 未给出建议')).toBeInTheDocument()
    expect(screen.getByText('引用无效已作废')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新运行 Agent' })).toBeInTheDocument()
  })

  it('rerun posts and refreshes', async () => {
    respond = async (url: string, init?: RequestInit) => {
      if (url === '/api/workbench/agent-runs' && init?.method === 'POST')
        return json({ id: 'r3', status: 'ok', reason: null })
      return await todayWith([unit({ agent: agentRejected })])()
    }
    render(Today)
    await fireEvent.click(await screen.findByRole('button', { name: '重新运行 Agent' }))
    await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/agent-runs'
      && c.init?.method === 'POST')).toBe(true))
    const body = JSON.parse(String(calls.find(c => c.url === '/api/workbench/agent-runs')!.init!.body))
    expect(body).toEqual({ ticker: 'NVDA', signal_date: '2026-10-22' })
    await waitFor(() => expect(calls.filter(c => c.url === '/api/workbench/today').length).toBeGreaterThanOrEqual(2))
  })

  it('agent basis enabled only when agent plan ok', async () => {
    respond = todayWith([unit({ plan: plan(), agent: { id: 'r', status: 'pass', model: 'glm-5.3',
      output: { summary: '趋势不明' }, counter: null, plan: null, input_tokens: 5, output_tokens: 5,
      created_at: 'c' } })])
    const { unmount } = render(Today)
    expect((await screen.findByLabelText(/Agent 建议/) as HTMLInputElement).disabled).toBe(true)
    unmount()

    respond = todayWith([unit({ plan: plan(), agent: agentOk() })])
    render(Today)
    expect((await screen.findByLabelText(/Agent 建议/) as HTMLInputElement).disabled).toBe(false)
  })

  it('rule invalid and agent ok defaults basis to agent', async () => {
    respond = todayWith([unit({ plan: plan({ status: 'invalid', invalid_reasons: ['earnings_in_validity'] }),
                               agent: agentOk() })])
    render(Today)
    expect((await screen.findByLabelText(/Agent 建议/) as HTMLInputElement).checked).toBe(true)
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '按 Agent 建议执行' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => {
      const post = calls.find(c => c.url === '/api/workbench/decisions')
      expect(JSON.parse(String(post!.init!.body)).plan_id).toBe('ap1')
    })
  })

  it('missing rule plan and agent ok defaults basis to agent and locks rule', async () => {
    respond = todayWith([unit({ plan: null, agent: agentOk() })])
    render(Today)
    expect((await screen.findByLabelText(/Agent 建议/) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText(/规则计划/) as HTMLInputElement).disabled).toBe(true)
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '规则计划缺失，按 Agent 执行' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
    await waitFor(() => {
      const post = calls.find(c => c.url === '/api/workbench/decisions')
      expect(JSON.parse(String(post!.init!.body)).plan_id).toBe('ap1')
    })
  })

  it('missing rule plan and void agent plan still offers own levels', async () => {
    respond = todayWith([unit({ plan: null, agent: agentOk({
      plan: agentPlan({ status: 'invalid', invalid_reasons: ['no_room'] }) }) })])
    render(Today)
    expect((await screen.findByLabelText(/自定价位/) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText(/规则计划/) as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByLabelText(/Agent 建议/) as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByLabelText('入场下限')).toBeInTheDocument()
  })

  it('level refs open their tool calls', async () => {
    const levels = { entry_low: { value: '98.50', refs: ['call:2'] }, entry_high: { value: '101.50', refs: ['call:2'] },
                     stop: { value: '96.00', refs: ['call:2'] }, target1: { value: '108.00', refs: ['call:2'] } }
    const agent = agentOk({ output: { ...agentOk().output, levels } })
    respond = async (url: string) => url.includes('/agent-runs/r1')
      ? json({ ...agent, tool_calls: [...toolCallDetail().tool_calls,
          { seq: 2, phase: 'propose', tool: 'get_price_bars', args: { ticker: 'NVDA', lookback: 20 },
            result: { ref: 'call:2', data: [] }, result_sha256: '99887766'.repeat(8), called_at: '2026-10-22T22:32:00Z' }] })
      : await todayWith([unit({ agent })])()
    render(Today)
    const line = await screen.findByText(/价位引用/)
    const buttons = Array.from(line.querySelectorAll('button')).filter(b => b.textContent === 'call:2')
    expect(buttons.length).toBe(4)
    await fireEvent.click(buttons[2])
    expect(await screen.findByText(/get_price_bars/)).toBeInTheDocument()
    expect(screen.getByText(/99887766/)).toBeInTheDocument()
  })

  it('extended list shows agent status', async () => {
    respond = todayWith([], [{ ticker: 'X01', signal_date: '2026-10-22', proposed_action: 'buy',
                               rule_ids: ['trend_reclaim'], plan: null, agent_status: 'skipped: disabled' }])
    render(Today)
    await fireEvent.click(await screen.findByText(/扩展池/))
    expect(await screen.findByText(/Agent skipped: disabled/)).toBeInTheDocument()
  })
})
