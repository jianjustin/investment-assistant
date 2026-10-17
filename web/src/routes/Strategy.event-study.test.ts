import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import Strategy from './Strategy.svelte'
import * as api from '../lib/api'

const kinds = {
  kinds: ['ma_reclaim', 'score_high'],
  definitions: {
    ma_reclaim: { indicator: 'SMA', period: 20, definition: 'close_cross_above_sma20', not_equivalent_to: '21EMA' },
    score_high: { definition: 'strategy_score_gte', threshold: 70 },
  },
  unavailable: {
    rs_strong: 'relative_strength_spy is a 20-session return difference in decimal units; legacy rs_strong=1.2 has unconfirmed units/intent. Definition suspended pending confirmation',
    eps_beat: 'point-in-time EPS actual/consensus source is not implemented',
    eps_miss: 'point-in-time EPS actual/consensus source is not implemented',
    vcp: 'VCP event definition/source is not implemented',
    vcp_breakout: 'VCP event definition/source is not implemented',
  },
}
const study = (kind = 'ma_reclaim', marker = 'current result') => ({
  result: {
    kind,
    caveats: [marker],
    horizons: { 5: { horizon: 5, n: 42, mean_excess: 0.02, median: 0.01, hit_rate: 0.6, t_stat: 1.5 } },
  },
  degraded: false,
  source: 'computed',
})
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const runButton = () => screen.getByRole('button', { name: '运行' })
const selectKind = (kind: string) => fireEvent.change(screen.getByRole('combobox'), { target: { value: kind } })
async function ready() {
  render(Strategy, { sub: 'event-study' })
  await waitFor(() => expect(runButton()).toBeEnabled())
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('Strategy · event study rendered contract', () => {
  beforeEach(() => {
    history.replaceState(null, '', '#strategy/event-study')
    vi.spyOn(api, 'getStrategyScores').mockResolvedValue({ rows: [] })
    vi.spyOn(api, 'getEventStudyKinds').mockResolvedValue(kinds)
    vi.spyOn(api, 'getEventStudy').mockImplementation(async kind => study(kind))
    // Any accidental request outside the explicit mocks must fail, never reach a service.
    vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Unexpected network request in component test') }))
  })

  it('disables run while definitions are loading, with no legacy rs_strong request', async () => {
    const pending = deferred<typeof kinds>()
    vi.mocked(api.getEventStudyKinds).mockReturnValue(pending.promise)
    render(Strategy, { sub: 'event-study' })
    expect(runButton()).toBeDisabled()
    expect(screen.getByRole('combobox')).toBeDisabled()
    expect(screen.getByText('正在加载事件定义…')).toBeInTheDocument()
    await fireEvent.click(runButton())
    expect(api.getEventStudy).not.toHaveBeenCalled()
    await act(() => pending.resolve(kinds))
    await waitFor(() => expect(runButton()).toBeEnabled())
  })

  it.each([
    ['ma_reclaim', ['ma_reclaim', 'score_high']],
    ['score_high', ['score_high', 'ma_reclaim']],
  ])('falls back to the first available kind, %s, rather than rs_strong', async (first, available) => {
    vi.mocked(api.getEventStudyKinds).mockResolvedValue({ ...kinds, kinds: available })
    await ready()
    expect(screen.getByRole('combobox')).toHaveValue(first)
    expect(screen.getAllByRole('option').map(option => (option as HTMLOptionElement).value)).toEqual(available)
    await fireEvent.click(runButton())
    expect(api.getEventStudy).toHaveBeenCalledWith(first)
    await screen.findByRole('table')
    expect(screen.getByText(/source:/)).toHaveTextContent(`事件类型：${first}`)
  })

  it('renders backend definitions accurately and all suspended/unimplemented reasons', async () => {
    await ready()
    expect(screen.getByText(/当前定义/)).toHaveTextContent('close_cross_above_sma20')
    expect(screen.getByText(/收盘价上穿20日简单移动平均线/)).toHaveTextContent('SMA20')
    expect(screen.getByText(/收盘价上穿20日简单移动平均线/)).toHaveTextContent('不是21EMA')
    expect(screen.getByRole('heading', { name: '已挂起 / 未实现的事件定义' })).toBeInTheDocument()
    for (const [kind, reason] of Object.entries(kinds.unavailable)) {
      expect(screen.getByText(kind).parentElement).toHaveTextContent(reason)
    }
    await selectKind('score_high')
    expect(screen.getByText(/当前定义/)).toHaveTextContent('strategy_score_gte')
    expect(screen.getByText(/当前定义/)).toHaveTextContent('70')
    expect(screen.queryByText(/收盘价上穿20日简单移动平均线/)).not.toBeInTheDocument()
  })

  it('treats definition and unavailable reason strings as text, never HTML', async () => {
    const unsafe = '<img src=x onerror="window.pwned=true">'
    vi.mocked(api.getEventStudyKinds).mockResolvedValue({
      kinds: ['ma_reclaim'],
      definitions: { ma_reclaim: { definition: unsafe } },
      unavailable: { rs_strong: unsafe },
    })
    await ready()
    expect(screen.getByText(/当前定义/)).toHaveTextContent(JSON.stringify({ definition: unsafe }))
    expect(screen.getByText('rs_strong').parentElement).toHaveTextContent(unsafe)
    expect(document.querySelector('img')).toBeNull()
  })

  it('keeps run disabled and reports a failed kinds request', async () => {
    vi.mocked(api.getEventStudyKinds).mockRejectedValue(new Error('事件定义服务不可用'))
    render(Strategy, { sub: 'event-study' })
    expect(await screen.findByRole('alert')).toHaveTextContent('事件定义加载失败：事件定义服务不可用')
    expect(runButton()).toBeDisabled()
    await fireEvent.click(runButton())
    expect(api.getEventStudy).not.toHaveBeenCalled()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('keeps an empty available list disabled while still explaining unavailable kinds', async () => {
    vi.mocked(api.getEventStudyKinds).mockResolvedValue({ ...kinds, kinds: [] })
    render(Strategy, { sub: 'event-study' })
    expect(await screen.findByText('暂无可运行的事件定义，已禁用运行。')).toBeInTheDocument()
    expect(runButton()).toBeDisabled()
    expect(screen.getByRole('combobox')).toBeDisabled()
    expect(screen.getByText('rs_strong').parentElement).toHaveTextContent(kinds.unavailable.rs_strong)
    await fireEvent.click(runButton())
    expect(api.getEventStudy).not.toHaveBeenCalled()
  })

  it('remains compatible with a kinds-only payload', async () => {
    vi.mocked(api.getEventStudyKinds).mockResolvedValue({ kinds: ['score_high'] })
    await ready()
    expect(screen.getByRole('combobox')).toHaveValue('score_high')
    expect(screen.queryByRole('heading', { name: '已挂起 / 未实现的事件定义' })).toBeNull()
    await fireEvent.click(runButton())
    expect(api.getEventStudy).toHaveBeenCalledWith('score_high')
  })

  it('shows the actual backend error message as plain text, not just HTTP 400', async () => {
    vi.mocked(api.getEventStudy).mockRestore()
    const reason = 'definition suspended: <img src=x onerror="window.pwned=true"> threshold units unconfirmed'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ message: reason }), { status: 400 })))
    await ready()
    await fireEvent.click(runButton())
    expect(await screen.findByRole('alert')).toHaveTextContent(`运行失败：${reason}`)
    expect(screen.queryByRole('table')).toBeNull()
    expect(document.querySelector('img')).toBeNull()
    expect(runButton()).toBeEnabled()
  })

  it('clears old results when switching kinds and does not resurrect them when switching back', async () => {
    await ready()
    await fireEvent.click(runButton())
    await screen.findByRole('table')
    expect(screen.getByText(/current result/)).toBeInTheDocument()
    await selectKind('score_high')
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.queryByText(/current result/)).toBeNull()
    await selectKind('ma_reclaim')
    expect(screen.queryByRole('table')).toBeNull()
    expect(api.getEventStudy).toHaveBeenCalledTimes(1)
  })

  it('ignores a pending result after switching away even before another run starts', async () => {
    const old = deferred<ReturnType<typeof study>>()
    vi.mocked(api.getEventStudy).mockReturnValueOnce(old.promise)
    await ready()
    await fireEvent.click(runButton())
    await selectKind('score_high')
    await act(() => old.resolve(study('ma_reclaim', 'stale result')))
    expect(screen.getByRole('combobox')).toHaveValue('score_high')
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.queryByText(/stale result/)).toBeNull()
    await fireEvent.click(runButton())
    await screen.findByRole('table')
    expect(screen.getByText(/source:/)).toHaveTextContent('事件类型：score_high')
    expect(api.getEventStudy).toHaveBeenLastCalledWith('score_high')
  })

  it('clears a previous success immediately on rerun and keeps it cleared on failure', async () => {
    const pending = deferred<ReturnType<typeof study>>()
    vi.mocked(api.getEventStudy).mockResolvedValueOnce(study()).mockReturnValueOnce(pending.promise)
    await ready()
    await fireEvent.click(runButton())
    await screen.findByRole('table')
    await fireEvent.click(runButton())
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByRole('button', { name: '计算中…' })).toBeDisabled()
    await act(() => pending.reject(new Error('资料不足，不可计算')))
    expect(await screen.findByRole('alert')).toHaveTextContent('资料不足，不可计算')
    expect(screen.queryByRole('table')).toBeNull()
    await selectKind('score_high')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it.each([
    ['success', 'before'], ['failure', 'before'],
    ['success', 'after'], ['failure', 'after'],
  ])('ignores a stale %s arriving %s the current request after A → B → A', async (outcome, timing) => {
    const old = deferred<ReturnType<typeof study>>()
    const current = deferred<ReturnType<typeof study>>()
    vi.mocked(api.getEventStudy).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    await ready()
    await fireEvent.click(runButton())
    await selectKind('score_high')
    expect(runButton()).toBeEnabled()
    await selectKind('ma_reclaim')
    await fireEvent.click(runButton())
    expect(api.getEventStudy).toHaveBeenCalledTimes(2)
    const finishOld = () => outcome === 'success' ? old.resolve(study('ma_reclaim', 'stale result')) : old.reject(new Error('stale failure'))
    if (timing === 'before') {
      await act(finishOld)
      expect(screen.getByRole('button', { name: '计算中…' })).toBeDisabled()
      expect(screen.queryByRole('table')).toBeNull()
    }
    await act(() => current.resolve(study('ma_reclaim', 'fresh result')))
    await screen.findByRole('table')
    if (timing === 'after') await act(finishOld)
    expect(screen.getByText(/fresh result/)).toBeInTheDocument()
    expect(screen.queryByText(/stale result/)).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(runButton()).toBeEnabled()
  })

  it('does not accept a response labelled with a different event kind', async () => {
    vi.mocked(api.getEventStudy).mockResolvedValue(study('score_high'))
    await ready()
    await fireEvent.click(runButton())
    expect(await screen.findByRole('alert')).toHaveTextContent('返回的事件类型与当前选择不一致')
    expect(screen.queryByRole('table')).toBeNull()
  })
})

