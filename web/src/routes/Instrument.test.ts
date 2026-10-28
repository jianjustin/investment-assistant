import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import Instrument from './Instrument.svelte'
import * as api from '../lib/api'
import { resetConceptIndex } from '../lib/knowledge'

// props the page hands to the chart (the stub itself renders nothing)
const chartProps = vi.hoisted(() => [] as any[])

// CandleChart 依赖 canvas，jsdom 下 mock 掉
vi.mock('../lib/charts/CandleChart.svelte', async () => {
  // @ts-ignore – stub has no declaration file; only used in tests
  const Stub = (await import('./__stub__.svelte')).default
  const Recording = (anchor: unknown, props: unknown) => { chartProps.push(props); return (Stub as any)(anchor, props) }
  return { default: Recording }
})

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const chartBars = (ma: Partial<{ ma20: number | null; ma50: number | null; ma200: number | null }> = {}) =>
  ['2026-10-20', '2026-10-21', '2026-10-22'].map((date, i) => ({
    price_date: date, open: 100 + i, high: 101 + i, low: 99 + i, close: 100.5 + i, volume: 1000,
    ma20: ma.ma20 ?? 100, ma50: ma.ma50 ?? 99, ma200: ma.ma200 ?? 98,
  }))
const fundamentalsView = (ticker: string) => ({
  ticker, security_id: `US:stock:${ticker}`, currency: 'USD',
  financials: [{ period: '2026-04-01/2026-06-30', start: '2026-04-01', end: '2026-06-30', days: 91, metrics: {}, ttm: {}, warnings: [] }],
  market: { bars: [], benchmarks: { SPY: [], QQQ: [] }, quote: {}, performance: { windows: {} }, limitations: [] },
  valuation: {}, statuses: [], guidance: { records: [], comparisons: [], consensus: '未接入一致预期' }, filings: [], pit: {},
})
const view = (ticker: string, chart: { bars: unknown[]; adjustment: string } = { bars: chartBars(), adjustment: 'split_only' }) => ({
  ticker, session: '2026-10-22', bars: [], closed: [], chart,
  position: { quantity: 10, avg_cost: 100.1, opened_at: '2026-10-02T14:00:00Z' },
  filings: [{ id: 1, form: '8-K', filing_date: '2026-10-20', accepted_at: null, items: ['2.02'] }],
  news: [{ id: 2, source: 'yfinance', title: '合成新闻', url: 'https://news.example.com/2', publisher: 'W',
           published_at: '2026-10-21T12:00:00Z', fetched_at: '2026-10-21T13:00:00Z' }],
  candidates: [{ id: 'c', signal_date: '2026-10-22', action: 'buy', rule_id: 'trend_reclaim', created_at: '2026-10-22T22:30:00Z' }],
  decisions: [], trades: [],
})

let urls: string[]
beforeEach(() => {
  urls = []
  chartProps.length = 0
  resetConceptIndex()
  history.replaceState(null, '', '#instrument/NVDA')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    urls.push(String(url))
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }, { ticker: 'MU' }] })
    if (String(url).startsWith('/api/us-research/')) return json(fundamentalsView(String(url).split('/')[3].split('?')[0]))
    if (String(url).startsWith('/api/workbench/chains?')) return json(chainsView)
    if (String(url).startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
    return json(view(String(url).split('/').pop()!))
  }))
})

const chainsView = { ticker: 'NVDA', chains: [
  { signal_date: '2026-10-22', state: 'holding', mode: 'holding', version_no: 2, head_plan_id: 'hp-1',
    latest_review: { outcome: 'maintain', decided_by: 'host', created_at: '2026-10-27T22:40:00Z',
                     reason: '无新信号，复查条件未满足（下一交易日）' } },
  { signal_date: '2026-10-10', state: 'expired', mode: null, version_no: 0, head_plan_id: 'hp-0', latest_review: null },
] }

