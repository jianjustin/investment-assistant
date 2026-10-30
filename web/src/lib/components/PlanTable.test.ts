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
    const exit = table.querySelector('[data-instruction="exit"]')!
    expect(exit).toHaveTextContent('次一交易日开盘卖出')
    expect(exit.className).toContain('text-red-600')
    const half = table.querySelector('[data-instruction="sell_half"]')!
    expect(half).toHaveTextContent('到 T1：卖出一半，余下按移动止损')
    expect(half.className).toContain('text-orange-600')
    expect(table.querySelector('[data-instruction="hold"]')!.className).not.toContain('text-red-600')
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

describe('ended group', () => {
  it('is collapsed and greyed by default; the toggle persists', async () => {
    mount()
    expect(screen.queryByTestId('ended-group')).toBeNull()
    expect(screen.queryByText('已过期（未执行）')).toBeNull()
    const toggle = screen.getByRole('button', { name: '已结束 1' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await fireEvent.click(toggle)
    expect(localStorage.getItem('workbench.today.ended_open')).toBe('1')
    const group = screen.getByTestId('ended-group')
    expect(group.className).toContain('text-muted')
    const table = within(group).getByRole('table', { name: '已结束计划' })
    expect(table.querySelector('td.opacity-60')).not.toBeNull()
    // the status cell keeps its colour: it is not dimmed and carries its own colour class
    const status = within(table).getByText('已过期（未执行）')
    expect(status.className).toContain('text-amber-600')
    expect(status.closest('td')!.className).not.toContain('opacity-60')
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
  it('folds each row into a card with the three opening cases stacked', () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('max-width: 899px'), media: q,
      addEventListener: () => {}, removeEventListener: () => {} }))
    mount()
    expect(screen.queryByRole('table', { name: '入场期计划' })).toBeNull()
    const cards = screen.getAllByTestId('plan-card')
    expect(cards).toHaveLength(2)                                      // entry + holding; ended is collapsed
    const entry = cards[0]
    const lines = within(entry).getAllByRole('listitem').map(li => li.textContent)
    expect(lines).toContain('开盘·区间内：开在 95.10–97.30：开盘买入 120 股')
    expect(lines).toContain('开盘·高开：高开过 97.30：不追，挂 97.30 限价等回落')
    expect(lines).toContain('开盘·低开：低开：≤ 91.40 作废；否则回升到 95.10 时买入')
    expect(entry).toHaveTextContent('区间限价 95.10–97.30 · 止损 91.40 · T1 104.70 · 120 股')
    expect(cards[1]).toHaveTextContent('继续持有')
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
