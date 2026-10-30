import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import PlanRowDetail from './PlanRowDetail.svelte'
import { holdRow, row } from '../plan-table-fixtures'
import type { PlanTableRow } from '../workbench'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const levels = {
  entry_low: { value: '95.10', refs: ['call:1'] }, entry_high: { value: '97.30', refs: ['call:1'] },
  stop: { value: '91.40', refs: ['call:1'] }, target1: { value: '104.70', refs: ['call:1'] },
}
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
           output: { action: 'buy', summary: '回踩修复放量', levels, thesis: [], invalidation: [], review_when: [], changes: [] },
           counter: null } }],
})
const toolCall = { seq: 1, phase: 'propose', tool: 'get_price_bars', args: { ticker: 'MU' }, result: { last_close: '96.00' },
                   result_sha256: 'abcdef0123456789', called_at: '2026-10-29T22:30:00Z' }

beforeEach(() => {
  try { localStorage.removeItem('workbench.today.layout') } catch { /* */ }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const u = String(url)
    if (u.startsWith('/api/workbench/chains/')) return json(chainView())
    if (u.startsWith('/api/workbench/agent-runs/')) return json({ ...chainView().versions[0].run, tool_calls: [toolCall] })
    if (u.startsWith('/api/workbench/user-inputs')) return json({ inputs: [] })
    return json({})
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

const mount = (r: PlanTableRow = row(), over: Record<string, unknown> = {}) =>
  render(PlanRowDetail, { row: r, onRecheck: vi.fn(), onNote: vi.fn(async () => {}), ...over })

describe('PlanRowDetail', () => {
  it('sheet closes on Esc: a tool call opens in a side sheet and Escape dismisses it', async () => {
    mount()
    const card = await screen.findByRole('region', { name: 'Agent 计划' })
    const opener = within(card).getAllByRole('button', { name: 'call:1' })[0]
    opener.focus()
    await fireEvent.click(opener)
    const sheet = await screen.findByRole('dialog')
    expect(sheet).toHaveAccessibleName('工具调用 call:1')
    expect(sheet).toHaveTextContent('get_price_bars')
    expect(sheet).toHaveTextContent('abcdef01')
    expect(sheet).toHaveTextContent('96.00')
    await waitFor(() => expect(sheet.contains(document.activeElement)).toBe(true))
    await fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await waitFor(() => expect(document.activeElement).toBe(opener))     // focus goes back to the call button
  })

  it('a call that is not in the run says so inside the sheet', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/workbench/chains/')) return json(chainView())
      if (u.startsWith('/api/workbench/agent-runs/')) return json({ ...chainView().versions[0].run, tool_calls: [] })
      return json({ inputs: [] })
    }))
    mount()
    const card = await screen.findByRole('region', { name: 'Agent 计划' })
    await fireEvent.click(within(card).getAllByRole('button', { name: 'call:1' })[0])
    expect(await within(await screen.findByRole('dialog')).findByText('未找到该编号的工具调用')).toBeInTheDocument()
  })

  it('a recheck in flight shows the running pill with the time waited; the button is busy', async () => {
    mount(holdRow(), { recheck: { busy: true, text: '复查中…', since: Date.now() - 5000 } })
    const detail = await screen.findByTestId('row-detail')
    const pill = within(detail).getByText('复查中…').closest('[data-slot="badge"]')!
    expect(pill).toHaveAttribute('data-domain', 'run')
    expect(pill).toHaveAttribute('data-status', 'running')
    expect(detail).toHaveTextContent(/已等待 [5-9] 秒/)
    const button = within(detail).getByRole('button', { name: '重新复查' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
  })

  it('a finished recheck keeps its plain text and re-enables the button', async () => {
    mount(holdRow(), { recheck: { busy: false, text: '复查完成：维持' } })
    const detail = await screen.findByTestId('row-detail')
    expect(within(detail).getByText('复查完成：维持')).toBeInTheDocument()
    expect(within(detail).queryByText(/已等待/)).toBeNull()
    expect(within(detail).getByRole('button', { name: '重新复查' })).toBeEnabled()
  })

  it('the rule baseline is one standard line, its derivation opens on demand, and the layout buttons are Buttons', async () => {
    mount()
    const baseline = await screen.findByTestId('rule-baseline')
    expect(baseline).toHaveTextContent('规则基线 plan-2：入场 95.00–97.00 · 止损 91.00 · T1 104.00 · 建议 110 股（有效）')
    expect(within(baseline).getByRole('link', { name: '查看' })).toHaveAttribute('href', '#plan/b1')
    expect(within(baseline).getByRole('button', { name: '展开推导' })).toHaveAttribute('aria-expanded', 'false')
    const layout = screen.getByRole('group', { name: '布局' })
    expect(within(layout).getByRole('button', { name: 'Agent 优先' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(layout).getByRole('button', { name: '规则优先（旧）' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('a row without a chain says so and offers the discussion button for the baseline', async () => {
    mount(row({ chain: null }))
    expect(await screen.findByText('这一行没有 Agent 计划链。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '就此计划讨论' })).toBeInTheDocument()
  })

  it('a failed chain load is an alert inside the row only', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      String(url).startsWith('/api/workbench/chains/') ? json({ error: '迁移 026 未执行' }, 503) : json({ inputs: [] })))
    mount()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/Agent 计划加载失败/)
    expect(screen.getByTestId('row-detail')).toContainElement(alert)
  })
})