it('shows 我的补充 and agent chains list', async () => {
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByRole('heading', { name: '我的补充' })).toBeInTheDocument()
  const list = await screen.findByRole('list', { name: 'Agent 计划' })
  const rows = list.querySelectorAll(':scope > li')
  expect(rows).toHaveLength(1)                       // 进行中的链；已结束的另在折叠里
  expect(rows[0]).toHaveTextContent('2026-10-22 · 持仓期 · 第 2 版 · 最近复查 维持 · 系统规则')
  expect(rows[0].querySelector('a')!.getAttribute('href')).toBe('#plan/hp-1')
  const ended = screen.getByRole('list', { name: '已结束的链', hidden: true })
  expect(ended.closest('details')).not.toHaveAttribute('open')
  expect(ended.querySelectorAll(':scope > li')[0]).toHaveTextContent('2026-10-10 · 已到期 · 第 0 版 · 尚未复查')
  expect(urls).toContain('/api/workbench/chains?ticker=NVDA')
  expect(urls).toContain('/api/workbench/user-inputs?ticker=NVDA')
  // 只有有效链（入场期 / 持仓期）可以作为补充的作用对象
  const scope = screen.getByLabelText('作用于') as HTMLSelectElement
  expect([...scope.options].map(o => o.textContent)).toEqual(['整个标的', '2026-10-22 · 第 2 版'])
  // 页面其余部分照旧
  expect(screen.getByTestId('instrument-chart')).toBeInTheDocument()
  expect(screen.getAllByText(/趋势回踩修复/).length).toBeGreaterThan(0)
  expect(await screen.findByText('未接入一致预期')).toBeInTheDocument()
})

it('keeps the page when the chains list is unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }] })
    if (String(url).startsWith('/api/us-research/')) return json(fundamentalsView('NVDA'))
    if (String(url).startsWith('/api/workbench/chains?')) return json({ error: '迁移 026 未执行' }, 503)
    if (String(url).startsWith('/api/workbench/user-inputs')) return json({ error: '迁移 026 未执行' }, 503)
    return json(view(String(url).split('/').pop()!))
  }))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByRole('heading', { name: /NVDA · 截至/ })).toBeInTheDocument()
  expect(await screen.findByText(/Agent 计划列表不可用/)).toBeInTheDocument()
  expect(screen.getByTestId('instrument-chart')).toBeInTheDocument()
  // 迁移 026 未执行：「我的补充」写不进去，不给表单
  expect(screen.getByRole('heading', { name: '我的补充' })).toBeInTheDocument()
  expect(screen.getByText(/暂不可用/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '提交补充' })).toBeNull()
  expect(screen.queryByLabelText('正文')).toBeNull()
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('loads the ticker from the route and renders one timeline', async () => {
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByRole('heading', { name: /NVDA/ })).toBeInTheDocument()
  expect(screen.getByText(/受理时间未知/)).toBeInTheDocument()
  expect(screen.getAllByText(/趋势回踩修复/).length).toBeGreaterThan(0)
  expect(screen.getByText(/持仓 10/)).toBeInTheDocument()
  expect(urls).toContain('/api/workbench/instruments/NVDA')
})

it('switches ticker through the picker and updates the hash', async () => {
  render(Instrument, { sub: 'NVDA' })
  await screen.findByRole('heading', { name: /NVDA/ })
  await fireEvent.change(screen.getByLabelText('标的'), { target: { value: 'MU' } })
  expect(await screen.findByRole('heading', { name: /MU/ })).toBeInTheDocument()
  expect(location.hash).toBe('#instrument/MU')
})

it('shows 503 as database unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).startsWith('/api/watchlist')
    ? json({ rows: [] }) : json({ error: 'down' }, 503)))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByText(/数据库未就绪/)).toBeInTheDocument()
})

it('skips invalid-identity watchlist rows when choosing the default ticker', async () => {
  history.replaceState(null, '', '#instrument')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    urls.push(String(url))
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [
      { ticker: '688008.SH', market: null, identity_error: '证券身份无效，请删除后使用完整有效代码重新添加' },  // invalid US code
      { ticker: 'MU', market: 'US' },
    ] })
    return json(view(String(url).split('/').pop()!))
  }))
  render(Instrument, {})
  expect(await screen.findByRole('heading', { name: /MU/ })).toBeInTheDocument()
  expect(urls.some(u => u.includes('/api/workbench/instruments/688008.SH'))).toBe(false)
  expect(screen.queryByRole('option', { name: '688008.SH' })).toBeNull()
})

