import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import PlanTable from './PlanTable.svelte'
import { endedRow, groups, holdRow, holdingStatus, row } from '../plan-table-fixtures'
import type { PlanTableGroups } from '../workbench'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const chainView = () => ({
  ticker: 'MU', signal_date: '2026-10-29', session: '2026-10-30',
  state: { state: 'entry', mode: 'entry', basis: '尚未成交' }, head_plan_id: 'p1', version_no: 1, latest_review: null,
  shadow_version: 'plan-shadow-2', reviews: [], inputs: [],
  versions: [{ version_no: 1, plan_id: 'p1', origin: 'signal', supersedes_plan_id: null, agent_run_id: 'run-1',
    cutoff_at: '2026-10-29T22:30:00Z', as_of_session: '2026-10-29', created_at: '2026-10-29T22:31:00Z', is_head: true,
    diff: null, changes: [], shadow: null,
    plan: { id: 'p1', status: 'ok', invalid_reasons: [], sizing: { status: 'sized', shares: 120 } },
    run: { id: 'run-1', mode: 'propose', agent_version: 'agent-3', model: 'gpt-test', status: 'ok', reason: null,
           cutoff_at: '', input_tokens: 1, output_tokens: 1, created_at: '2026-10-29T22:31:00Z',
           output: { action: 'buy', summary: '回踩修复放量', levels: null, thesis: [], invalidation: [], review_when: [] },
           counter: null } }],
})

let calls: string[]
beforeEach(() => {
  calls = []
  try { localStorage.removeItem('workbench.today.ended_open'); localStorage.removeItem('workbench.today.layout') } catch { /* */ }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(String(url))
    if (String(url).startsWith('/api/workbench/chains/')) return json(chainView())
    if (String(url).startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
    return json({})
  }))
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

const mount = (g: PlanTableGroups = groups(), over: Record<string, unknown> = {}) =>
  render(PlanTable, { groups: g, onRecheck: vi.fn(), onNote: vi.fn(async () => {}), ...over })

