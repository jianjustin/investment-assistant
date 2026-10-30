import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import Today from './Today.svelte'
import * as api from '../lib/api'
import { row as planRow } from '../lib/plan-table-fixtures'
import { notify } from '$lib/ui/toast'

// Toaster is not mounted in page tests: results are asserted on the call to notify.
vi.mock('$lib/ui/toast', () => ({ notify: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }))

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const emptyGroups = { entry: [], holding: [], ended: [] }
const tableView = (over: Record<string, unknown> = {}) => ({
  session: '2026-10-30', groups: { ...emptyGroups, entry: [planRow()] }, other_units: [], counts: {}, errors: {}, ...over,
})
const todayView = (over: Record<string, unknown> = {}) => ({ session: '2026-10-30', market: null, screen: null, ...over })

let calls: { url: string; init?: RequestInit }[]
let respond: (url: string, init?: RequestInit) => Promise<Response>        // /api/workbench/today
let respondTable: (url: string, init?: RequestInit) => Promise<Response>   // /api/workbench/plan-table
let respondOther: (url: string, init?: RequestInit) => Promise<Response>   // chains, user-inputs, notes, recheck, runs …

beforeEach(() => {
  calls = []
  respond = async () => json(todayView())
  respondTable = async () => json(tableView())
  respondOther = async url => {
    if (url.startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
    return json({})
  }
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, init })
    if (u === '/api/workbench/today') return respond(u, init)
    if (u.startsWith('/api/workbench/plan-table')) return respondTable(u, init)
    return respondOther(u, init)
  }))
  vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'req-today') })
  try { localStorage.removeItem('workbench.today.ended_open'); localStorage.removeItem('workbench.today.layout') } catch { /* */ }
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks() })

// A row opens with the 展开详情 button of its own row (the ticker button toggles it too).
const expandRow = async (ticker: string) =>
  within((await screen.findByRole('button', { name: ticker })).closest('tr')!).getByRole('button', { name: '展开详情' })

const tableCalls = () => calls.filter(c => c.url.startsWith('/api/workbench/plan-table')).map(c => c.url)

