import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import AgentPlanCard from './AgentPlanCard.svelte'
import * as api from '../api'
import { ATTACH, resetConceptIndex } from '../knowledge'

const conceptIndexOf = (ids: string[]) => ({
  knowledge_version: 'knowledge-1', groups: [],
  concepts: ids.map(id => ({ id, ref: `concept:${id}@1`, title: `T:${id}`, group: id.split('.')[0], version: 1,
                             applies_to: [], summary: `S:${id}`, related: [] })),
})
const termIds = async () => new Set((await screen.findAllByRole('button', { name: /^概念：/, hidden: true }))
  .map(b => b.getAttribute('aria-label')!.replace(/^概念：T:/, '')))

const agentPlan = (overrides: Record<string, unknown> = {}) => ({
  id: 'ap2', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'agent', plan_version: 'agent-2', status: 'ok',
  entry_low: '98.50', entry_high: '101.50', stop: '96.00', target1: '108.00', ref_price: '100.00', atr: '2.00',
  valid_from: '2026-10-26', valid_until: '2026-10-28',
  sizing: { status: 'sized', shares: 166, risk_amount: '1000.00', snapshot_as_of: '2026-10-20' },
  invalid_reasons: [], warnings: [], ...overrides,
})

const agent2 = (overrides: Record<string, any> = {}) => ({
  id: 'r2', status: 'ok', model: 'gpt-test', agent_version: 'agent-2',
  output: {
    action: 'buy', summary: '回踩修复放量',
    levels: { entry_low: { value: '98.50', refs: ['call:1'] }, entry_high: { value: '101.50', refs: ['call:1'] },
              stop: { value: '96.00', refs: ['call:2'] }, target1: { value: '108.00', refs: ['call:2'] } },
    thesis: [{ id: 'T1', text: '放量突破 20 日线', refs: ['call:1'] },
             { id: 'T2', text: '行业转强', refs: ['call:3', 'user:7'] }],
    invalidation: [{ kind: 'close_below', params: { price: '95.00' }, text: '收盘跌破 95.00', refs: ['call:2'] },
                   { kind: 'regime_is', params: { label: 'risk_off' }, text: '区制变为 risk_off', refs: ['call:4'] }],
    review_when: [{ kind: 'earnings_within', params: { sessions: 3 }, text: '距财报不足 3 个交易日' }],
    changes: [{ field: 'stop', text: '止损上移到前低', refs: ['call:2'] }],
  },
  counter: { status: 'ok', counter: [{ thesis: 1, text: '量能来自指数调仓', refs: ['call:5'] }],
             risks: [{ text: '财报临近', refs: ['call:6'] }], dropped: 0, uncountered: [2] },
  plan: agentPlan(), input_tokens: 40, output_tokens: 20, created_at: '2026-10-27T13:00:00Z',
  chain: {
    version_no: 1, head_plan_id: 'ap2', state: 'entry', mode: 'entry', basis: '已决定买入，尚未成交',
    cutoff_at: '2026-10-27T12:59:00Z',
    diff: [{ field: 'stop', before: '95.00', after: '96.00' }],
    latest_review: {
      id: 9, session: '2026-10-27', trigger: 'batch', outcome: 'maintain', decided_by: 'host',
      reason: '无新信号，复查条件未满足（距财报不足 3 个交易日）', new_plan_id: null, revision_status: null,
      created_at: '2026-10-27T22:40:00Z',
      conditions: [
        { list: 'invalidation', index: 0, kind: 'close_below', params: { price: '95.00' }, result: 'not_met', detail: '' },
        { list: 'invalidation', index: 1, kind: 'regime_is', params: { label: 'risk_off' }, result: 'unknown', detail: '' },
        { list: 'review_when', index: 0, kind: 'earnings_within', params: { sessions: 3 }, result: 'not_met', detail: '' },
      ],
    },
  },
  ...overrides,
})

const withReview = (review: Record<string, unknown>) => {
  const a = agent2()
  return agent2({ chain: { ...a.chain, latest_review: { ...a.chain.latest_review, ...review } } })
}