it('renders the chart with three moving averages', async () => {
  render(Instrument, { sub: 'NVDA' })
  await screen.findByRole('heading', { name: /NVDA/ })
  expect(screen.getByTestId('instrument-chart')).toBeInTheDocument()
  expect(screen.getByText(/拆股调整、未分红调整/)).toBeInTheDocument()
})

it('renders candles without ma200 when history is short', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).startsWith('/api/watchlist')
    ? json({ rows: [{ ticker: 'NVDA' }] })
    : json(view(String(url).split('/').pop()!, { bars: chartBars({ ma200: null }), adjustment: 'split_only' }))))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByTestId('instrument-chart')).toBeInTheDocument()
})

it('shows an empty note without bars', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).startsWith('/api/watchlist')
    ? json({ rows: [{ ticker: 'NVDA' }] })
    : json(view(String(url).split('/').pop()!, { bars: [], adjustment: 'split_only' }))))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByText('暂无日线，等下一次批处理采集')).toBeInTheDocument()
  expect(urls.some(u => u.startsWith('/api/tickers/'))).toBe(false)
})

it('renders the fundamentals section', async () => {
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByText('未接入一致预期')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '基本面' })).toBeInTheDocument()
})

it('keeps the instrument page when fundamentals fail', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).startsWith('/api/watchlist')
    ? json({ rows: [{ ticker: 'NVDA' }] })
    : String(url).startsWith('/api/us-research/') ? json({ error: 'down' }, 500)
      : json(view(String(url).split('/').pop()!))))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByRole('heading', { name: /NVDA/ })).toBeInTheDocument()
  expect(screen.getByTestId('instrument-chart')).toBeInTheDocument()
  expect(screen.getAllByText(/趋势回踩修复/).length).toBeGreaterThan(0)
  expect(await screen.findByText(/加载失败/)).toBeInTheDocument()
})


// ---- v2.6: four sections, focus, key data, annotations ----

