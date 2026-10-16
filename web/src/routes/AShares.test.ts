import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, act } from '@testing-library/svelte'
import AShares from './AShares.svelte'
import * as api from '../lib/api'

const fixture = () => ({
  profile: { name: '测试证券', board: '科创板' }, window: { start: '2026-09-01', end: '2026-10-15' },
  statuses: [{ dataset: 'announcements', status: 'failed', error: 'HTTP 429', stored_rows: 0 }],
  bars: [], raw_bars: [], performance: {}, valuation: null, adjustment: { basis:'qfq', missing_sessions: 0 },
  coverage: { requested_sessions: 1, missing_sessions: ['2026-09-01'] }, financials: [],
  announcements: [], disclosure: [], unlocks: [], comparisons: [], calendar: {}, pit: {},
  upstream: { version: '0.16.0', commit: 'c118038' }, card: null,
})

describe('A-share research boundaries', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    window.location.hash = '#data/ashares'
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[{ ticker:'600519.SH', name:'贵州茅台', status:'active' }, { ticker:'688008.SH', name:'澜起科技', status:'active' }] })
  })
  it('source failure is visible rather than a no-risk conclusion', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(fixture())
    render(AShares)
    expect(await screen.findByText('HTTP 429')).toBeTruthy()
    expect(screen.getByText('来源失败')).toBeTruthy()
    expect(screen.getByText(/不能据此判断没有公告或风险/)).toBeTruthy()
  })
  it('switches quarter vs cumulative amounts without differencing balance stocks', async () => {
    const f = fixture() as any
    f.financials = [{ period_end: '2026-06-30', revenue: 250e8, inventory: 17e8, receivables: 5e8,
      quarter: { revenue: 150e8 }, quarter_inputs: [1, 2], ttm_periods: [], limitations: [], origins: {} }]
    vi.spyOn(api, 'get').mockResolvedValue(f)
    render(AShares)
    expect(await screen.findByText('250')).toBeTruthy()
    await fireEvent.change(screen.getByLabelText('财务期间口径'), { target: { value: 'quarter' } })
    expect(screen.getByText('150')).toBeTruthy()
    expect(screen.getByText('17')).toBeTruthy()
  })
  it('retains the displayed price basis when loading another basis fails', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(fixture()).mockRejectedValueOnce(new Error('source unavailable'))
    render(AShares)
    await screen.findByText('区间收益 · qfq')
    await fireEvent.change(screen.getByLabelText('价格口径'), { target: { value:'raw' } })
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('区间收益 · qfq')).toBeTruthy()
    expect(screen.queryByText('区间收益 · raw')).toBeNull()
  })
})


describe('A-share selection and navigation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    window.location.hash = '#data/ashares'
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[{ ticker:'600519.SH', name:'贵州茅台', status:'active' }, { ticker:'688008.SH', name:'澜起科技', status:'active' }] })
  })
  it('starts from the first actual watchlist entry and carries identity into the card link', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue(fixture())
    render(AShares)
    await screen.findByText('HTTP 429')
    expect(get).toHaveBeenCalledWith(expect.stringContaining('/api/ashares/600519.SH/research?'))
    expect(screen.getByRole('link', { name:'打开研究观察卡 →' }).getAttribute('href')).toBe('#strategy/observation?market=CN&symbol=600519.SH')
  })
  it('honors a refreshed deep link over first watchlist entry', async () => {
    window.location.hash = '#data/ashares?market=CN&symbol=688008.SH'
    const get = vi.spyOn(api, 'get').mockResolvedValue(fixture())
    render(AShares)
    await screen.findByText('HTTP 429')
    expect(get).toHaveBeenCalledWith(expect.stringContaining('/api/ashares/688008.SH/research?'))
  })
  it('does not fetch any stock when the watchlist is empty', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[] })
    const get = vi.spyOn(api, 'get').mockResolvedValue(fixture())
    render(AShares)
    await screen.findByText('暂无A股关注证券，请先在关注列表添加。')
    expect(get).not.toHaveBeenCalled()
  })
  it('rejects an older response after choosing a different stock', async () => {
    let finish: (value:any) => void = () => {}
    const first = new Promise(resolve => { finish = resolve })
    vi.spyOn(api, 'get').mockReturnValueOnce(first).mockResolvedValueOnce({ ...fixture(), profile:{ name:'新证券', board:'科创板' } })
    render(AShares)
    const picker = await screen.findByRole('combobox', { name:'关注证券' })
    await screen.findByText('688008.SH 澜起科技')
    await fireEvent.change(picker, { target:{ value:'688008.SH' } })
    await screen.findByRole('heading', { name:/新证券/ })
    await act(async () => { finish({ ...fixture(), profile:{ name:'旧证券', board:'主板' } }) })
    await waitFor(() => expect(screen.queryByRole('heading', { name:/旧证券/ })).toBeNull())
  })
  it('changes identity on same-page browser hash navigation', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(fixture())
    render(AShares)
    await screen.findByText('HTTP 429')
    window.location.hash = '#data/ashares?market=CN&symbol=688008.SH'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    expect(api.get).toHaveBeenLastCalledWith(expect.stringContaining('/api/ashares/688008.SH/research?'))
  })
})

