import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Watchlist from './Watchlist.svelte'
import * as api from '../api'
const rows = [
  { ticker:'MU', market:'US', status:'active', thesis:'cycle', tags:['memory'], updated_at:'2026-10-16T00:00:00Z' },
  { ticker:'NVDA', market:'US', name:'NVIDIA', status:'active', thesis:'cashflow', tags:['consumer'], updated_at:'2026-10-16T00:00:00Z' },
]
beforeEach(() => { vi.restoreAllMocks() })
describe('shared watchlist editor', () => {
  it('watchlist shows no market tabs', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows } as any)
    render(Watchlist)
    await screen.findByText('NVIDIA')
    expect(screen.queryByRole('navigation', { name:'关注市场' })).toBeNull()
    expect(screen.queryByRole('button', { name:'CN' })).toBeNull()
  })
  it('preserves thesis/tags on status changes with server read-back', async () => {
    const get = vi.spyOn(api, 'getWatchlist').mockResolvedValueOnce({ rows } as any).mockResolvedValue({ rows:[rows[0], {...rows[1], status:'paused'}] } as any)
    const save = vi.spyOn(api, 'addWatchlistItem').mockResolvedValue({} as any)
    render(Watchlist)
    await screen.findByText('NVIDIA')
    await fireEvent.click(screen.getAllByRole('button', { name:'暂停' })[1])
    await waitFor(() => expect(save).toHaveBeenCalledWith({ ticker:'NVDA', status:'paused', expected_updated_at:'2026-10-16T00:00:00Z' }))
    expect(get).toHaveBeenCalledTimes(2)
    expect(await screen.findByRole('button', { name:'恢复' })).toBeTruthy()
  })
  it('edits existing user thesis and tags instead of replacing them with defaults', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[rows[1]] } as any)
    const save = vi.spyOn(api, 'addWatchlistItem').mockResolvedValue({} as any)
    render(Watchlist)
    await fireEvent.click(await screen.findByRole('button', { name:'编辑' }))
    expect((screen.getByLabelText('论点') as HTMLInputElement).value).toBe('cashflow')
    expect((screen.getByLabelText('标签') as HTMLInputElement).value).toBe('consumer')
    await fireEvent.input(screen.getByLabelText('论点'), { target:{ value:'updated thesis' } })
    await fireEvent.click(screen.getByRole('button', { name:'保存' }))
    await waitFor(() => expect(save).toHaveBeenCalledWith({ ticker:'NVDA', status:'active', thesis:'updated thesis', tags:['consumer'], expected_updated_at:'2026-10-16T00:00:00Z' }))
  })
  it('saves the confirmed candidate symbol', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[] } as any)
    vi.spyOn(api, 'get').mockResolvedValue({ candidates:[{ symbol:'BRK.B', market:'US', asset_type:'stock' }] })
    const save = vi.spyOn(api, 'addWatchlistItem').mockResolvedValue({} as any)
    render(Watchlist)
    await fireEvent.click(await screen.findByRole('button', { name:'+ 添加' }))
    expect(screen.getByLabelText('证券代码')).toHaveAttribute('placeholder', 'MU / BRK.B')
    await fireEvent.input(screen.getByLabelText('证券代码'), { target:{ value:'brk.b' } })
    await fireEvent.click(screen.getByRole('button', { name:'确认身份' }))
    expect(save).not.toHaveBeenCalled()
    await fireEvent.click(await screen.findByRole('button', { name:'BRK.B' }))
    await fireEvent.click(screen.getByRole('button', { name:'保存' }))
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ ticker:'BRK.B', tags:[] })))
  })
  it('keeps the edit form open when server read-back fails', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValueOnce({ rows:[rows[1]] } as any).mockRejectedValueOnce(new Error('read-back unavailable'))
    vi.spyOn(api, 'addWatchlistItem').mockResolvedValue({} as any)
    render(Watchlist)
    await fireEvent.click(await screen.findByRole('button', { name:'编辑' }))
    await fireEvent.click(screen.getByRole('button', { name:'保存' }))
    await screen.findByRole('alert')
    expect(screen.getByLabelText('论点')).toBeTruthy()
  })
  it('retains user changes after a version conflict', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[rows[1]] } as any)
    vi.spyOn(api, 'addWatchlistItem').mockRejectedValue(new Error('409 record changed'))
    render(Watchlist)
    await fireEvent.click(await screen.findByRole('button', { name:'编辑' }))
    await fireEvent.input(screen.getByLabelText('论点'), { target:{ value:'unsaved work' } })
    await fireEvent.click(screen.getByRole('button', { name:'保存' }))
    await screen.findByRole('alert')
    expect((screen.getByLabelText('论点') as HTMLInputElement).value).toBe('unsaved work')
  })
  it('ignores candidate resolution after the user changes the input', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[] } as any)
    let finish: (value:any) => void = () => {}
    vi.spyOn(api, 'get').mockReturnValue(new Promise(resolve => { finish = resolve }))
    render(Watchlist)
    await fireEvent.click(await screen.findByRole('button', { name:'+ 添加' }))
    await fireEvent.input(screen.getByLabelText('证券代码'), { target:{ value:'MU' } })
    await fireEvent.click(screen.getByRole('button', { name:'确认身份' }))
    await fireEvent.input(screen.getByLabelText('证券代码'), { target:{ value:'NVDA' } })
    finish({ candidates:[{ symbol:'MU', market:'US', asset_type:'stock' }] })
    await Promise.resolve()
    expect(screen.queryByRole('button', { name:'MU' })).toBeNull()
  })
})
it('labels earnings events', async () => {
  vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[{...rows[0], next_event:{date:'2026-11-19', kind:'earnings', title:null}}] } as any)
  render(Watchlist)
  expect(await screen.findByText('2026-11-19')).toBeInTheDocument()
  expect(screen.getByText('财报')).toBeInTheDocument()
})