const extra = () => ({
  holding: { quantity: 10, avg_cost: 100.1, plan_id: 'pl-rule', stop: '95.00', mode: 'trailing', t1_reached: false,
             target1: '112.00', last_close: '102.50', to_stop_pct: -0.073, to_target_pct: 0.093 },
  focus: [
    { kind: 'position', text: '持仓 10 股 · 成本 100.10 · 当前止损 95.00（按你决定的计划）· 距止损 -5.1%', link: '#review/trades',
      concepts: ['review.position', 'plan.stop'] },
    { kind: 'agent_plan', text: 'Agent 第 2 版 · 持仓期 · 入场 98.50–101.50 · 止损 96.00 · T1 108.00 · 最近复查：维持（系统规则，2026-10-27 22:40 北京）',
      link: '#plan/hp-1', concepts: ['agent.version_chain'] },
    { kind: 'trigger', text: '今天触发 趋势回踩修复（买入）', link: '#today', concepts: ['rule.trend_reclaim'] },
  ],
  key_data: {
    as_of: '2026-10-22',
    values: { last_close: '102.50', atr14: '2.23', ma20: '100.10', ma50: '99.00', ma200: '98.00', high_20: '103.00',
              low_20: '97.00', high_252: '110.00', low_252: '80.00', avg_volume_20: '1200000', volume_ratio: '1.35',
              rs20: '0.021', rs60: null },
    concepts: { last_close: 'family.bars', atr14: 'indicator.atr14', ma20: 'indicator.moving_average',
                ma50: 'indicator.moving_average', ma200: 'indicator.moving_average', high_20: 'indicator.high_low',
                low_20: 'indicator.high_low', high_252: 'indicator.high_low', low_252: 'indicator.high_low',
                avg_volume_20: 'indicator.volume_ratio', volume_ratio: 'indicator.volume_ratio',
                rs20: 'indicator.relative_strength', rs60: 'indicator.relative_strength' },
  },
  context: {
    earnings: { date: '2026-11-04', status: 'confirmed', sessions_until: 8 },
    regime: { label: 'risk_on', session: '2026-10-22' },
    sector: { etf: 'XLK', state: 'strong', rs20: 0.03, rs60: 0.05 },
  },
  plans: [
    { id: 'pl-rule', kind: 'rule', plan_version: 'plan-1', signal_date: '2026-10-22', entry_low: '98.50', entry_high: '101.50',
      stop: '94.00', target1: '112.00', valid_from: '2026-10-23', valid_until: '2026-10-29', status: 'ok', version_no: null },
    { id: 'pl-old', kind: 'rule', plan_version: 'plan-1', signal_date: '2026-09-01', entry_low: '90.00', entry_high: '92.00',
      stop: '85.00', target1: '99.00', valid_from: '2026-09-02', valid_until: '2026-09-08', status: 'ok', version_no: null },
    { id: 'hp-1', kind: 'agent', plan_version: 'agent-2', signal_date: '2026-10-22', entry_low: '98.50', entry_high: '101.50',
      stop: '96.00', target1: '108.00', valid_from: '2026-10-23', valid_until: '2026-10-29', status: 'ok', version_no: 2 },
  ],
})
const annotations = {
  markers: [{ time: '2026-10-22', position: 'belowBar', shape: 'arrowUp', text: '回踩', kind: 'candidate', refs: ['c'] }],
  segments: [{ plan_id: 'pl-rule', kind: 'rule', label: '规则', level: 'stop', from: '2026-10-23', to: '2026-10-29', value: '94.00' }],
  omitted: 2,
}
const richView = (ticker: string) => {
  const v = view(ticker)
  return { ...v, ...extra(), chart: { ...v.chart, annotations } }
}
const conceptIndexOf = (ids: string[]) => ({
  knowledge_version: 'knowledge-1', groups: [],
  concepts: ids.map(id => ({ id, ref: `concept:${id}@1`, title: `T:${id}`, group: id.split('.')[0], version: 1,
                             applies_to: [], summary: `S:${id}`, related: [] })),
})
const rich = () => vi.stubGlobal('fetch', vi.fn(async (url: string) => {
  urls.push(String(url))
  if (String(url).startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }] })
  if (String(url).startsWith('/api/us-research/')) return json(fundamentalsView('NVDA'))
  if (String(url).startsWith('/api/workbench/chains?')) return json(chainsView)
  if (String(url).startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
  if (String(url).startsWith('/api/workbench/units/')) return json({ derivation_version: 'derivation-1', trigger: [], consistency:
    { status: 'consistent', mismatches: [], missing: [] }, evidence: '证据', note: '', plan_ids: [] })
  return json(richView('NVDA'))
}))

it('four sections in order', async () => {
  rich()
  render(Instrument, { sub: 'NVDA' })
  await screen.findByRole('heading', { name: /NVDA · 截至/ })
  const names = ['信号与计划', '关键数据', '背景', '历史']
  const sections = names.map(name => screen.getByRole('region', { name }))
  names.forEach((name, i) => expect(within(sections[i]).getByRole('heading', { level: 2, name })).toBeInTheDocument())
  for (let i = 1; i < sections.length; i++)
    expect(sections[i - 1].compareDocumentPosition(sections[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  // 旧内容各归其段
  expect(within(sections[0]).getByRole('heading', { name: '我的补充' })).toBeInTheDocument()
  expect(await within(sections[2]).findByRole('heading', { name: '基本面' })).toBeInTheDocument()
  expect(within(sections[3]).getByTestId('instrument-chart')).toBeInTheDocument()
})

it('focus items render first', async () => {
  rich()
  render(Instrument, { sub: 'NVDA' })
  const list = await screen.findByRole('list', { name: '今天该关注什么' })
  const items = list.querySelectorAll(':scope > li')
  expect(items).toHaveLength(3)
  expect(items[0]).toHaveTextContent('持仓 10 股 · 成本 100.10 · 当前止损 95.00（按你决定的计划）')
  expect(items[0].querySelector('a')!.getAttribute('href')).toBe('#review/trades')
  expect(items[1].querySelector('a')!.getAttribute('href')).toBe('#plan/hp-1')
  expect(items[2]).toHaveTextContent('今天触发 趋势回踩修复（买入）')
  // the focus list is the first thing in the first section
  const section = screen.getByRole('region', { name: '信号与计划' })
  expect(section.querySelector('ul, ol')).toBe(list)
})

it('focus empty sentence from the backend is shown verbatim', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }] })
    if (String(url).startsWith('/api/us-research/')) return json(fundamentalsView('NVDA'))
    if (String(url).startsWith('/api/workbench/chains?')) return json({ ticker: 'NVDA', chains: [] })
    if (String(url).startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
    return json({ ...richView('NVDA'), focus: [{ kind: 'none', text: '今天没有触发，也没有进行中的计划或持仓', link: null, concepts: [] }] })
  }))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByText('今天没有触发，也没有进行中的计划或持仓')).toBeInTheDocument()
})