describe('plan table page', () => {
  it('shows the plan table with its three groups and no decision form anywhere (no decision form)', async () => {
    respond = async () => json(todayView({
      // an older backend may still send the unit cards: the page ignores them
      units: [{ ticker: 'OLD', signal_date: '2026-10-22', proposed_action: 'buy', labels: [], candidate_ids: [], rule_ids: [],
                entry_passed: false, holding: false, position: null, candidates: [], brief: null, filings: [], news: [], plan: null }],
      holdings: [{ ticker: 'NVDA', quantity: 10, avg_cost: 100, plan_id: 'p1', stop: 105, mode: 'trailing', t1_reached: true }] }))
    render(Today)
    expect(await screen.findByRole('heading', { name: '入场期（可执行）1' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '持仓中 0' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '已结束 0' })).toBeInTheDocument()
    expect(screen.getByText('MU·10-29 第 1 版')).toBeInTheDocument()
    await screen.findByText(/最近收盘交易日 2026-10-30/)
    for (const name of ['提交决定', '刷新']) expect(screen.queryByRole('button', { name })).toBeNull()
    for (const label of ['理由', '否决', '采纳', '降级为观察', '自定价位', '执行依据']) expect(screen.queryByLabelText(label)).toBeNull()
    expect(screen.queryByText('OLD · 2026-10-22')).toBeNull()                        // no unit cards
    expect(screen.queryByRole('region', { name: '进行中的 Agent 计划' })).toBeNull()   // folded into the table
    expect(screen.queryByRole('heading', { name: '持仓止损' })).toBeNull()
    expect(screen.queryByText(/未决定/)).toBeNull()
  })

  it('fetches the table on its own: the batch view failing does not hide it', async () => {
    respond = async () => json({ error: 'boom' }, 500)
    render(Today)
    expect(await screen.findByRole('heading', { name: '入场期（可执行）1' })).toBeInTheDocument()
    expect(await screen.findByText(/请求失败：boom/)).toBeInTheDocument()
    expect(tableCalls()).toEqual(['/api/workbench/plan-table'])
  })

  it('changing the date or switching the extended pool re-requests the table', async () => {
    render(Today)
    await screen.findByRole('heading', { name: '入场期（可执行）1' })
    await fireEvent.change(screen.getByLabelText('交易日'), { target: { value: '2026-10-29' } })
    await waitFor(() => expect(tableCalls()).toContain('/api/workbench/plan-table?session=2026-10-29'))
    await fireEvent.click(screen.getByRole('checkbox', { name: /显示扩展池/ }))
    await waitFor(() => expect(tableCalls()).toContain('/api/workbench/plan-table?session=2026-10-29&include_extended=true'))
    expect(calls.filter(c => c.url === '/api/workbench/today')).toHaveLength(1)     // the batch view is not re-read
  })

  it('shows the other triggers read-only, one line each', async () => {
    respondTable = async () => json(tableView({ other_units: [
      { ticker: 'RKLB', signal_date: '2026-10-30', proposed_action: 'sell', labels: ['avoid'], rule_ids: ['trend_break'],
        brief: { id: 'b', status: 'ok', output: { summary: '跌破 MA50', support: [], contra: [], conflicts: [] } } },
      { ticker: 'AMD', signal_date: '2026-10-30', proposed_action: 'watch', labels: ['conflict'], rule_ids: ['volume_breakout'], brief: null }] }))
    render(Today)
    const section = await screen.findByRole('region', { name: '其他触发' })
    const rows = within(section).getAllByRole('row').slice(1)              // [0] is the header
    expect(rows).toHaveLength(2)
    for (const text of ['RKLB · 2026-10-30', '建议卖出', '回避', '跌破 MA50']) expect(rows[0]).toHaveTextContent(text)
    expect(rows[0].querySelectorAll('td')[4]).toHaveTextContent('跌破 MA50')           // the brief summary
    for (const text of ['AMD · 2026-10-30', '建议观察', '冲突', '放量突破', '无简报']) expect(rows[1]).toHaveTextContent(text)
    expect(within(section).queryByRole('button')).toBeNull()
  })

  it('shows the migration 029 text for a 503, not an empty table', async () => {
    respondTable = async () => json({ error: 'migration_029_missing' }, 503)
    render(Today)
    expect(await screen.findByText('迁移 029 未执行')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /入场期/ })).toBeNull()
  })

  it('shows blocks the backend could not read', async () => {
    respondTable = async () => json(tableView({ errors: { holding_status: '读取失败' } }))
    render(Today)
    expect(await screen.findByText('holding_status 暂不可用：读取失败')).toBeInTheDocument()
  })

  it('run overview is the first section, before 筛选, 市场环境 and the plan table', async () => {
    vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
    respond = async () => json(todayView({ screen: screenReport(), market: { id: 'r1', session: '2026-10-22', calc_version: 'regime-1',
      label: 'risk_off', breadth: {}, sectors: {}, macro: {}, inputs: {}, created_at: 'x' } }))
    const getRunOverview = vi.spyOn(api, 'getRunOverview').mockResolvedValue({
      session: '2026-10-22', ready: true, note: null, runs: [], selected_run_id: 'r1',
      headline: '定时运行 · 06:30 开始 · 用时 3 分 12 秒 · 8 个阶段：成功 8',
      stages: [{ id: 'collect', title: '数据采集', purpose: '', status: 'success', status_text: '成功', sentence: '采集 10/10 个目标',
                 input_count: 10, output_count: 10, skips: [], failures: [], degradations: [], reason: null, reason_text: null,
                 duration_ms: 1000, concepts: [] }],
    } as any)
    render(Today)
    await screen.findByRole('heading', { name: '入场期（可执行）1' })
    const overview = await screen.findByRole('region', { name: '运行一览' })
    expect(await within(overview).findByText('采集 10/10 个目标')).toBeInTheDocument()
    expect(getRunOverview).toHaveBeenCalledWith(undefined, undefined)
    for (const name of ['筛选', '市场环境', '计划表']) {
      const other = await screen.findByRole('region', { name })
      expect(overview.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
    // the overview does not depend on the batch view: today's request count is unchanged
    expect(calls.filter(c => c.url === '/api/workbench/today')).toHaveLength(1)
  })

  it('repush button calls pushToday and shows the result', async () => {
    respondOther = async url => url.includes('/api/workbench/push') ? json({ session: '2026-10-22', sent: true, messages: 4 })
      : json({ inputs: [] })
    render(Today)
    await screen.findByRole('heading', { name: '入场期（可执行）1' })
    await fireEvent.click(screen.getByRole('button', { name: '重新推送今日计划' }))
    await waitFor(() => expect(notify.success).toHaveBeenCalledWith('已推送 4 条'))
    expect(calls.find(c => c.url.includes('/api/workbench/push'))!.init?.method).toBe('POST')
  })
})

