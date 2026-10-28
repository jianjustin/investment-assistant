import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { get, post, pollRun } from './api'
import * as api from './api'

afterEach(() => vi.restoreAllMocks())

describe('jobs/settings api wrappers', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, json: async () => ({ ok: true }),
    })))
  })

  it('getJobReports builds task+limit query', async () => {
    await api.getJobReports('metrics', 10)
    const url = (fetch as any).mock.calls[0][0]
    expect(url).toContain('/api/jobs/reports')
    expect(url).toContain('task=metrics')
    expect(url).toContain('limit=10')
  })

  it('getWatchlist(true) requests ?enriched=true only', async () => {
    await api.getWatchlist(true)
    expect((fetch as any).mock.calls[0][0]).toBe('/api/watchlist?enriched=true')
    await api.getWatchlist()
    expect((fetch as any).mock.calls[1][0]).toBe('/api/watchlist')
  })

  it('runJob posts to /run', async () => {
    await api.runJob('metrics')
    expect((fetch as any).mock.calls[0][0]).toBe('/api/jobs/metrics/run')
  })

  it('patchScheduledJob uses PATCH', async () => {
    await api.patchScheduledJob('metrics', { time_local: '09:30' })
    expect((fetch as any).mock.calls[0][1].method).toBe('PATCH')
  })

  it('testNotifyChannel posts channel', async () => {
    await api.testNotifyChannel({ channel: 'signals', url: 'u' })
    expect((fetch as any).mock.calls[0][0]).toBe('/api/settings/notify/test')
  })
})

describe('api client', () => {
  it('get parses json', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })))
    expect(await get<{ ok: boolean }>('/api/status')).toEqual({ ok: true })
  })
  it('throws on non-ok', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"error":"x"}', { status: 400 })))
    await expect(post('/api/x', {})).rejects.toThrow()
  })
  it('pollRun resolves when done', async () => {
    const seq = [{ status: 'pending' }, { status: 'done', result: { v: 1 } }]
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(seq.shift()), { status: 200 })))
    const rec = await pollRun('rid', { intervalMs: 1 })
    expect(rec.status).toBe('done')
  })
})


describe('v2.7 growth-loop wrappers (spec 12)', () => {
  let seen: { url: string; method: string; body: unknown }[]
  beforeEach(() => {
    seen = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      seen.push({ url: String(url), method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined })
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    }))
  })
  const last = () => seen[seen.length - 1]

  it('review cards', async () => {
    await api.getReviewCards({})
    expect(last()).toMatchObject({ url: '/api/workbench/review-cards', method: 'GET' })
    await api.getReviewCards({ status: 'to_review', ticker: 'NVDA', since: '2026-10-01' })
    expect(last().url).toBe('/api/workbench/review-cards?status=to_review&ticker=NVDA&since=2026-10-01')
    await api.getReviewCard(12)
    expect(last().url).toBe('/api/workbench/review-cards/12')
    await api.postCardVerdict(12, { request_id: 'r', note: 'n', lessons: [] })
    expect(last()).toMatchObject({ url: '/api/workbench/review-cards/12/verdict', method: 'POST',
                                   body: { request_id: 'r', note: 'n', lessons: [] } })
    await api.redraftCard(12)
    expect(last()).toMatchObject({ url: '/api/workbench/review-cards/12/redraft', method: 'POST' })
  })

  it('my knowledge', async () => {
    await api.getMyKnowledge({})
    expect(last().url).toBe('/api/workbench/my-knowledge')
    await api.getMyKnowledge({ ticker: 'AAPL', concept: 'plan.stop', status: 'all' })
    expect(last().url).toBe('/api/workbench/my-knowledge?ticker=AAPL&concept=plan.stop&status=all')
    await api.postMyKnowledge({ request_id: 'r', title: 't' })
    expect(last()).toMatchObject({ url: '/api/workbench/my-knowledge', method: 'POST' })
    await api.getKnowledgeItem(3)
    expect(last().url).toBe('/api/workbench/my-knowledge/3')
    await api.getKnowledgeItem(3, 2)
    expect(last().url).toBe('/api/workbench/my-knowledge/3?version=2')
    await api.postKnowledgeVersion(3, { request_id: 'r', base_version: 2 })
    expect(last()).toMatchObject({ url: '/api/workbench/my-knowledge/3/versions', method: 'POST', body: { base_version: 2 } })
    await api.postKnowledgeStatus(3, { request_id: 'r', status: 'archived', reason: '过时' })
    expect(last()).toMatchObject({ url: '/api/workbench/my-knowledge/3/status', method: 'POST',
                                   body: { status: 'archived', reason: '过时' } })
    await api.getKnowledgePerformance(3)
    expect(last().url).toBe('/api/workbench/my-knowledge/3/performance')
  })

  it('knowledge drafts', async () => {
    await api.getKnowledgeDrafts('open')
    expect(last().url).toBe('/api/workbench/my-knowledge-drafts?status=open')
    await api.getKnowledgeDrafts('all')
    expect(last().url).toBe('/api/workbench/my-knowledge-drafts?status=all')
    await api.postDraftVerdict(9, { request_id: 'r', action: 'dismiss' })
    expect(last()).toMatchObject({ url: '/api/workbench/my-knowledge-drafts/9/verdict', method: 'POST' })
  })

  it('discussions', async () => {
    await api.postDiscussion({ request_id: 'r', context: { kind: 'plan', plan_id: 'p1' } })
    expect(last()).toMatchObject({ url: '/api/workbench/discussions', method: 'POST',
                                   body: { context: { kind: 'plan', plan_id: 'p1' } } })
    await api.getDiscussions({ plan_id: 'p1' })
    expect(last().url).toBe('/api/workbench/discussions?plan_id=p1')
    await api.getDiscussions({ card_id: 4 })
    expect(last().url).toBe('/api/workbench/discussions?card_id=4')
    await api.getDiscussion(5)
    expect(last().url).toBe('/api/workbench/discussions/5')
    await api.postDiscussionTurn(5, { request_id: 'r', body: '为什么？' })
    expect(last()).toMatchObject({ url: '/api/workbench/discussions/5/turns', method: 'POST', body: { body: '为什么？' } })
  })

  it('keeps the HTTP status of a conflict so pages can read the code', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'discussion_busy' }), { status: 409 })))
    await expect(api.postDiscussionTurn(5, { request_id: 'r', body: 'x' })).rejects.toMatchObject({ status: 409, message: 'discussion_busy' })
  })
})