it('key data values with ConceptTerm', async () => {
  rich()
  vi.spyOn(api, 'getConcepts').mockResolvedValue(conceptIndexOf(
    ['family.bars', 'indicator.atr14', 'indicator.moving_average', 'indicator.high_low', 'indicator.volume_ratio',
     'indicator.relative_strength']))
  render(Instrument, { sub: 'NVDA' })
  const section = await screen.findByRole('region', { name: '关键数据' })
  expect(section).toHaveTextContent('截至 2026-10-22')
  const list = await within(section).findByRole('list', { name: '关键数据' })
  const rows = [...list.querySelectorAll(':scope > li')]
  const row = (label: string) => rows.find(r => r.textContent!.includes(label)) as HTMLElement
  expect(row('最近收盘')).toHaveTextContent('102.50')
  expect(row('ATR14')).toHaveTextContent('2.23')
  expect(row('MA200')).toHaveTextContent('98.00')
  expect(row('量比')).toHaveTextContent('1.35')
  expect(row('60 日')).toHaveTextContent('—')              // null stays a dash
  // each value's label carries the concept the API names
  expect(await within(row('ATR14')).findByRole('button', { name: '概念：T:indicator.atr14' })).toBeInTheDocument()
  expect(within(row('MA50')).getByRole('button', { name: '概念：T:indicator.moving_average' })).toBeInTheDocument()
  expect(within(row('252 日高')).getByRole('button', { name: '概念：T:indicator.high_low' })).toBeInTheDocument()
  expect(within(row('最近收盘')).getByRole('button', { name: '概念：T:family.bars' })).toBeInTheDocument()
  // 焦点计划 → its derivation
  expect(within(section).getByRole('link', { name: '看推导' }).getAttribute('href')).toBe('#plan/hp-1')
})

it('background shows earnings, regime and sector', async () => {
  rich()
  render(Instrument, { sub: 'NVDA' })
  const section = await screen.findByRole('region', { name: '背景' })
  expect(section).toHaveTextContent('2026-11-04')
  expect(section).toHaveTextContent('距今 8 个交易日')
  expect(section).toHaveTextContent('进攻')                  // regime label, 2026-10-22
  expect(section).toHaveTextContent('XLK')
  expect(section).toHaveTextContent('强')
  // recent news and filings live here, not candidates / decisions
  expect(section).toHaveTextContent('合成新闻')
  expect(section).toHaveTextContent('受理时间未知')
  expect(section).not.toHaveTextContent('→ 买入')
})

it('background says 未映射行业 ETF when the sector is unknown', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }] })
    if (String(url).startsWith('/api/us-research/')) return json(fundamentalsView('NVDA'))
    if (String(url).startsWith('/api/workbench/chains?')) return json({ ticker: 'NVDA', chains: [] })
    if (String(url).startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
    return json({ ...richView('NVDA'), context: { earnings: null, regime: null, sector: null } })
  }))
  render(Instrument, { sub: 'NVDA' })
  const section = await screen.findByRole('region', { name: '背景' })
  expect(section).toHaveTextContent('未映射行业 ETF')
  expect(section).toHaveTextContent('下次财报日未知')
})

