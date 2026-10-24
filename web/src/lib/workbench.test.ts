import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  WorkbenchError, decisionPayload, describeError, finalAction, getAccount, getDiscipline, getMonthly,
  getPlanShadow, getToday, levelsError, pct, publishedText, pushToday, ruleLabel, timeline,
} from './workbench'
import type { DisciplineTrade, Plan, PlanShadow } from './workbench'

afterEach(() => vi.unstubAllGlobals())

const unit = {
  ticker: 'NVDA', signal_date: '2026-10-22', proposed_action: 'buy' as const, labels: [], candidate_ids: ['c1', 'c2'],
  rule_ids: ['trend_reclaim'], entry_passed: false, market_status: null, holding: false,
  candidates: [], brief: { id: 'b1', status: 'ok' as const }, filings: [], news: [], position: null,
}

const basePlan = {
  id: 'p1', ticker: 'NVDA', signal_date: '2026-10-22', plan_version: 'plan-1', status: 'ok' as const,
  entry_low: 98.5, entry_high: 101.5, stop: 94, target1: 112, ref_price: 100, atr: 2,
  valid_from: '2026-10-23', valid_until: '2026-10-27', sizing: null, invalid_reasons: [], warnings: [],
}

describe('decision payload', () => {
  it('maps the choice to the final action the ledger expects', () => {
    expect(finalAction('buy', 'accept')).toBe('buy')
    expect(finalAction('sell', 'reject')).toBe('ignore')
    expect(finalAction('buy', 'downgrade')).toBe('watch')
  })

  it('carries the request id, candidates and brief, and trims the reason', () => {
    expect(decisionPayload(unit as any, 'accept', '  趋势修复 ', 'req-1')).toEqual({
      request_id: 'req-1', ticker: 'NVDA', signal_date: '2026-10-22', candidate_ids: ['c1', 'c2'], brief_id: 'b1',
      proposed_action: 'buy', final_action: 'buy', decision: 'accept', reason: '趋势修复',
      plan_id: null, own_plan: null,
    })
  })

  it('sends plan_id when accepting against a healthy rule plan', () => {
    const withPlan = { ...unit, plan: { id: 'p1', status: 'ok', kind: 'rule' } }
    expect(decisionPayload(withPlan as any, 'accept', 'r', 'req-2')).toMatchObject({ plan_id: 'p1' })
  })

  it('sends own_plan with its own request id when levels are custom', () => {
    const payload = decisionPayload(unit as any, 'accept', 'r', 'req-3', {
      request_id: 'own-1', entry_low: '98.5', entry_high: '101.5', stop: '94', target1: '112',
    })
    expect(payload.own_plan).toEqual({ request_id: 'own-1', entry_low: '98.5', entry_high: '101.5',
                                       stop: '94', target1: '112' })
    expect(payload.plan_id).toBeNull()
  })

  it('rejects own levels that break the ordering', () => {
    expect(levelsError({ entry_low: '99', entry_high: '101.5', stop: '100', target1: '112' })).toContain('止损')
    expect(levelsError({ entry_low: 'abc', entry_high: '101.5', stop: '94', target1: '112' })).toBeTruthy()
    expect(levelsError({ entry_low: '98.5', entry_high: '101.5', stop: '94', target1: '112' })).toBeNull()
  })

  it('does not cite a brief that was rejected as invalid', () => {
    const payload = decisionPayload({ ...unit, brief: { id: 'b2', status: 'error' } } as any, 'reject', 'x', 'r')
    expect(payload.brief_id).toBeNull()
  })
})

describe('requests', () => {
  it('keeps the HTTP status so the page can tell 503 from an empty list', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: '工作台数据表未就绪' }), { status: 503 })))
    const error = await getToday().catch(e => e)
    expect(error).toBeInstanceOf(WorkbenchError)
    expect(error.status).toBe(503)
    expect(describeError(error)).toBe('数据库未就绪：工作台数据表未就绪')
  })

  it('explains a 409 as a newer record', () => {
    expect(describeError(new WorkbenchError('this unit already has a newer decision', 409)))
      .toContain('已有更新的记录')
  })
})