describe('PlanTable groups', () => {
  it('shows three groups with counts and the entry row in full', () => {
    mount()
    expect(screen.getByRole('heading', { name: '入场期（可执行）1' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '持仓中 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '已结束 1' })).toBeInTheDocument()
    const table = screen.getByRole('table', { name: '入场期计划' })
    const r = within(table).getAllByRole('row')[1]
    expect(r).toHaveTextContent('MU')
    expect(r).toHaveTextContent('MU·10-29 第 1 版')
    expect(r).toHaveTextContent('买入')
    expect(r).toHaveTextContent('区间限价 95.10–97.30')
    expect(r).toHaveTextContent('91.40')
    expect(r).toHaveTextContent('104.70')
    expect(r).toHaveTextContent('120 股')
    expect(r).toHaveTextContent('2026-10-31 至 2026-11-04')
    expect(r).toHaveTextContent('开在 95.10–97.30：开盘买入 120 股')
    expect(r).toHaveTextContent('高开过 97.30：不追，挂 97.30 限价等回落')
    expect(r).toHaveTextContent('低开：≤ 91.40 作废；否则回升到 95.10 时买入')
    expect(r).toHaveTextContent('有效期至 11-04 收盘仍未成交')
    expect(r).toHaveTextContent('收盘跌破 92.00（最近判定：未成立）')
    expect(r).toHaveTextContent('入场期 · 今日修订（再次触发）')
    expect(r).toHaveTextContent('入场期，未成交')
    expect(r).toHaveTextContent('备注 1')
  })

  it('prints the host diff and the change sentences of the day in the status cell', () => {
    mount(groups({ entry: [row({ status: { label: '入场期 · 今日修订（再次触发）', execution: 'pending',
      changes_text: ['再次触发（趋势回踩修复，10-30），沿用价位，有效期延至 11-05'],
      diff: [{ field: 'valid_until', before: '2026-11-04', after: '2026-11-05' }, { field: 'stop', before: '91.40', after: '92.00' }] } })] }))
    const table = screen.getByRole('table', { name: '入场期计划' })
    expect(table).toHaveTextContent('变化：再次触发（趋势回踩修复，10-30），沿用价位，有效期延至 11-05')
    expect(table).toHaveTextContent('相对上版：有效期至 2026-11-04 → 2026-11-05；止损 91.40 → 92.00')
  })

  it('writes a retrigger under the chain cell instead of adding a row', () => {
    mount()
    const table = screen.getByRole('table', { name: '入场期计划' })
    expect(within(table).getAllByRole('row')).toHaveLength(2)         // head + one chain row
    expect(table).toHaveTextContent('10-30 再次触发 → 第 1 版')
  })

  it('holding rows swap the opening columns for the status line and the instruction', () => {
    mount(groups({ holding: [holdRow(), holdRow({
      row_id: 'chain:MU2', ticker: 'XYZ',
      holding: holdingStatus({ ticker: 'XYZ', instruction: 'exit', exit_reason: 'stop_touched', reason: '止损触及（91.00）' }) as any }),
      holdRow({ row_id: 'chain:T1', ticker: 'T1X', holding: holdingStatus({ ticker: 'T1X', instruction: 'sell_half', t1_reached: true, to_t1_pct: null }) as any })] }))
    const table = screen.getByRole('table', { name: '持仓计划' })
    expect(table).toHaveTextContent('AMD 持有 4/10 天 · 距止损 −6.96% · 距 T1 +7.59% · 现 +0.6R · 继续持有：无新信号，复查条件未满足')
    expect(table).not.toHaveTextContent('开盘：区间内')
    expect(table).toHaveTextContent('已采纳（10-22 成交 20 股）')
    const pill = (key: string) => table.querySelector(`[data-domain="instruction"][data-status="${key}"]`)!
    expect(pill('exit')).toHaveTextContent('次一交易日开盘卖出')
    expect(pill('exit')).toHaveAttribute('data-tone', 'danger')
    expect(pill('sell_half')).toHaveTextContent('到 T1：卖出一半，余下按移动止损')
    expect(pill('sell_half')).toHaveAttribute('data-tone', 'warn')
    expect(pill('hold')).toHaveAttribute('data-tone', 'neutral')
  })

  it('flags a holding whose status row was not written and shows the old-version defaults note', () => {
    mount(groups({ holding: [holdRow({ holding: holdingStatus({ stale: true }) as any })],
                   entry: [row({ plan: { ...row().plan!, defaults_applied: true } })] }))
    expect(screen.getByText('今日持仓状态未写入（每日复查失败），以下为现算')).toBeInTheDocument()
    expect(screen.getByText('旧版计划，执行字段按默认值显示')).toBeInTheDocument()
  })

  it('says so when a group is empty', () => {
    mount(groups({ entry: [], holding: [], ended: [] }))
    expect(screen.getByText('入场期暂无可执行的计划')).toBeInTheDocument()
    expect(screen.getByText('当前无持仓')).toBeInTheDocument()
  })
})

describe('instruction and execution pills', () => {
  it('instruction pill text: the instruction wording from the backend, in the vocabulary tone', () => {
    mount(groups({ holding: [holdRow({ holding: holdingStatus({ instruction: 'no_plan', reason: '' }) as any }), holdRow({
      row_id: 'chain:X', ticker: 'XYZ', holding: holdingStatus({ ticker: 'XYZ', instruction: 'sell_half', t1_reached: true }) as any })] }))
    const table = screen.getByRole('table', { name: '持仓计划' })
    const pills = [...table.querySelectorAll('[data-domain="instruction"]')]
    expect(pills.map(p => p.getAttribute('data-status'))).toEqual(['no_plan', 'sell_half'])
    expect(pills[0]).toHaveAttribute('data-tone', 'info')
    expect(pills[1]).toHaveTextContent('到 T1：卖出一半，余下按移动止损')
    expect(pills[1]).toHaveAttribute('data-tone', 'warn')
  })

  it('the execution wording is a pill whose tone comes from the execution vocabulary', () => {
    mount()
    const adopted = screen.getByRole('table', { name: '持仓计划' }).querySelector('[data-domain="execution"]')!
    expect(adopted).toHaveTextContent('已采纳（10-22 成交 20 股）')
    expect(adopted).toHaveAttribute('data-tone', 'success')
    expect(screen.getByRole('table', { name: '入场期计划' }).querySelector('[data-domain="execution"]')).toHaveAttribute('data-tone', 'info')
  })

  it('a missing price or plan says 没算, never a dash', () => {
    mount(groups({ entry: [row({ plan: null, open_scenarios: [], chain: null })] }))
    const table = screen.getByRole('table', { name: '入场期计划' })
    expect(table).not.toHaveTextContent('—')
    expect(within(table).getAllByText('没算').length).toBeGreaterThan(0)
  })
})

describe('ended group', () => {
  it('ended group muted and collapsible: collapsed by default, the toggle persists, the rows are greyed', async () => {
    mount()
    expect(screen.queryByTestId('ended-group')).toBeNull()
    expect(screen.queryByText('已过期（未执行）')).toBeNull()
    const toggle = screen.getByRole('button', { name: '已结束 1' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await fireEvent.click(toggle)
    expect(localStorage.getItem('workbench.today.ended_open')).toBe('1')
    const group = screen.getByTestId('ended-group')
    expect(group.className).toContain('text-muted-foreground')
    const table = within(group).getByRole('table', { name: '已结束计划' })
    expect(table.querySelector('tbody tr[data-muted="true"]')).not.toBeNull()
    // the status stays a pill with its own tone (an ended chain is neutral), whatever the row's greyed text
    const status = within(table).getByText('已过期（未执行）').closest('[data-slot="badge"]')!
    expect(status).toHaveAttribute('data-domain', 'chain')
    expect(status).toHaveAttribute('data-tone', 'neutral')
    expect(table).toHaveTextContent('2026-10-28')
    await fireEvent.click(toggle)
    expect(localStorage.getItem('workbench.today.ended_open')).toBe('0')
    expect(screen.queryByTestId('ended-group')).toBeNull()
  })

  it('opens on load when the stored flag says so', () => {
    localStorage.setItem('workbench.today.ended_open', '1')
    mount()
    expect(screen.getByTestId('ended-group')).toBeInTheDocument()
  })

  it('stays collapsed when localStorage throws, and still opens for this page', async () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') },
      removeItem: () => { throw new Error('denied') },
    })
    mount()
    expect(screen.queryByTestId('ended-group')).toBeNull()
    await fireEvent.click(screen.getByRole('button', { name: '已结束 1' }))
    expect(screen.getByTestId('ended-group')).toBeInTheDocument()
  })
})

describe('narrow screens', () => {
  const narrow = () => vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('max-width: 767px'), media: q,
    addEventListener: () => {}, removeEventListener: () => {} }))

  it('narrow cards: each row folds into a card with the three opening cases stacked, no horizontal table', () => {
    narrow()
    mount()
    expect(screen.queryByRole('table', { name: '入场期计划' })).toBeNull()
    const cards = screen.getAllByRole('listitem').filter(li => li.querySelector('dl'))
    expect(cards).toHaveLength(2)                                      // entry + holding; ended is collapsed
    const entry = cards[0]
    const field = (label: string) => [...entry.querySelectorAll('dt')].find(dt => dt.textContent === label)!.nextElementSibling!
    expect(field('开盘·区间内')).toHaveTextContent('开在 95.10–97.30：开盘买入 120 股')
    expect(field('开盘·高开')).toHaveTextContent('高开过 97.30：不追，挂 97.30 限价等回落')
    expect(field('开盘·低开')).toHaveTextContent('低开：≤ 91.40 作废；否则回升到 95.10 时买入')
    expect(field('价位')).toHaveTextContent('区间限价 95.10–97.30 · 止损 91.40 · T1 104.70 · 120 股')
    expect(field('动作')).toHaveTextContent('买入')
    expect(field('链与版本')).toHaveTextContent('MU·10-29 第 1 版')
    expect(cards[1]).toHaveTextContent('继续持有')
  })

  it('narrow cards keep the 动作 badge, also for a plan the Agent passes on', () => {
    narrow()
    mount(groups({ entry: [row({ plan: { ...row().plan!, action: 'pass' } })], holding: [] }))
    const card = screen.getAllByRole('listitem').find(li => li.querySelector('dl'))!
    const field = (label: string) => [...card.querySelectorAll('dt')].find(dt => dt.textContent === label)!.nextElementSibling!
    expect(field('动作')).toHaveTextContent('不建议买入')
  })

  it('narrow cards: a card opens its detail with the row button, and the ticker still toggles', async () => {
    narrow()
    mount()
    const card = screen.getAllByRole('listitem').filter(li => li.querySelector('dl'))[0]
    await fireEvent.click(within(card).getByRole('button', { name: '展开 MU' }))
    expect(await screen.findByTestId('row-detail')).toBeInTheDocument()
    await fireEvent.click(within(card).getByRole('button', { name: 'MU' }))
    expect(screen.queryByTestId('row-detail')).toBeNull()
  })

  it('an ended row is a muted card', async () => {
    narrow()
    mount()
    await fireEvent.click(screen.getByRole('button', { name: '已结束 1' }))
    const ended = within(screen.getByTestId('ended-group')).getAllByRole('listitem').find(li => li.querySelector('dl'))!
    expect(ended).toHaveAttribute('data-muted', 'true')
    expect(ended).toHaveTextContent('已过期（未执行）')
  })

  it('renders a table when matchMedia is missing', () => {
    mount()
    expect(screen.getByRole('table', { name: '入场期计划' })).toBeInTheDocument()
  })
})

