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

  it('runJob posts to /run', async () => {
    await api.runJob('metrics')
    expect((fetch as any).mock.calls[0][0]).toBe('/api/jobs/metrics/run')
  })

  it('patchScheduledJob uses PATCH', async () => {
    await api.patchScheduledJob('metrics', { time_local: '09:30' })
    expect((fetch as any).mock.calls[0][1].method).toBe('PATCH')
  })

  it('testNotifyChannel posts channel', async () => {
    await api.testNotifyChannel({ channel: 'daily', url: 'u' })
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
