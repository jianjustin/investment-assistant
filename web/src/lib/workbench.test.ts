import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  WorkbenchError, decisionPayload, describeError, finalAction, getToday, pct, publishedText, ruleLabel, timeline,
} from './workbench'

afterEach(() => vi.unstubAllGlobals())

const unit = {
  ticker: 'NVDA', signal_date: '2026-10-22', proposed_action: 'buy' as const, labels: [], candidate_ids: ['c1', 'c2'],
  rule_ids: ['trend_reclaim'], entry_passed: false, market_status: null, holding: false,
  candidates: [], brief: { id: 'b1', status: 'ok' as const }, filings: [], news: [], position: null,
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
    })
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