describe('row expansion', () => {
  it('opens the Agent card without any decision form, and loads the chain once', async () => {
    const onExpand = vi.fn()
    mount(groups(), { onExpand })
    await fireEvent.click(screen.getByRole('button', { name: '展开 MU' }))
    expect(onExpand).toHaveBeenCalledWith(expect.objectContaining({ ticker: 'MU' }), true)
    const detail = await screen.findByTestId('row-detail')
    expect(await within(detail).findByRole('region', { name: 'Agent 计划' })).toBeInTheDocument()
    expect(calls).toContain('/api/workbench/chains/MU/2026-10-29')
    // no decision form
    expect(screen.queryByRole('button', { name: '提交决定' })).toBeNull()
    expect(screen.queryByLabelText('理由')).toBeNull()
    expect(screen.queryByLabelText('否决')).toBeNull()
    expect(screen.queryByLabelText('自定价位')).toBeNull()
    // baseline in one line, version link, discuss, my input, note input
    expect(detail).toHaveTextContent('规则基线 plan-2：入场 95.00–97.00 · 止损 91.00 · T1 104.00 · 建议 110 股（有效）')
    expect(within(detail).getByRole('link', { name: '第 1 版计划页' })).toHaveAttribute('href', '#plan/p1')
    expect(within(detail).getAllByRole('button', { name: '就此计划讨论' })).toHaveLength(1)
    expect(within(detail).getByRole('region', { name: '我的补充' })).toBeInTheDocument()
    expect(within(detail).getByRole('region', { name: '备注' })).toHaveTextContent('等回踩再看')
    await fireEvent.click(screen.getByRole('button', { name: '收起 MU' }))
    expect(screen.queryByTestId('row-detail')).toBeNull()
  })

  it('clicking the ticker expands too, and the layout toggle swaps the order and persists', async () => {
    mount()
    await fireEvent.click(screen.getByRole('button', { name: 'MU' }))
    const detail = await screen.findByTestId('row-detail')
    const agent = await within(detail).findByRole('region', { name: 'Agent 计划' })
    const baseline = within(detail).getByTestId('rule-baseline')
    expect(agent.compareDocumentPosition(baseline) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await fireEvent.click(within(detail).getByRole('button', { name: '规则优先（旧）' }))
    expect(baseline.compareDocumentPosition(agent) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(localStorage.getItem('workbench.today.layout')).toBe('legacy')
  })

  it('recheck calls back with the row; an exiting chain cannot be rechecked', async () => {
    const onRecheck = vi.fn()
    mount(groups({ holding: [holdRow({ chain: { ...holdRow().chain!, state: 'exiting' } })] }), { onRecheck })
    await fireEvent.click(screen.getByRole('button', { name: '展开 MU' }))
    await fireEvent.click(within(await screen.findByTestId('row-detail')).getByRole('button', { name: '重新复查' }))
    expect(onRecheck).toHaveBeenCalledWith(expect.objectContaining({ ticker: 'MU' }))
    await fireEvent.click(screen.getByRole('button', { name: '展开 AMD' }))
    const buttons = screen.getAllByRole('button', { name: '重新复查' })
    expect(buttons[1]).toBeDisabled()
    expect(buttons[1]).toHaveAttribute('title', '这条链已发出退出指令，不再复查')
  })

  it('shows the recheck text handed in by the page', async () => {
    mount(groups(), { rechecks: { 'chain:MU:2026-10-29': { busy: true, text: '复查中…' } } })
    await fireEvent.click(screen.getByRole('button', { name: '展开 MU' }))
    const detail = await screen.findByTestId('row-detail')
    expect(within(detail).getByRole('button', { name: '重新复查' })).toBeDisabled()
    expect(detail).toHaveTextContent('复查中…')
  })

  it('submits a note through onNote with a stable request id, and keeps the draft on failure', async () => {
    let n = 0
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => `req-${++n}`) })
    const onNote = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue(undefined)
    mount(groups(), { onNote })
    await fireEvent.click(screen.getByRole('button', { name: '展开 MU' }))
    const detail = await screen.findByTestId('row-detail')
    const notes = within(detail).getByRole('region', { name: '备注' })
    expect(notes).toHaveTextContent('备注只给你自己看；要让 Agent 参考，请用『我的补充』')
    await fireEvent.input(within(notes).getByLabelText('备注正文'), { target: { value: '写给自己' } })
    await fireEvent.click(within(notes).getByRole('button', { name: '保存备注' }))
    await waitFor(() => expect(onNote).toHaveBeenCalledTimes(1))
    expect(onNote).toHaveBeenLastCalledWith(expect.objectContaining({ ticker: 'MU' }), '写给自己', expect.stringMatching(/^req-/))
    expect(await within(notes).findByRole('alert')).toBeInTheDocument()
    expect((within(notes).getByLabelText('备注正文') as HTMLTextAreaElement).value).toBe('写给自己')
    await fireEvent.click(within(notes).getByRole('button', { name: '保存备注' }))
    await waitFor(() => expect(onNote).toHaveBeenCalledTimes(2))
    expect(onNote.mock.calls[1][2]).toBe(onNote.mock.calls[0][2])      // 同一内容重试沿用同一个 request id
    await waitFor(() => expect((within(notes).getByLabelText('备注正文') as HTMLTextAreaElement).value).toBe(''))
  })

  it('blocks a note longer than 1000 characters', async () => {
    const onNote = vi.fn()
    mount(groups(), { onNote })
    await fireEvent.click(screen.getByRole('button', { name: '展开 MU' }))
    const notes = within(await screen.findByTestId('row-detail')).getByRole('region', { name: '备注' })
    await fireEvent.input(within(notes).getByLabelText('备注正文'), { target: { value: '字'.repeat(1001) } })
    expect(within(notes).getByRole('button', { name: '保存备注' })).toBeDisabled()
    expect(notes).toHaveTextContent('备注最多 1000 字（现在 1001 字）')
  })

  it('shows the chain load failure inside the row only', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      String(url).startsWith('/api/workbench/chains/') ? json({ error: '迁移 026 未执行' }, 503) : json({ inputs: [] })))
    mount()
    await fireEvent.click(screen.getByRole('button', { name: '展开 MU' }))
    expect(await screen.findByText(/Agent 计划加载失败/)).toBeInTheDocument()
    expect(screen.getByRole('table', { name: '入场期计划' })).toBeInTheDocument()
  })
})

