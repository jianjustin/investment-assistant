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

describe('run detail, resume, rerun and agent connection wrappers (v2.8 §11.1)', () => {
  const RID = 'daily-20261030033000-1a2b3c4d'
  let calls: { url: string; method: string; body: any }[]
  const respond = (status: number, body: unknown) => {
    calls = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined })
      return new Response(JSON.stringify(body), { status })
    }))
  }

  it('the ten functions use the spec paths and methods', async () => {
    respond(200, {})
    await api.getRunDetail(RID)
    await api.resumeDaily(RID, 'collect')
    await api.runDaily()
    await api.rerunAgent({ ticker: 'NVDA', signal_date: '2026-10-29', mode: 'propose', request_id: 'r1', origin: 'run_detail' })
    await api.getAgentConnection()
    await api.startAgentLogin()
    await api.cancelAgentLogin()
    await api.disconnectAgent()
    await api.getAgentModels()
    await api.setAgentModel('gpt-x')
    expect(calls.map(c => `${c.method} ${c.url}`)).toEqual([
      `GET /api/runs/${RID}/detail`,
      'POST /api/jobs/daily/resume',
      'POST /api/jobs/daily/run',
      'POST /api/workbench/agent-runs/rerun',
      'GET /api/settings/agent-connection',
      'POST /api/settings/agent-connection/login',
      'POST /api/settings/agent-connection/cancel',
      'DELETE /api/settings/agent-connection',
      'GET /api/settings/agent-connection/models',
      'PUT /api/settings/agent-connection/model',
    ])
  })

  it('write calls carry a request_id (a fresh uuid unless the caller passes one)', async () => {
    respond(200, {})
    await api.resumeDaily(RID, 'collect', 'req-1')
    await api.resumeDaily(RID, 'collect')
    await api.runDaily()
    await api.setAgentModel('gpt-x')
    expect(calls[0].body).toEqual({ run_id: RID, node: 'collect', request_id: 'req-1' })
    expect(calls[1].body.request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(calls[1].body.request_id).not.toBe('req-1')
    expect(calls[2].body.request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(calls[3].body).toMatchObject({ slug: 'gpt-x' })
    expect(calls[3].body.request_id).toBeTruthy()
  })

  it('rerunAgent sends the body as given', async () => {
    respond(200, { reset_id: 1, run_id: null, replayed: false })
    const body = { ticker: 'NVDA', signal_date: '2026-10-29', mode: 'interpret' as const, request_id: 'r1', origin: 'plan_page' as const }
    expect(await api.rerunAgent(body)).toEqual({ reset_id: 1, run_id: null, replayed: false })
    expect(calls[0].body).toEqual(body)
  })

  it('errors keep the status and a machine code from {"error": code}', async () => {
    respond(409, { error: 'node_mismatch' })
    const err: any = await api.resumeDaily(RID, 'screen').catch(e => e)
    expect(err).toBeInstanceOf(api.ApiError)
    expect([err.status, err.code, err.message]).toEqual([409, 'node_mismatch', 'node_mismatch'])
    respond(409, { error: 'not_needed: 这个单元不需要重跑' })
    expect(((await api.rerunAgent({} as any).catch(e => e)) as any).code).toBe('not_needed')
    respond(409, { error: { code: 'daily_running', message: '每日工作流正在运行' } })
    const nested: any = await api.runDaily().catch(e => e)
    expect([nested.code, nested.message]).toEqual(['daily_running', '每日工作流正在运行'])
    respond(404, { error: '没有这次运行' })
    const missing: any = await api.getRunDetail(RID).catch(e => e)
    expect([missing.status, missing.code]).toEqual([404, null])
    respond(503, null)
    expect(((await api.getAgentConnection().catch(e => e)) as any).message).toBe('HTTP 503')
  })

  it('getAgentRuns asks for the runs since a date', async () => {
    respond(200, { runs: [] })
    await api.getAgentRuns('2026-10-29')
    expect(calls[0]).toMatchObject({ method: 'GET', url: '/api/workbench/agent-runs?since=2026-10-29' })
  })
})
