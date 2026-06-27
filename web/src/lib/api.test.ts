import { describe, it, expect, vi, afterEach } from 'vitest'
import { get, post, pollRun } from './api'

afterEach(() => vi.restoreAllMocks())

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