it('shows persisted US coverage in readable Chinese',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({rows:[{...rows[0],name:'Micron',latest_period:'2026-09-03',datasets:{financials:{status:'failed'}},next_event:null}]}),{status:200})))
 try{
  render(Watchlist)
  await screen.findByText('Micron')
  expect(screen.getByText('标准财务: 来源失败')).toBeInTheDocument()
  expect(screen.getByText('尚无财报日')).toBeInTheDocument()
 }finally{vi.unstubAllGlobals()}
})


it('shows unsupported legacy identities for deletion',async()=>{
 const legacy={ticker:'AAPL.US',market:null,status:'active',identity_error:'证券身份无效，请删除后使用完整有效代码重新添加'}
 vi.spyOn(api,'getWatchlist').mockResolvedValue({rows:[rows[0],legacy]} as any)
 const remove=vi.spyOn(api,'deleteWatchlistItem').mockResolvedValue({})
 render(Watchlist)
 await screen.findByText('AAPL.US')
 expect(screen.getByText(/证券身份无效/)).toBeInTheDocument()
 await fireEvent.click(screen.getAllByRole('button',{name:'删除'})[1])
 expect(remove).toHaveBeenCalledWith('AAPL.US')
})

describe('pool tier controls', () => {
  const usRows = [
    { ticker: 'NVDA', market: 'US', status: 'active', thesis: 'ai', tags: ['core', 'sector:SMH'], updated_at: '2026-10-16T00:00:00Z' },
    { ticker: 'MU', market: 'US', status: 'active', thesis: '', tags: [], updated_at: '2026-10-16T00:00:00Z' },
    { ticker: 'AMD', market: 'US', status: 'paused', thesis: '', tags: [], updated_at: '2026-10-16T00:00:00Z' },
    { ticker: '600519.SH', market: null, identity_error: '证券身份无效，请删除后使用完整有效代码重新添加', status: 'active', thesis: '', tags: [], updated_at: '2026-10-16T00:00:00Z' },  // invalid US code
  ]
  it('header shows pool and core counts', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows: usRows } as any)
    render(Watchlist)
    expect(await screen.findByText('美股池 2/100 · 核心 1/15')).toBeTruthy()
  })
  it('core checkbox writes core tag', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows: usRows } as any)
    const save = vi.spyOn(api, 'addWatchlistItem').mockResolvedValue({} as any)
    render(Watchlist)
    const box = await screen.findByRole('checkbox', { name: '核心池 MU' })
    await fireEvent.click(box)
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ ticker: 'MU', tags: ['core'] })))
  })
  it('sector select writes sector tag', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows: usRows } as any)
    const save = vi.spyOn(api, 'addWatchlistItem').mockResolvedValue({} as any)
    render(Watchlist)
    const select = await screen.findByRole('combobox', { name: '行业 ETF NVDA' })
    await fireEvent.change(select, { target: { value: 'XLK' } })
    await waitFor(() => expect(save).toHaveBeenCalledWith(
      expect.objectContaining({ ticker: 'NVDA', tags: ['core', 'sector:XLK'] })))
  })
  it('server 400 detail is shown and row unchanged', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows: usRows } as any)
    vi.spyOn(api, 'addWatchlistItem').mockRejectedValue(new Error('核心池超出上限：16 > 15'))
    render(Watchlist)
    await screen.findByText('美股池 2/100 · 核心 1/15')
    await fireEvent.click(screen.getByRole('checkbox', { name: '核心池 MU' }))
    await screen.findByText(/核心池超出上限：16 > 15/)
    expect(screen.getByRole('checkbox', { name: '核心池 MU' })).toBeTruthy()
  })
  it('invalid identity rows have no core or sector controls', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows: usRows } as any)
    render(Watchlist)
    await screen.findByText('600519.SH')
    expect(screen.queryByRole('checkbox', { name: /核心池 600519/ })).toBeNull()
    expect(screen.queryByRole('combobox', { name: /行业 ETF 600519/ })).toBeNull()
  })
})