describe('AgentPlanCard', () => {
  it('renders thesis, counter per thesis, invalidation with results, review_when, changes', async () => {
    const onCall = vi.fn()
    render(AgentPlanCard, { agent: agent2() as any, onCall })
    expect(screen.getByText(/^Agent 计划 · 第 1 版 · 生成于 2026-10-27 21:00:00 北京 · 截止 2026-10-27 20:59:00 北京$/))
      .toBeInTheDocument()
    expect(screen.getByText('买入 · 入场区间 98.50–101.50 · 止损 96.00 · T1 108.00')).toBeInTheDocument()
    expect(screen.getByText('建议 166 股')).toBeInTheDocument()
    const thesis = screen.getByRole('list', { name: '论点' })
    expect(thesis).toHaveTextContent('T1')
    expect(thesis).toHaveTextContent('放量突破 20 日线')
    expect(thesis).toHaveTextContent('反证：量能来自指数调仓')
    expect(thesis).toHaveTextContent('user:7')
    const invalidation = screen.getByRole('list', { name: '失效条件' })
    expect(invalidation).toHaveTextContent('收盘跌破 95.00 · 最近判定：未成立')
    expect(invalidation).toHaveTextContent('区制变为 risk_off · 最近判定：无法判定')
    expect(screen.getByRole('list', { name: '下次复查条件' })).toHaveTextContent('距财报不足 3 个交易日')
    const changes = screen.getByRole('region', { name: '相对第 0 版' })
    expect(changes).toHaveTextContent('止损 95.00 → 96.00')
    expect(changes).toHaveTextContent('止损上移到前低')
    expect(screen.getByText(/其他风险/)).toHaveTextContent('财报临近')
    // call refs open tool calls; user refs are plain text
    expect(screen.queryByRole('button', { name: 'user:7' })).toBeNull()
    await fireEvent.click(screen.getAllByRole('button', { name: 'call:5' })[0])
    expect(onCall).toHaveBeenCalledWith('call:5')
  })

  it('shows 反方未对此论点给出反证 for uncountered', () => {
    render(AgentPlanCard, { agent: agent2() as any, onCall: () => {} })
    const items = screen.getByRole('list', { name: '论点' }).querySelectorAll(':scope > li')
    expect(items[0]).not.toHaveTextContent('反方未对此论点给出反证')
    expect(items[1]).toHaveTextContent('反方未对此论点给出反证')
  })

  it('evidence text 证据：未验证 always present', () => {
    for (const agent of [
      agent2(),
      { id: 'r3', status: 'rejected', reason: 'thesis_count', created_at: '2026-10-22T23:00:00Z' },
      agent2({ status: 'pass', plan: null, output: { action: 'pass', summary: '趋势不明', levels: null, thesis: [] } }),
      withReview({ outcome: 'invalidate' }),
    ]) {
      const { unmount } = render(AgentPlanCard, { agent: agent as any, onCall: () => {} })
      expect(screen.getByText('证据：未验证')).toBeInTheDocument()
      unmount()
    }
  })

  it('shows latest review with decided_by text', () => {
    render(AgentPlanCard, { agent: agent2() as any, onCall: () => {} })
    const line = screen.getByText(/^最近复查/)
    expect(line).toHaveTextContent('维持 · 系统规则')
    expect(line).toHaveTextContent('无新信号，复查条件未满足（距财报不足 3 个交易日）')
    expect(line).toHaveTextContent('2026-10-28 06:40:00 北京')
  })

  it('legacy agent-1 shows the legacy label', () => {
    render(AgentPlanCard, { agent: {
      id: 'r1', status: 'ok', model: 'gpt-test', agent_version: 'agent-1', legacy: true,
      output: { action: 'buy', summary: '回踩', levels: agent2().output.levels, thesis: [{ text: '放量', refs: ['call:1'] }] },
      counter: { status: 'ok', risks: [{ text: '财报临近', refs: ['call:1'] }], dropped: 0 },
      plan: agentPlan({ plan_version: 'agent-1' }), input_tokens: 1, output_tokens: 1,
      created_at: '2026-10-22T23:00:00Z', chain: null } as any, onCall: () => {} })
    expect(screen.getByText('agent-1（旧版，不参与复查）')).toBeInTheDocument()
    expect(screen.getByText('Agent 建议（gpt-test · agent-1）买入')).toBeInTheDocument()
    expect(screen.getByText(/反方：/)).toHaveTextContent('财报临近')
    expect(screen.queryByText(/^Agent 计划 · 第/)).toBeNull()
    expect(screen.getByText('证据：未验证')).toBeInTheDocument()
  })

  it('revision failure note', () => {
    render(AgentPlanCard, { agent: withReview({ outcome: 'revise', decided_by: 'agent', reason: '财报提前',
                                                revision_status: 'rejected: no_change' }) as any,
                            onCall: () => {} })
    expect(screen.getByText('Agent 建议修订，但修订未通过校验（修订与上版没有差异），当前仍为第 1 版')).toBeInTheDocument()
  })

  it('states why there is no plan: failed, pass and invalidated', async () => {
    const onRerun = vi.fn()
    const { unmount } = render(AgentPlanCard, { agent: { id: 'r3', status: 'rejected', reason: 'invalid_condition',
                                                         created_at: 'c' } as any, onCall: () => {}, onRerun })
    expect(screen.getByText('Agent 未给出计划：失效或复查条件无效')).toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: '重新运行 Agent' }))
    expect(onRerun).toHaveBeenCalled()
    unmount()

    const passed = render(AgentPlanCard, { agent: agent2({ status: 'pass', plan: null,
      output: { action: 'pass', summary: '趋势不明', levels: null, thesis: [] } }) as any, onCall: () => {} })
    expect(screen.getByText('Agent 不建议买入：趋势不明')).toBeInTheDocument()
    passed.unmount()

    const a = agent2()
    render(AgentPlanCard, { agent: agent2({ chain: { ...a.chain, state: 'invalidated',
      latest_review: { ...a.chain.latest_review, outcome: 'invalidate', reason: '失效条件成立：收盘跌破 95.00' } } }) as any,
      onCall: () => {} })
    expect(screen.getByText('Agent 已作废此计划（第 1 版）：失效条件成立：收盘跌破 95.00')).toBeInTheDocument()
    expect(screen.queryByText(/入场区间/)).toBeNull()
  })

  it('labels condition results only when the review carries them', () => {
    const a = agent2()
    const { unmount } = render(AgentPlanCard, { agent: agent2({ chain: { ...a.chain,
      latest_review: { ...a.chain.latest_review, conditions: undefined } } }) as any, onCall: () => {} })
    const list = screen.getByRole('list', { name: '失效条件' })
    expect(list).not.toHaveTextContent('最近判定')
    expect(list).not.toHaveTextContent('尚未复查')
    unmount()

    const second = render(AgentPlanCard, { agent: agent2({ chain: { ...a.chain, latest_review: null } }) as any,
                                           onCall: () => {} })
    expect(screen.getByRole('list', { name: '失效条件' })).toHaveTextContent('收盘跌破 95.00 · 最近判定：尚未复查')
    second.unmount()

    // 产生本版的那条复查判定的是上一版：本版仍是「尚未复查」
    render(AgentPlanCard, { agent: agent2({ chain: { ...a.chain, latest_review: { ...a.chain.latest_review,
      outcome: 'revise', new_plan_id: 'ap2' } } }) as any, onCall: () => {} })
    expect(screen.getByRole('list', { name: '失效条件' })).toHaveTextContent('收盘跌破 95.00 · 最近判定：尚未复查')
  })

  it('holding version blocked by position rules is not called void', () => {
    const a = agent2()
    const blocked = agentPlan({ status: 'invalid', invalid_reasons: ['no_room'] })
    const { unmount } = render(AgentPlanCard, { agent: agent2({ plan: blocked,
      chain: { ...a.chain, state: 'holding', mode: 'holding' } }) as any, onCall: () => {} })
    expect(screen.getByText('本版按仓位规则不能加仓（no_room）')).toBeInTheDocument()
    expect(screen.queryByText(/Agent 计划已作废/)).toBeNull()
    unmount()

    render(AgentPlanCard, { agent: agent2({ plan: blocked }) as any, onCall: () => {} })
    expect(screen.getByText('Agent 计划已作废：no_room')).toBeInTheDocument()
  })

  describe('knowledge', () => {
    beforeEach(() => { resetConceptIndex() })
    afterEach(() => { cleanup(); vi.restoreAllMocks() })

    it('ConceptTerm on each field per ATTACH.agentCard', async () => {
      const wanted = new Set(Object.values(ATTACH.agentCard))
      vi.spyOn(api, 'getConcepts').mockResolvedValue(conceptIndexOf([...wanted]))
      const found = new Set<string>()
      const a = agent2()
      const blocked = agentPlan({ status: 'invalid', invalid_reasons: ['no_room'] })
      const cases = [
        agent2(),                                                                     // version, cutoff, levels, citation, thesis, counter, conditions, changes, review
        { id: 'r1', status: 'ok', model: 'gpt-test', agent_version: 'agent-1', legacy: true, output: agent2().output,
          counter: { status: 'ok', risks: [], dropped: 0 }, plan: agentPlan({ plan_version: 'agent-1' }),
          input_tokens: 1, output_tokens: 1, created_at: '2026-10-22T23:00:00Z', chain: null },   // legacy
        agent2({ chain: { ...a.chain, latest_review: { ...a.chain.latest_review, outcome: 'revise', decided_by: 'agent',
                 reason: '财报提前', revision_status: 'rejected: no_change' } } }),   // reject reasons
        agent2({ plan: blocked, chain: { ...a.chain, state: 'holding', mode: 'holding' } }),   // no add
      ]
      for (const agent of cases) {
        render(AgentPlanCard, { agent: agent as any, onCall: () => {} })
        for (const id of await termIds()) found.add(id)
        cleanup()
      }
      expect(found).toEqual(wanted)
    })

    it('chips keep the original lines intact', async () => {
      vi.spyOn(api, 'getConcepts').mockResolvedValue(conceptIndexOf(Object.values(ATTACH.agentCard)))
      render(AgentPlanCard, { agent: agent2() as any, onCall: () => {} })
      await termIds()
      expect(screen.getByText('买入 · 入场区间 98.50–101.50 · 止损 96.00 · T1 108.00')).toBeInTheDocument()
      expect(screen.getByText('证据：未验证')).toBeInTheDocument()
    })

    it('看推理过程 opens AgentReasoning with the generating run id', async () => {
      vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
      const getReasoning = vi.spyOn(api, 'getReasoning').mockResolvedValue({
        run: { id: 'r2', ticker: 'NVDA', signal_date: '2026-10-22', mode: 'propose', agent_version: 'agent-2', status: 'ok',
               reason: null, reason_text: null, model: 'gpt-test', cutoff_at: '', started_at: '', finished_at: '',
               input_tokens: 0, output_tokens: 0 },
        legacy: false, version: null, review: null, steps: [
          { kind: 'read', title: '提议者读了什么', concept: null, calls: [] }], notes: [] } as any)
      render(AgentPlanCard, { agent: agent2() as any, onCall: () => {} })
      expect(getReasoning).not.toHaveBeenCalled()                       // 展开时才请求
      const open = screen.getByRole('button', { name: '看推理过程' })
      expect(open).toHaveAttribute('aria-expanded', 'false')
      await fireEvent.click(open)
      expect(await screen.findByRole('region', { name: '提议者读了什么' })).toBeInTheDocument()
      expect(getReasoning).toHaveBeenCalledWith('r2')
      expect(open).toHaveAttribute('aria-expanded', 'true')
      await fireEvent.click(open)
      expect(screen.queryByRole('region', { name: '提议者读了什么' })).toBeNull()
    })

    it('failed runs can still be read', async () => {
      vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
      render(AgentPlanCard, { agent: { id: 'r3', status: 'rejected', reason: 'thesis_count', created_at: 'c' } as any,
                              onCall: () => {} })
      expect(screen.getByRole('button', { name: '看推理过程' })).toBeInTheDocument()
    })
  })
})