describe('PlanTable · review fixes', () => {
  const chainWith = (retriggers: any[], version_no = 3) => ({ ...row().chain!, version_no, retriggers })

  it('writes the version of a retrigger only when it is known (M3)', () => {
    mount(groups({ entry: [row({ chain: chainWith([
      { unit_signal_date: '2026-10-30', rule_ids: ['trend_reclaim'], version_no: 2 },
      { unit_signal_date: '2026-11-02', rule_ids: ['trend_reclaim'] }]) })] }))
    const table = screen.getByRole('table', { name: '入场期计划' })
    expect(table).toHaveTextContent('10-30 再次触发 → 第 2 版')
    expect(table).toHaveTextContent('11-02 再次触发')
    expect(table).not.toHaveTextContent('11-02 再次触发 → 第 3 版')
  })

  it('a chain retriggered once still says which version it became (M3)', () => {
    mount(groups({ entry: [row({ chain: chainWith([{ unit_signal_date: '2026-10-30', rule_ids: [] }], 1) })] }))
    expect(screen.getByText('10-30 再次触发 → 第 1 版')).toBeInTheDocument()
  })

  it('the 入场类型 header carries no concept term (M4)', () => {
    mount()
    const head = screen.getByRole('table', { name: '入场期计划' }).querySelectorAll('th')[4]               // [0] is the expand column
    expect(head.textContent).toBe('入场类型与区间')
    expect(head.querySelector('button')).toBeNull()
  })

  it('prints 已有活跃链 on a baseline-only row and on the expanded baseline (M7)', async () => {
    const baselineOnly = row({ row_id: 'plan:X', ticker: 'MU', chain: null,
      baseline: { ...row().baseline!, active_chain: { ticker: 'MU', signal_date: '2026-10-29' } } })
    mount(groups({ entry: [baselineOnly] }))
    expect(screen.getAllByText('已有活跃链，见 MU·10-29').length).toBe(1)
    await fireEvent.click(screen.getByRole('button', { name: '展开 MU' }))
    await within(await screen.findByTestId('row-detail')).findByTestId('rule-baseline')
    expect(screen.getAllByText('已有活跃链，见 MU·10-29').length).toBe(2)
  })

  it('a chain row with a merged baseline says where it went in the detail (M7)', async () => {
    mount()
    await fireEvent.click(screen.getByRole('button', { name: '展开 MU' }))
    expect(await screen.findByText('已有活跃链，见 MU·10-29')).toBeInTheDocument()
  })

  it('toggles are wired with aria-expanded and aria-controls (M12)', async () => {
    mount()
    const ticker = screen.getByRole('button', { name: 'MU' })
    expect(ticker).toHaveAttribute('aria-expanded', 'false')
    await fireEvent.click(ticker)
    expect(ticker).toHaveAttribute('aria-expanded', 'true')
    const id = ticker.getAttribute('aria-controls')!
    expect(document.getElementById(id)).not.toBeNull()
    const ended = screen.getByRole('button', { name: '已结束 1' })
    expect(ended).toHaveAttribute('aria-controls', 'plan-table-ended')
    await fireEvent.click(ended)
    expect(document.getElementById('plan-table-ended')).not.toBeNull()
  })

  it('shows chain-level 已执行 with what it followed (M13)', () => {
    mount(groups({ holding: [holdRow({ status: { label: '持仓期', execution: 'executed', execution_basis: '照规则基线' } })] }))
    expect(screen.getByRole('table', { name: '持仓计划' })).toHaveTextContent('已执行（照规则基线）')
  })

  it('shows a recheck conclusion that came after the holding status row (M14)', () => {
    const status = (over: Record<string, unknown>) => ({ label: '持仓期', execution: 'adopted' as const, latest_review: {
      outcome: 'invalidate', decided_by: 'agent', reason: '财报提前', session: '2026-10-30', trigger: 'recheck', ...over } })
    mount(groups({ holding: [holdRow({ status: status({}) })] }))
    expect(screen.getByTestId('later-review')).toHaveTextContent('之后的复查（2026-10-30）：作废 · Agent：财报提前')
  })

  it('does not repeat the batch review as a later one (M14)', () => {
    mount(groups({ holding: [holdRow({ status: { label: '持仓期', execution: 'adopted', latest_review: {
      outcome: 'maintain', decided_by: 'host', reason: '无新信号', session: '2026-10-30', trigger: 'batch' } } })] }))
    expect(screen.queryByTestId('later-review')).toBeNull()
  })

  it('a note body edited after a failure gets a new request id (M6)', async () => {
    let n = 0
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => `req-${++n}`) })
    const onNote = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue(undefined)
    mount(groups(), { onNote })
    await fireEvent.click(screen.getByRole('button', { name: '展开 MU' }))
    const notes = within(await screen.findByTestId('row-detail')).getByRole('region', { name: '备注' })
    const box = within(notes).getByLabelText('备注正文')
    await fireEvent.input(box, { target: { value: '第一版' } })
    await fireEvent.click(within(notes).getByRole('button', { name: '保存备注' }))
    await waitFor(() => expect(onNote).toHaveBeenCalledTimes(1))
    await within(notes).findByRole('alert')
    await fireEvent.input(box, { target: { value: '第一版，改过' } })
    await fireEvent.click(within(notes).getByRole('button', { name: '保存备注' }))
    await waitFor(() => expect(onNote).toHaveBeenCalledTimes(2))
    expect(onNote.mock.calls[1][2]).not.toBe(onNote.mock.calls[0][2])
  })
})