describe('Strategy event-study GET error details and compatibility', () => {
  it.each(['error', 'message', 'detail'])('preserves a backend %s string for both event-study endpoints', async key => {
    const reason = 'rs_strong unavailable: threshold units pending confirmation'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ [key]: reason }), { status: 400 })))
    await expect(api.getEventStudy('rs_strong')).rejects.toThrow(reason)
    await expect(api.getEventStudyKinds()).rejects.toThrow(reason)
  })

  it('prefers error, and skips empty/non-string error fields in favour of a useful message', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: 'specific reason', message: 'generic reason' }), { status: 400 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 1 }, message: 'useful message' }), { status: 400 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: ' ', detail: 'useful detail' }), { status: 400 })))
    await expect(api.getEventStudy('rs_strong')).rejects.toThrow('specific reason')
    await expect(api.getEventStudy('rs_strong')).rejects.toThrow('useful message')
    await expect(api.getEventStudy('rs_strong')).rejects.toThrow('useful detail')
  })

  it.each(['<html>upstream failed</html>', '', 'null', '[]', '{"error":{"code":1}}'])('falls back to HTTP status for unusable error body %s', async body => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 502 })))
    await expect(api.getEventStudy('ma_reclaim')).rejects.toThrow('HTTP 502')
  })

  it('preserves successful response shapes, GET headers, no-store policy and query arguments', async () => {
    const result = study()
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(kinds)))
      .mockResolvedValueOnce(new Response(JSON.stringify(result)))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'up', extra: null })))
    vi.stubGlobal('fetch', fetchMock)
    expect(await api.getEventStudyKinds()).toEqual(kinds)
    expect(await api.getEventStudy('ma_reclaim', '2026-01-01', '2026-10-16')).toEqual(result)
    expect(await api.getStatus()).toEqual({ status: 'up', extra: null })
    const init = { headers: { Accept: 'application/json' }, cache: 'no-store' }
    expect(fetchMock.mock.calls).toEqual([
      ['/api/research/event-study/kinds', init],
      ['/api/research/event-study?kind=ma_reclaim&since=2026-01-01&asof=2026-10-16', init],
      ['/api/status', init],
    ])
  })

  it('leaves generic GET failure behaviour unchanged without consuming its body', async () => {
    const json = vi.fn(async () => ({ error: 'must not change unrelated endpoints' }))
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403, json })))
    await expect(api.get('/api/other')).rejects.toThrow('HTTP 403')
    await expect(api.getStatus()).rejects.toThrow('HTTP 403')
    expect(json).not.toHaveBeenCalled()
  })

  it('preserves transport errors instead of replacing them with a parsing error', async () => {
    const failure = new Error('offline transport')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(failure))
    await expect(api.getEventStudy('ma_reclaim')).rejects.toBe(failure)
    await expect(api.get('/api/other')).rejects.toBe(failure)
  })
})