describe('AgentPlanCard · v2.7 growth loop', () => {
  beforeEach(() => { resetConceptIndex(); vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline')) })
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('renders KnowledgeRefs when present', () => {
    render(AgentPlanCard, { agent: agent2({ knowledge_refs: [
      { ref: 'know:3@1', title: '回踩别追', fields: ['thesis', 'counter'], current_version: 2 },
      { ref: 'know:4@1', title: '财报前不加仓', fields: ['risks'], current_version: 1 },
    ] }) as any, onCall: () => {} })
    const refs = screen.getByRole('region', { name: '引用的知识' })
    const first = within(refs).getByRole('link', { name: 'know:3@1' })
    expect(first).toHaveAttribute('href', '#knowledge/mine/3@1')
    const rows = within(refs).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('回踩别追')
    expect(rows[0]).toHaveTextContent('论点、反证')
    expect(rows[0]).toHaveTextContent('当前已是第 2 版')
    expect(rows[1]).toHaveTextContent('财报前不加仓')
    expect(rows[1]).not.toHaveTextContent('当前已是')          // cited version is the current one
  })

  it('shows no 引用的知识 block without knowledge refs', () => {
    render(AgentPlanCard, { agent: agent2() as any, onCall: () => {} })
    expect(screen.queryByRole('region', { name: '引用的知识' })).toBeNull()
    cleanup()
    render(AgentPlanCard, { agent: agent2({ knowledge_refs: [] }) as any, onCall: () => {} })
    expect(screen.queryByRole('region', { name: '引用的知识' })).toBeNull()
  })

  it('a know: ref inside a thesis is a link to that version, not plain text', () => {
    const a = agent2()
    render(AgentPlanCard, { agent: agent2({ output: { ...a.output, thesis: [
      { id: 'T1', text: '回踩后企稳', refs: ['call:1', 'know:3@1'] }] } }) as any, onCall: () => {} })
    const thesis = screen.getByRole('list', { name: '论点' })
    expect(within(thesis).getByRole('link', { name: 'know:3@1' })).toHaveAttribute('href', '#knowledge/mine/3@1')
  })

  it('DiscussButton with plan context', async () => {
    const post = vi.spyOn(api, 'postDiscussion').mockResolvedValue({ id: 5 } as any)
    location.hash = ''
    render(AgentPlanCard, { agent: agent2() as any, onCall: () => {} })
    await fireEvent.click(screen.getByRole('button', { name: '就此计划讨论' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0].context).toEqual({ kind: 'plan', plan_id: 'ap2' })
    await waitFor(() => expect(location.hash).toBe('#discuss/5'))
  })

  it('has no discuss button when the run produced no plan', () => {
    render(AgentPlanCard, { agent: { id: 'r3', status: 'rejected', reason: 'thesis_count', created_at: 'c' } as any, onCall: () => {} })
    expect(screen.queryByRole('button', { name: '就此计划讨论' })).toBeNull()
  })
})

describe('AgentPlanCard · executable fields (v2.9)', () => {
  const v3 = (over: Record<string, any> = {}, planOver: Record<string, unknown> = {}) => agent2({
    agent_version: 'agent-3', plan: agentPlan({ plan_version: 'agent-3', entry_type: 'breakout_stop', max_hold_sessions: 14, ...planOver }),
    ...over })

  it('shows the entry type and the max hold of an agent-3 version', async () => {
    render(AgentPlanCard, { agent: v3() as any, onCall: () => {} })
    expect(await screen.findByText('入场类型 突破买入 · 最长持有 14 个交易日')).toBeInTheDocument()
  })

  it('an agent-2 version shows the defaults and says so', async () => {
    render(AgentPlanCard, { agent: agent2() as any, onCall: () => {} })
    expect(await screen.findByText('入场类型 区间限价 · 最长持有 10 个交易日 · 旧版计划，执行字段按默认值显示')).toBeInTheDocument()
  })

  it('marks the entry fields as not applicable in the holding period', async () => {
    const base = v3()
    render(AgentPlanCard, { agent: { ...base, chain: { ...base.chain, mode: 'holding', state: 'holding' } } as any, onCall: () => {} })
    expect(await screen.findByText('入场类型 突破买入 · 最长持有 14 个交易日 · 入场类型与区间持仓期不适用')).toBeInTheDocument()
  })

  it('an exiting chain says the exit instruction is out and no more reviews follow', async () => {
    const base = v3()
    render(AgentPlanCard, { agent: { ...base, chain: { ...base.chain, mode: 'holding', state: 'exiting' } } as any, onCall: () => {} })
    expect(await screen.findByText(/退出期：已发出退出指令（次一交易日开盘卖出），不再复查/)).toBeInTheDocument()
  })

  it('a renewal diff lists the host-only fields with a mark', async () => {
    const base = v3()
    render(AgentPlanCard, { agent: { ...base, output: { ...base.output, changes: [] }, chain: { ...base.chain, diff: [
      { field: 'valid_until', before: '2026-10-28', after: '2026-11-03', host_only: true },
      { field: 'entry_cap', before: '2026-11-05', after: '2026-11-12', host_only: true }] } } as any, onCall: () => {} })
    const region = await screen.findByRole('region', { name: '相对第 0 版' })
    expect(region).toHaveTextContent('有效期至 2026-10-28 → 2026-11-03（宿主）')
    expect(region).toHaveTextContent('入场期上限 2026-11-05 → 2026-11-12（宿主）')
  })

  it('has no decision form', async () => {
    render(AgentPlanCard, { agent: v3() as any, onCall: () => {} })
    await screen.findByRole('region', { name: 'Agent 计划' })
    expect(screen.queryByRole('button', { name: '提交决定' })).toBeNull()
    expect(screen.queryByLabelText('理由')).toBeNull()
  })
})