it('plan list links to #plan', async () => {
  rich()
  render(Instrument, { sub: 'NVDA' })
  const history = await screen.findByRole('region', { name: '历史' })
  const list = within(history).getByRole('list', { name: '计划价位' })
  const rows = [...list.querySelectorAll(':scope > li')]
  expect(rows).toHaveLength(3)
  const agent = rows.find(r => r.textContent!.includes('第 2 版'))!
  expect(agent).toHaveTextContent('Agent')
  expect(agent).toHaveTextContent('入场 98.50–101.50 · 止损 96.00 · T1 108.00')
  expect(agent).toHaveTextContent('有效期 2026-10-23 至 2026-10-29')
  expect(agent.querySelector('a')!.getAttribute('href')).toBe('#plan/hp-1')
  expect(rows.map(r => r.querySelector('a')!.getAttribute('href'))).toEqual(['#plan/pl-rule', '#plan/pl-old', '#plan/hp-1'])
  expect(history).toHaveTextContent('另有 2 份未画')
  // 进行中的计划段只放有效期覆盖今天及之后的规则 / 自定计划
  const mine = screen.getByRole('list', { name: '当前有效的计划' })
  expect(mine.querySelectorAll(':scope > li')).toHaveLength(1)
  expect(mine.querySelector('a')!.getAttribute('href')).toBe('#plan/pl-rule')
})

it('chart receives markers and segments', async () => {
  rich()
  render(Instrument, { sub: 'NVDA' })
  await screen.findByTestId('instrument-chart')
  const props = chartProps.at(-1)
  expect(props.markers).toEqual(annotations.markers)
  expect(props.segments).toEqual(annotations.segments)
  expect(screen.getByTestId('instrument-chart')).toHaveTextContent('候选')
})

it('chart gets no annotations from an older response', async () => {
  render(Instrument, { sub: 'NVDA' })
  await screen.findByTestId('instrument-chart')
  const props = chartProps.at(-1)
  expect(props.markers ?? []).toEqual([])
  expect(props.segments ?? []).toEqual([])
})

it('trigger basis opens the unit derivation', async () => {
  rich()
  render(Instrument, { sub: 'NVDA' })
  const section = await screen.findByRole('region', { name: '信号与计划' })
  const triggers = within(section).getByRole('list', { name: '今日触发' })
  expect(triggers).toHaveTextContent('趋势回踩修复')
  await fireEvent.click(within(triggers).getByRole('button', { name: '触发依据' }))
  await waitFor(() => expect(urls).toContain('/api/workbench/units/NVDA/2026-10-22/derivation'))
})

it('existing fundamentals, timeline, chains and UserInputs still render', async () => {
  rich()
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByText('未接入一致预期')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '基本面' })).toBeInTheDocument()
  expect(screen.getByText(/受理时间未知/)).toBeInTheDocument()
  expect(await screen.findByRole('list', { name: 'Agent 计划' })).toBeInTheDocument()
  expect(await screen.findByRole('heading', { name: '我的补充' })).toBeInTheDocument()
  expect(screen.getByLabelText('作用于')).toBeInTheDocument()
  expect(screen.getAllByText(/持仓 10/).length).toBeGreaterThan(0)       // position line (+ the focus line)
  expect(screen.getByText(/拆股调整、未分红调整/)).toBeInTheDocument()
  // history timeline keeps candidate / decision / trade rows
  expect(screen.getByRole('region', { name: '历史' })).toHaveTextContent('2026-10-22 趋势回踩修复 → 买入')
})

it('a failed new block shows its reason in the matching section', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }] })
    if (String(url).startsWith('/api/us-research/')) return json(fundamentalsView('NVDA'))
    if (String(url).startsWith('/api/workbench/chains?')) return json({ ticker: 'NVDA', chains: [] })
    if (String(url).startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
    return json({ ...richView('NVDA'), focus: null, key_data: null, context: null, plans: null,
      chart: { ...richView('NVDA').chart, annotations: null },
      errors: { focus: 'f 失败', key_data: 'k 失败', context: 'c 失败', plans: 'p 失败', 'chart.annotations': 'a 失败' } })
  }))
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByRole('region', { name: '信号与计划' })).toHaveTextContent('f 失败')
  expect(screen.getByRole('region', { name: '关键数据' })).toHaveTextContent('k 失败')
  expect(screen.getByRole('region', { name: '背景' })).toHaveTextContent('c 失败')
  expect(screen.getByRole('region', { name: '历史' })).toHaveTextContent('p 失败')
  expect(screen.getByRole('region', { name: '历史' })).toHaveTextContent('a 失败')
  expect(screen.getByTestId('instrument-chart')).toBeInTheDocument()
})

