import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import PlanTimeline from './PlanTimeline.svelte'
import * as api from '../api'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const planRow = (id: string, over: Record<string, unknown> = {}) => ({
  id, ticker: 'NVDA', signal_date: '2026-10-22', kind: 'agent', plan_version: 'agent-2', status: 'ok',
  entry_low: '98.50', entry_high: '101.50', stop: '95.00', target1: '108.00', ref_price: '100.00', atr: '2.00',
  valid_from: '2026-10-23', valid_until: '2026-10-27',
  sizing: { status: 'sized', shares: 120, risk_amount: '1000.00', snapshot_as_of: '2026-10-20' },
  invalid_reasons: [], warnings: [], ...over,
})
const runRow = (id: string, over: Record<string, unknown> = {}) => ({
  id, mode: 'propose', agent_version: 'agent-2', model: 'glm-5.3', status: 'ok', reason: null,
  cutoff_at: '2026-10-22T22:30:00Z', input_tokens: 10, output_tokens: 5, created_at: '2026-10-22T22:31:00Z',
  output: { action: 'buy', summary: '回踩修复放量',
            levels: { entry_low: { value: '98.50', refs: ['call:1'] }, entry_high: { value: '101.50', refs: ['call:1'] },
                      stop: { value: '95.00', refs: ['call:1'] }, target1: { value: '108.00', refs: ['call:1'] } },
            thesis: [{ id: 'T1', text: '放量突破 20 日线', refs: ['call:1'] }],
            invalidation: [{ kind: 'close_below', params: { price: '94.00' }, text: '收盘跌破 94.00', refs: ['call:1'] }],
            review_when: [], changes: [] },
  counter: { status: 'ok', counter: [], risks: [], dropped: 0, uncountered: [1] }, ...over,
})
const review = (over: Record<string, unknown> = {}) => ({
  id: 11, ticker: 'NVDA', signal_date: '2026-10-22', head_plan_id: 'p0', session: '2026-10-23', trigger: 'batch',
  run_id: 'run-1', mode: 'entry', timeline_version: 'timeline-1',
  signals: [{ kind: 't1_touched', fired: true, detail: '最高价触及 T1 108.00', evidence: [] },
            { kind: 'new_8k', fired: false, detail: '没有新的 8-K', evidence: [] },
            { kind: 'user_input', fired: true, detail: '1 条', evidence: [] }],
  conditions: [{ list: 'invalidation', index: 0, kind: 'close_below', params: { price: '94.00' }, result: 'not_met', detail: '' }],
  user_input_ids: [7], outcome: 'revise', decided_by: 'agent', reason: 'T1 已触及，上移止损', refs: ['call:3', 'user:7'],
  review_agent_run_id: 'rr-1', revision_agent_run_id: 'rv-1', new_plan_id: 'p1', detail: {}, attempt: 1,
  cutoff_at: '2026-10-23T22:30:00Z', input_tokens: 1, output_tokens: 1, created_at: '2026-10-23T22:35:00Z',
  head_version_no: 0, new_version_no: 1, ...over,
})
const chain = (over: Record<string, unknown> = {}) => ({
  ticker: 'NVDA', signal_date: '2026-10-22', session: '2026-10-24',
  state: { state: 'entry', mode: 'entry', basis: '已决定买入，尚未成交' },
  head_plan_id: 'p1', version_no: 1, latest_review: null, shadow_version: 'plan-shadow-1',
  versions: [
    { version_no: 0, plan_id: 'p0', origin: 'signal', supersedes_plan_id: null, agent_run_id: 'run-0',
      cutoff_at: '2026-10-22T22:30:00Z', as_of_session: '2026-10-22', created_at: '2026-10-22T22:31:00Z',
      is_head: false, diff: null, changes: [], plan: planRow('p0'), run: runRow('run-0'),
      shadow: { status: 'expired', fill_date: null, fill_price: null, legs: [], r: null, return: null, spy_return: null } },
    { version_no: 1, plan_id: 'p1', origin: 'review', supersedes_plan_id: 'p0', agent_run_id: 'rv-1',
      cutoff_at: '2026-10-23T22:30:00Z', as_of_session: '2026-10-23', created_at: '2026-10-23T22:36:00Z',
      is_head: true, diff: [{ field: 'stop', before: '95.00', after: '96.00' }],
      changes: [{ field: 'stop', text: '止损上移', refs: ['call:3'] }],
      plan: planRow('p1', { stop: '96.00', valid_from: '2026-10-24', valid_until: '2026-10-26' }),
      run: runRow('rv-1', { mode: 'revise' }),
      shadow: { status: 'pending', fill_date: null, fill_price: null, legs: [], r: null, return: null, spy_return: null } },
  ],
  reviews: [
    review(),
    review({ id: 12, head_plan_id: 'p1', session: '2026-10-24', trigger: 'recheck', outcome: 'revise',
             decided_by: 'agent', reason: '财报提前', new_plan_id: null, new_version_no: null, head_version_no: 1,
             user_input_ids: [], detail: { revision_status: 'rejected: changes_mismatch' },
             created_at: '2026-10-24T15:00:00Z' }),
    review({ id: 13, head_plan_id: 'p1', session: '2026-10-24', trigger: 'batch', outcome: 'skipped',
             decided_by: null, reason: 'token_budget', new_plan_id: null, new_version_no: null, head_version_no: 1,
             signals: [], conditions: [], user_input_ids: [], created_at: '2026-10-24T22:40:00Z' }),
  ],
  inputs: [], ...over,
})