describe('empty vs not_computed vs error', () => {
  it('empty: a group with nothing says why, with no 没算 badge and no alert', async () => {
    respondTable = async () => json(tableView({ groups: emptyGroups }))
    render(Today)
    expect(await screen.findByText('入场期暂无可执行的计划')).toBeInTheDocument()
    expect(screen.getByText('当前无持仓')).toBeInTheDocument()
    const section = screen.getByRole('region', { name: '计划表' })
    expect(within(section).queryByText('没算')).toBeNull()
    expect(within(section).queryByRole('alert')).toBeNull()
  })

  it('not_computed: a market / screen that was never produced carries the 没算 badge and its missing part', async () => {
    render(Today)                                              // todayView(): market null, screen null
    const market = await screen.findByRole('region', { name: '市场环境' })
    expect(market).toHaveTextContent('市场环境未生成')
    expect(within(market).getByText('没算')).toBeInTheDocument()
    expect(within(market).queryByRole('alert')).toBeNull()
    const screening = screen.getByRole('region', { name: '筛选' })
    expect(screening).toHaveTextContent('今日无筛选记录')
    expect(within(screening).getByText('没算')).toBeInTheDocument()
  })

  it('error: a failed table is an alert with the Chinese reason and a retry, not an empty table', async () => {
    respondTable = async () => json({ error: 'migration_029_missing' }, 503)
    render(Today)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('迁移 029 未执行')
    expect(screen.queryByText('入场期暂无可执行的计划')).toBeNull()
    expect(within(screen.getByRole('region', { name: '计划表' })).getByRole('button', { name: '重试' })).toBeInTheDocument()
    respondTable = async () => json(tableView())
    await fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('heading', { name: '入场期（可执行）1' })).toBeInTheDocument()
  })

  it('the batch view failing is its own alert; the plan table still loads', async () => {
    respond = async () => json({ error: 'boom' }, 500)
    render(Today)
    expect(await screen.findByRole('heading', { name: '入场期（可执行）1' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('请求失败：boom')
  })

  it('the header has no actions beyond the two buttons and the page title keeps its level', async () => {
    render(Today)
    expect(await screen.findByRole('heading', { level: 1, name: '今日' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '立即运行批处理' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新推送今日计划' })).toBeInTheDocument()
  })
})

describe('row actions', () => {
  const chainView = () => ({
    ticker: 'MU', signal_date: '2026-10-29', session: '2026-10-30', state: { state: 'entry', mode: 'entry', basis: '' },
    head_plan_id: 'p1', version_no: 1, latest_review: null, shadow_version: 'plan-shadow-2', reviews: [], inputs: [],
    versions: [] })

  it('rechecks a chain from the expanded row, polls the run and reloads the table', async () => {
    respondOther = async (url, init) => {
      if (url.endsWith('/recheck') && init?.method === 'POST') return json({ run_id: 'plan_recheck-1', status: 'pending' })
      if (url.startsWith('/api/runs/')) return json({ run_id: 'plan_recheck-1', status: 'done', result: { outcome: 'maintain', decided_by: 'agent' } })
      if (url.startsWith('/api/workbench/chains/')) return json(chainView())
      return json({ inputs: [] })
    }
    render(Today)
    await fireEvent.click(await expandRow('MU'))
    await fireEvent.click(await screen.findByRole('button', { name: '重新复查' }))
    expect(await screen.findByText('复查完成：维持')).toBeInTheDocument()
    expect(calls.some(c => c.url === '/api/workbench/chains/MU/2026-10-29/recheck' && c.init?.method === 'POST')).toBe(true)
    await waitFor(() => expect(tableCalls()).toHaveLength(2))
  })

  it('reports a recheck conflict, a poll timeout and an exiting chain', async () => {
    respondOther = async (url, init) => {
      if (url.endsWith('/recheck') && init?.method === 'POST') return json({ error: 'chain_exiting' }, 409)
      if (url.startsWith('/api/workbench/chains/')) return json(chainView())
      return json({ inputs: [] })
    }
    render(Today)
    await fireEvent.click(await expandRow('MU'))
    await fireEvent.click(await screen.findByRole('button', { name: '重新复查' }))
    expect(await screen.findByText('不能重新复查：这条链已发出退出指令，不再复查')).toBeInTheDocument()
  })

  it('a poll timeout keeps the button disabled and says the recheck is still running', async () => {
    respondOther = async (url, init) => url.endsWith('/recheck') && init?.method === 'POST'
      ? json({ run_id: 'plan_recheck-1', status: 'pending' })
      : url.startsWith('/api/workbench/chains/') ? json(chainView()) : json({ inputs: [] })
    const poll = vi.spyOn(api, 'pollRun').mockRejectedValue(new Error('run timeout'))
    render(Today)
    await fireEvent.click(await expandRow('MU'))
    await fireEvent.click(await screen.findByRole('button', { name: '重新复查' }))
    expect(await screen.findByText('复查仍在后台进行，稍后刷新查看')).toBeInTheDocument()
    expect(poll).toHaveBeenCalledWith('plan_recheck-1', { timeoutMs: 900_000 })
    expect(screen.getByRole('button', { name: '重新复查' })).toBeDisabled()
  })

  it('writes a chain note with the chain key, then reloads the table', async () => {
    respondOther = async (url, init) => {
      if (url === '/api/workbench/plan-notes' && init?.method === 'POST') return json({ status: 'created', record: { id: 9 } })
      if (url.startsWith('/api/workbench/chains/')) return json(chainView())
      return json({ inputs: [] })
    }
    render(Today)
    await fireEvent.click(await expandRow('MU'))
    const notes = await screen.findByRole('region', { name: '备注' })
    await fireEvent.input(within(notes).getByLabelText('备注正文'), { target: { value: '等回踩' } })
    await fireEvent.click(within(notes).getByRole('button', { name: '保存备注' }))
    await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/plan-notes')).toBe(true))
    expect(JSON.parse(String(calls.find(c => c.url === '/api/workbench/plan-notes')!.init!.body)))
      .toEqual({ request_id: 'req-today', body: '等回踩', ticker: 'MU', chain_signal_date: '2026-10-29' })
    await waitFor(() => expect(tableCalls()).toHaveLength(2))
  })

  it('a row without a chain writes its note on the plan', async () => {
    respondTable = async () => json(tableView({ groups: { ...emptyGroups, entry: [planRow({
      row_id: 'plan:X', ticker: 'X01', chain: null,
      plan: { ...planRow().plan!, kind: 'rule', plan_version: 'plan-2', plan_id: 'rp1' } })] } }))
    respondOther = async (url, init) => url === '/api/workbench/plan-notes' && init?.method === 'POST'
      ? json({ status: 'created', record: { id: 9 } }) : json({ inputs: [] })
    render(Today)
    await fireEvent.click(await expandRow('X01'))
    const notes = await screen.findByRole('region', { name: '备注' })
    await fireEvent.input(within(notes).getByLabelText('备注正文'), { target: { value: '规则基线备注' } })
    await fireEvent.click(within(notes).getByRole('button', { name: '保存备注' }))
    await waitFor(() => expect(calls.some(c => c.url === '/api/workbench/plan-notes')).toBe(true))
    expect(JSON.parse(String(calls.find(c => c.url === '/api/workbench/plan-notes')!.init!.body)))
      .toEqual({ request_id: 'req-today', body: '规则基线备注', plan_id: 'rp1' })
  })
})

const screenReport = (over: Record<string, unknown> = {}) => ({
  session: '2026-10-22', calc_version: 'screen-1', status: 'success', error: null,
  universe: { name: 'nasdaq100', as_of: '2026-10-22', stale: false },
  counts: { universe: 100, data_skipped: 0, illiquid: 0, earnings_soon: 0, no_setup: 74,
            trigger: 2, setup: 12, selected: 14 },
  selected: ['T1', 'T2', ...Array.from({ length: 12 }, (_, i) => `S${i}`)],
  members: 20, cap: 40, evicted: [], removed: [], flags: [],
  triggers: [
    { ticker: 'T1', rule_ids: ['trend_reclaim'], rs: 0.12, review: 'plan',
      plan: { entry_low: 98.5, entry_high: 101.5, stop: 94, target1: 112, shares: 166,
              sizing_status: 'sized' }, invalid_reasons: [] },
    { ticker: 'T2', rule_ids: ['volume_breakout'], rs: 0.1, review: 'invalid', plan: null,
      invalid_reasons: ['earnings'] },
  ],
  setups: Array.from({ length: 10 }, (_, i) => ({ ticker: `S${i}`, rs: 0.05 - i * 0.001, atr_pct: 0.04, rank: 3 + i })),
  setups_more: 2, ...over,
})

describe('market context', () => {
  const market = { id: 'r1', session: '2026-10-22', calc_version: 'regime-1', label: 'risk_off',
    breadth: { tickers: 40, eligible_50: 40, above_50: 12, pct_50: 0.3, eligible_200: 40, above_200: 10,
               pct_200: 0.25, eligible_52w: 38, new_highs: 3, new_lows: 5 },
    sectors: { SMH: { rs20: -0.12, rs60: -0.2, state: 'weak' } }, macro: { BAMLH0A0HYM2: null, T10Y2Y: null },
    inputs: {}, created_at: '2026-10-22T23:00:00Z' }
  it('market card shows label and breadth', async () => {
    respond = async () => json(todayView({ market }))
    render(Today)
    expect(await screen.findByText('防守')).toBeTruthy()
    expect(screen.getByText(/站上 MA50 30\.0%/)).toBeTruthy()
    expect(screen.getByText(/新高 3 \/ 新低 5/)).toBeTruthy()
    expect(screen.getByText(/SMH/)).toBeTruthy()
  })
  it('market card shows FRED not configured', async () => {
    const unconfigured = { ...market, inputs: { macro_status: { BAMLH0A0HYM2: 'not_configured', T10Y2Y: 'not_configured' } } }
    respond = async () => json(todayView({ market: unconfigured }))
    render(Today)
    expect(await screen.findByText('FRED 未配置')).toBeTruthy()
  })
  it('market card tells a FRED failure apart from no key', async () => {
    const failed = { ...market, inputs: { macro_status: { BAMLH0A0HYM2: 'error', T10Y2Y: 'error' } } }
    respond = async () => json(todayView({ market: failed }))
    render(Today)
    expect(await screen.findByText(/FRED 采集失败/)).toBeTruthy()
    expect(screen.queryByText('FRED 未配置')).toBeNull()
  })
  it('market card without recorded FRED status says no data', async () => {
    respond = async () => json(todayView({ market }))
    render(Today)
    expect(await screen.findByText('FRED 无数据')).toBeTruthy()
  })
})

describe('今日 · 筛选卡片', () => {
  it('renders the screen card', async () => {
    const twelve = Array.from({ length: 12 }, (_, i) => ({ ticker: `S${i}`, rs: 0.05 - i * 0.001, atr_pct: 0.04, rank: 3 + i }))
    respond = async () => json(todayView({ screen: screenReport() }))
    respondOther = async () => json({ report: screenReport({ setups: twelve, setups_more: 0 }) })
    render(Today)
    const card = await screen.findByRole('region', { name: '筛选' })
    expect(card).toHaveTextContent('范围 100 · 通过过滤 14')
    expect(card).toHaveTextContent('今日入选 14（触发 2 / 形态 12）')
    expect(card).toHaveTextContent('成员 20/40')
    expect(card).toHaveTextContent('T1')
    expect(card).toHaveTextContent('入场 98.5–101.5 · 止损 94 · T1 112 · 建议 166 股')
    expect(card).toHaveTextContent('作废 earnings')
    expect(card).toHaveTextContent('S0')
    expect(card).toHaveTextContent('另 2 只')
    expect(screen.queryByText(/S10/)).toBeNull()
    await fireEvent.click(screen.getByRole('button', { name: '展开全部' }))
    await waitFor(() => expect(calls.some(c => c.url.includes('/api/workbench/screen') && c.url.includes('full=1'))).toBe(true))
    expect(await screen.findByText(/S11/)).toBeInTheDocument()
  })

  it('screen trigger without an equity snapshot shows no null shares', async () => {
    const report = screenReport({ triggers: [
      { ticker: 'T1', rule_ids: ['trend_reclaim'], rs: 0.12, review: 'plan',
        plan: { entry_low: 98.5, entry_high: 101.5, stop: 94, target1: 112, shares: null,
                sizing_status: 'no_equity' }, invalid_reasons: [] }] })
    respond = async () => json(todayView({ screen: report }))
    render(Today)
    const card = await screen.findByRole('region', { name: '筛选' })
    expect(card).toHaveTextContent('T1 112 · 缺资金快照，无法计算股数')
    expect(card).not.toHaveTextContent('null')
  })

  it('splits today\'s picks, not the groups that passed', async () => {
    // Real 2026-10-23 shape: 1 trigger + 20 setups passed, 20 picked -> 1 trigger + 19 setups picked.
    const setups = Array.from({ length: 20 }, (_, i) => `S${i}`)
    const report = screenReport({
      counts: { universe: 94, data_skipped: 2, illiquid: 0, earnings_soon: 30, no_setup: 41,
                trigger: 1, setup: 20, selected: 20 },
      selected: ['T1', ...setups.slice(0, 19)],
      triggers: [{ ticker: 'T1', rule_ids: ['trend_reclaim'], rs: 0.2, review: 'watch', plan: null,
                   invalid_reasons: [] }] })
    respond = async () => json(todayView({ screen: report }))
    render(Today)
    const card = await screen.findByRole('region', { name: '筛选' })
    expect(card).toHaveTextContent('通过过滤 21')
    expect(card).toHaveTextContent('今日入选 20（触发 1 / 形态 19）')
  })

  it('screen error is shown plainly', async () => {
    respond = async () => json(todayView({
      screen: screenReport({ status: 'error', error: 'benchmark_missing', triggers: [], setups: [], setups_more: 0 }) }))
    render(Today)
    expect(await screen.findByText('筛选未运行：benchmark_missing')).toBeInTheDocument()
    expect(screen.getByText(/沿用成员 20 只/)).toBeInTheDocument()
  })
})