it('shows the holding stop and T1 with their concepts, and keeps position facts', async () => {
  rich()
  vi.spyOn(api, 'getConcepts').mockResolvedValue(conceptIndexOf(
    ['plan.stop', 'plan.target1', 'plan.trailing_stop', 'review.position', 'agent.user_input', 'agent.version_chain']))
  render(Instrument, { sub: 'NVDA' })
  const holding = await screen.findByLabelText('持仓止损')
  expect(holding).toHaveTextContent('当前止损 95.00（移动）')
  expect(holding).toHaveTextContent('T1 112.00（未触 T1）')
  expect(holding).toHaveTextContent('距止损 -7.30% · 距 T1 +9.30%')
  const section = screen.getByRole('region', { name: '信号与计划' })
  expect(section).toHaveTextContent('持仓 10 股 · 成本 100.10')
  const labels = (await within(holding).findAllByRole('button', { name: /^概念：/ })).map(b => b.getAttribute('aria-label'))
  expect(labels).toEqual(['概念：T:plan.stop', '概念：T:plan.trailing_stop', '概念：T:plan.target1'])
  expect((await within(section).findAllByRole('button', { name: '概念：T:review.position' })).length).toBeGreaterThan(0)
  expect(within(section).getByRole('button', { name: '概念：T:agent.user_input' })).toBeInTheDocument()
  // 计划价位 and the history timeline carry their concepts too
  const history = screen.getByRole('region', { name: '历史' })
  expect(within(history).getByRole('button', { name: '概念：T:agent.version_chain' })).toBeInTheDocument()
  expect(within(history).getByRole('button', { name: '概念：T:review.position' })).toBeInTheDocument()
})

it('holding without a plan and a failed holding block', async () => {
  const respondWith = (extraKeys: Record<string, unknown>) => vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }] })
    if (String(url).startsWith('/api/us-research/')) return json(fundamentalsView('NVDA'))
    if (String(url).startsWith('/api/workbench/chains?')) return json({ ticker: 'NVDA', chains: [] })
    if (String(url).startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
    return json({ ...richView('NVDA'), ...extraKeys })
  }))
  respondWith({ holding: { ...extra().holding, stop: null, mode: null, target1: null, plan_id: null } })
  const first = render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByLabelText('持仓止损')).toHaveTextContent('无计划持仓（回撤规则看护）')
  first.unmount()
  respondWith({ holding: null, errors: { holding: 'h 失败' } })
  render(Instrument, { sub: 'NVDA' })
  expect(await screen.findByText(/当前止损与 T1 暂不可用：h 失败/)).toBeInTheDocument()
  expect(screen.queryByLabelText('持仓止损')).toBeNull()
})

it('ended chains keep their latest review reason', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).startsWith('/api/watchlist')) return json({ rows: [{ ticker: 'NVDA' }] })
    if (String(url).startsWith('/api/us-research/')) return json(fundamentalsView('NVDA'))
    if (String(url).startsWith('/api/workbench/chains?')) return json({ ticker: 'NVDA', chains: [
      { signal_date: '2026-10-10', state: 'invalidated', mode: null, version_no: 1, head_plan_id: 'hp-0',
        latest_review: { outcome: 'invalidate', decided_by: 'agent', created_at: '2026-10-20T22:40:00Z', reason: '失效条件成立：收盘跌破 95.00' } }] })
    if (String(url).startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
    return json(richView('NVDA'))
  }))
  render(Instrument, { sub: 'NVDA' })
  const ended = await screen.findByRole('list', { name: '已结束的链', hidden: true })
  expect(ended).toHaveTextContent('失效条件成立：收盘跌破 95.00')
})