describe('formatting', () => {
  it('never invents a publish time', () => {
    expect(publishedText(null)).toBe('发布时间未知')
    expect(publishedText('2026-10-22T12:00:00Z')).toContain('2026-10-22')
  })

  it('labels rules and formats percentages', () => {
    expect(ruleLabel('earnings_gap_up')).toBe('财报跳空向上')
    expect(ruleLabel('unknown_rule')).toBe('unknown_rule')
    expect(pct(0.0512)).toBe('+5.12%')
    expect(pct(-0.03)).toBe('-3.00%')
    expect(pct(null)).toBe('—')
  })
})

describe('timeline', () => {
  it('merges sources newest first and keeps undated news at its fetch time', () => {
    const items = timeline({
      ticker: 'NVDA', session: '2026-10-22', bars: [], position: null, closed: [],
      filings: [{ id: 1, form: '8-K', filing_date: '2026-10-20', accepted_at: '2026-10-20T20:00:00Z', items: ['2.02'] }],
      news: [{ id: 2, source: 'yfinance', title: 'Undated', url: 'https://x', publisher: null, published_at: null,
               fetched_at: '2026-10-21T10:00:00Z' }],
      candidates: [{ id: 'c', signal_date: '2026-10-22', action: 'buy', rule_id: 'trend_reclaim', created_at: '2026-10-22T22:30:00Z' }],
      decisions: [], trades: [],
    } as any)
    expect(items.map(i => i.kind)).toEqual(['candidate', 'news', 'filing'])
    expect(items[1].text).toContain('发布时间未知')
  })
})


describe('P1 endpoints', () => {
  it('hits account, plan shadow, discipline, monthly and push', async () => {
    const urls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      urls.push(`${init?.method ?? 'GET'} ${String(url)}`)
      return new Response('{}', { status: 200 })
    }))
    await getAccount(); await getPlanShadow(); await getDiscipline(); await getMonthly(); await pushToday()
    expect(urls).toEqual([
      'GET /api/workbench/account/snapshots', 'GET /api/workbench/plans/shadow',
      'GET /api/workbench/discipline', 'GET /api/workbench/monthly-reviews', 'POST /api/workbench/push',
    ])
  })
})

describe('agent track', () => {
  it('AGENT_REASON_TEXT covers every reason', async () => {
    const { AGENT_REASON_TEXT } = await import('./workbench')
    expect(Object.keys(AGENT_REASON_TEXT).sort()).toEqual(['checkpoint_unavailable', 'disabled',
      'invalid_citation', 'level_check', 'malformed', 'max_attempts', 'model_error', 'not_configured',
      'quota_exhausted', 'stage_budget', 'token_budget', 'tool_rounds_exceeded'].sort())
  })

  it('agent basis submits agent plan id', async () => {
    const { decisionPayload } = await import('./workbench')
    const agentPlan: Plan = { ...basePlan, id: 'ap1', kind: 'agent' }
    const withBoth = { ...unit, plan: { ...basePlan, kind: 'rule' as const },
                       agent: { id: 'r1', status: 'ok' as const, model: 'glm-5.3', agent_version: 'agent-1',
                                output: null, counter: null, plan: agentPlan, input_tokens: 0,
                                output_tokens: 0, created_at: '2026-10-22T23:00:00Z' } }
    expect(decisionPayload(withBoth, 'accept', 'r', 'req', null, 'agent')).toMatchObject({ plan_id: 'ap1' })
    expect(decisionPayload(withBoth, 'accept', 'r', 'req', null, 'rule')).toMatchObject({ plan_id: 'p1' })
    expect(decisionPayload(withBoth, 'accept', 'r', 'req', null, 'own')).toMatchObject({ plan_id: null })
  })

  it('plans, shadows and discipline trades carry the agent kind', async () => {
    const wb = await import('./workbench')
    const plan: Plan = { ...basePlan, kind: 'agent', plan_version: 'agent-1' }
    const shadow: PlanShadow = { id: 's1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'agent',
                                 plan_version: 'agent-1', status: 'ok', outcome: {
                                   status: 'expired', fill_date: null, fill_price: null, legs: [], r: null,
                                   return: null, spy_return: null } }
    const trade: DisciplineTrade = { trade_id: 't1', ticker: 'NVDA', track: 'agent', flags: [],
                                     immature: [], r: null }
    expect([plan.kind, shadow.kind, trade.track]).toEqual(['agent', 'agent', 'agent'])
  })
})