it('preserves the displayed stock when a dirty-change guard refuses navigation', async () => {
  vi.restoreAllMocks()
  window.location.hash = '#data/ashares?market=CN&symbol=600519.SH'
  vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[{ ticker:'600519.SH', status:'active' }, { ticker:'688008.SH', status:'active' }] })
  const get = vi.spyOn(api, 'get').mockResolvedValue(fixture())
  render(AShares, { beforeChange:() => false })
  await screen.findByText('HTTP 429')
  await fireEvent.change(screen.getByRole('combobox', { name:'关注证券' }), { target:{ value:'688008.SH' } })
  expect(get).toHaveBeenCalledTimes(1)
  expect(window.location.hash).toContain('symbol=600519.SH')
})

it('adds a deep-linked stock without inventing industry tags and confirms server state', async () => {
  vi.restoreAllMocks()
  window.location.hash = '#data/ashares?market=CN&symbol=600519.SH'
  const existing = { rows:[{ ticker:'688008.SH', status:'active' }] }
  const list = vi.spyOn(api, 'getWatchlist').mockResolvedValueOnce(existing).mockResolvedValueOnce(existing).mockResolvedValueOnce({ rows:[{ ticker:'600519.SH', status:'active' }] })
  vi.spyOn(api, 'get').mockResolvedValue(fixture())
  const add = vi.spyOn(api, 'addWatchlistItem').mockResolvedValue({})
  render(AShares)
  await screen.findByText('HTTP 429')
  await fireEvent.click(screen.getByRole('button', { name:'加入关注' }))
  await screen.findByText('已加入现有关注列表。')
  expect(add).toHaveBeenCalledWith({ ticker:'600519.SH', status:'active' })
  expect(list).toHaveBeenCalledTimes(3)
})

it('does not apply an old watchlist result after leaving and returning to the same stock', async () => {
  vi.restoreAllMocks()
  window.location.hash = '#data/ashares?market=CN&symbol=600519.SH'
  const rows = [{ ticker:'600519.SH', status:'active' }, { ticker:'688008.SH', status:'active' }]
  let finish: (value:any) => void = () => {}
  vi.spyOn(api, 'getWatchlist').mockResolvedValueOnce({ rows }).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  vi.spyOn(api, 'get').mockResolvedValue(fixture())
  render(AShares)
  await screen.findByText('HTTP 429')
  await fireEvent.click(screen.getByRole('button', { name:'加入关注' }))
  await fireEvent.change(screen.getByRole('combobox', { name:'关注证券' }), { target:{ value:'688008.SH' } })
  await fireEvent.change(screen.getByRole('combobox', { name:'关注证券' }), { target:{ value:'600519.SH' } })
  await act(async () => { finish({ rows }) })
  expect(screen.queryByText('已在关注列表中，可在设置中编辑现有记录。')).toBeNull()
})

 it('loads a valid explicit URL even if the watchlist service fails',async()=>{
 vi.restoreAllMocks()
 history.replaceState(null,'','#data/ashares?market=CN&symbol=600519.SH')
 vi.spyOn(api,'getWatchlist').mockRejectedValue(new Error('offline'))
 vi.spyOn(api,'get').mockResolvedValue(fixture())
 render(AShares)
 expect(await screen.findByText('HTTP 429')).toBeInTheDocument()
 expect(screen.getByRole('link',{name:'打开研究观察卡 →'})).toHaveAttribute('href','#strategy/observation?market=CN&symbol=600519.SH')
})