let calls: { url: string; init?: RequestInit }[]
let respond: (url: string, init?: RequestInit) => Promise<Response>
beforeEach(() => {
  calls = []
  respond = async () => json(chain())
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init }); return respond(String(url), init)
  }))
})
afterEach(() => vi.unstubAllGlobals())

describe('PlanTimeline', () => {
  it('lists versions with origin, cutoff and diff', async () => {
    render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
    const list = await screen.findByRole('list', { name: '版本' })
    expect(calls[0].url).toBe('/api/workbench/chains/NVDA/2026-10-22')
    const rows = list.querySelectorAll(':scope > li')
    expect(rows[0]).toHaveTextContent('第 0 版 · 信号日 · 生成 2026-10-23 06:31:00 北京 · 截止 2026-10-23 06:30:00 北京')
    expect(rows[0]).toHaveTextContent('入场 98.50–101.50 · 止损 95.00 · T1 108.00 · 有效期至 2026-10-27 · 影子 到期未成交')
    expect(rows[1]).toHaveTextContent('第 1 版 · 每日复查')
    expect(rows[1]).toHaveTextContent('最新')
    expect(rows[1]).toHaveTextContent('差异：止损 95.00 → 96.00')
    // 点开即该版的 Agent 计划卡
    await fireEvent.click(screen.getByRole('button', { name: '第 0 版' }))
    expect(await screen.findByText(/^Agent 计划 · 第 0 版/)).toBeInTheDocument()
  })

  it('lists reviews with signals, conditions and cited inputs', async () => {
    render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
    const list = await screen.findByRole('list', { name: '复查记录' })
    const rows = list.querySelectorAll(':scope > li')
    expect(rows[0]).toHaveTextContent('2026-10-23 · 批处理 · 修订 · Agent · 第 0 版 → 第 1 版')
    expect(rows[0]).toHaveTextContent('T1 已触及，上移止损')
    expect(rows[0]).toHaveTextContent('信号：触及 T1、新的用户输入')
    expect(rows[0]).toHaveTextContent('失效 收盘跌破 94.00：未成立')
    expect(rows[0]).toHaveTextContent('给模型的新输入：user:7')
    expect(rows[0]).toHaveTextContent('引用：user:7')
    expect(rows[1]).not.toHaveTextContent('给模型的新输入')
    expect(rows[1]).toHaveTextContent('重新复查 · 修订 · Agent · 第 1 版')
    expect(rows[1]).toHaveTextContent('修订未通过：变化说明与实际差异不符')
    expect(rows[2]).toHaveTextContent('跳过')
    expect(rows[2]).toHaveTextContent('超出 token 上限')
  })

  it('old version banner links to head', async () => {
    render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p0' })
    const banner = await screen.findByText('这是第 0 版，最新为第 1 版')
    expect(banner).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看最新版' }).getAttribute('href')).toBe('#plan/p1')
  })

  it('no banner on the head version', async () => {
    render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
    await screen.findByRole('list', { name: '版本' })
    expect(screen.queryByText(/最新为第/)).toBeNull()
  })

  it('recheck enabled only for entry/holding and polls the run', async () => {
    respond = async (url, init) => {
      if (url.endsWith('/recheck') && init?.method === 'POST') return json({ run_id: 'plan_recheck-1', status: 'pending' })
      if (url.startsWith('/api/runs/')) return json({ run_id: 'plan_recheck-1', status: 'done', result: { outcome: 'maintain' } })
      return json(chain())
    }
    const { unmount } = render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
    const button = await screen.findByRole('button', { name: '重新复查' })
    expect(button).not.toBeDisabled()
    await fireEvent.click(button)
    expect(await screen.findByText('复查完成：维持')).toBeInTheDocument()
    expect(calls.some(c => c.url === '/api/workbench/chains/NVDA/2026-10-22/recheck' && c.init?.method === 'POST')).toBe(true)
    expect(calls.some(c => c.url === '/api/runs/plan_recheck-1')).toBe(true)
    await waitFor(() => expect(calls.filter(c => c.url === '/api/workbench/chains/NVDA/2026-10-22').length).toBe(2))
    unmount()

    for (const state of ['expired', 'invalidated', 'position_closed', 'closed_by_decision']) {
      respond = async () => json(chain({ state: { state, mode: null, basis: '已结束' } }))
      const r = render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
      expect(await screen.findByRole('button', { name: '重新复查' })).toBeDisabled()
      r.unmount()
    }
    respond = async () => json(chain({ state: { state: 'holding', mode: 'holding', basis: '持仓中' } }))
    render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
    expect(await screen.findByRole('button', { name: '重新复查' })).not.toBeDisabled()
  })

  it('recheck polls up to 15 minutes, a poll timeout is not a failure, and skipped/error carry the reason', async () => {
    respond = async (url, init) => url.endsWith('/recheck') && init?.method === 'POST'
      ? json({ run_id: 'plan_recheck-1', status: 'pending' }) : json(chain())
    const poll = vi.spyOn(api, 'pollRun').mockRejectedValueOnce(new Error('run timeout'))
    const first = render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
    await fireEvent.click(await screen.findByRole('button', { name: '重新复查' }))
    expect(await screen.findByText('复查仍在后台进行，稍后刷新查看')).toBeInTheDocument()
    expect(poll).toHaveBeenCalledWith('plan_recheck-1', { timeoutMs: 900_000 })
    expect(screen.getByRole('button', { name: '重新复查' })).toBeDisabled()
    first.unmount()

    poll.mockResolvedValueOnce({ run_id: 'plan_recheck-1', status: 'done', result: { outcome: 'error', reason: 'review_malformed' } })
    render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
    await fireEvent.click(await screen.findByRole('button', { name: '重新复查' }))
    expect(await screen.findByText('复查完成：出错（复查输出格式无效）')).toBeInTheDocument()
    poll.mockRestore()
  })

  it('409 review_in_progress shows reason', async () => {
    respond = async (url, init) => url.endsWith('/recheck') && init?.method === 'POST'
      ? json({ error: 'review_in_progress' }, 409) : json(chain())
    render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
    await fireEvent.click(await screen.findByRole('button', { name: '重新复查' }))
    expect(await screen.findByText('不能重新复查：正在复查')).toBeInTheDocument()
  })

  it('shows the backend reason when the chain view is unavailable', async () => {
    respond = async () => json({ error: '迁移 026 未执行' }, 503)
    render(PlanTimeline, { ticker: 'NVDA', signalDate: '2026-10-22', currentPlanId: 'p1' })
    expect(await screen.findByText(/迁移 026 未执行/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新复查' })).toBeNull()
  })
})
