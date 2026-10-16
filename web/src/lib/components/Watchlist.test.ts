import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Watchlist from './Watchlist.svelte'
import SecurityPicker from './SecurityPicker.svelte'
import * as api from '../api'
const rows = [
  { ticker:'MU', market:'US', status:'active', thesis:'cycle', tags:['memory'], updated_at:'2026-10-16T00:00:00Z' },
  { ticker:'600519.SH', market:'CN', name:'贵州茅台', board:'主板', status:'active', thesis:'cashflow', tags:['consumer'], updated_at:'2026-10-16T00:00:00Z' },
]
beforeEach(() => { vi.restoreAllMocks() })
describe('shared watchlist editor', () => {
  it('filters markets and preserves thesis/tags on status changes with server read-back', async () => {
    const get = vi.spyOn(api, 'getWatchlist').mockResolvedValueOnce({ rows } as any).mockResolvedValue({ rows:[rows[0], {...rows[1], status:'paused'}] } as any)
    const save = vi.spyOn(api, 'addWatchlistItem').mockResolvedValue({} as any)
    render(Watchlist)
    await screen.findByText('贵州茅台')
    await fireEvent.click(screen.getByRole('button', { name:'CN' }))
    expect(screen.queryByText('MU')).toBeNull()
    await fireEvent.click(screen.getByRole('button', { name:'暂停' }))
    await waitFor(() => expect(save).toHaveBeenCalledWith({ ticker:'600519.SH', status:'paused', expected_updated_at:'2026-10-16T00:00:00Z' }))
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
    await waitFor(() => expect(save).toHaveBeenCalledWith({ ticker:'600519.SH', status:'active', thesis:'updated thesis', tags:['consumer'], expected_updated_at:'2026-10-16T00:00:00Z' }))
  })
  it('requires explicit candidate selection before saving a six-digit code', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[] } as any)
    vi.spyOn(api, 'get').mockResolvedValue({ candidates:[{ symbol:'600519.SH', name:'贵州茅台' }] })
    const save = vi.spyOn(api, 'addWatchlistItem').mockResolvedValue({} as any)
    render(Watchlist)
    await fireEvent.click(await screen.findByRole('button', { name:'+ 添加' }))
    await fireEvent.input(screen.getByLabelText('证券代码'), { target:{ value:'600519' } })
    await fireEvent.click(screen.getByRole('button', { name:'确认身份' }))
    expect(save).not.toHaveBeenCalled()
    await fireEvent.click(await screen.findByRole('button', { name:'600519.SH 贵州茅台' }))
    await fireEvent.click(screen.getByRole('button', { name:'保存' }))
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ ticker:'600519.SH', tags:[] })))
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
    await fireEvent.input(screen.getByLabelText('证券代码'), { target:{ value:'600519' } })
    await fireEvent.click(screen.getByRole('button', { name:'确认身份' }))
    await fireEvent.input(screen.getByLabelText('证券代码'), { target:{ value:'688008' } })
    finish({ candidates:[{ symbol:'600519.SH', name:'贵州茅台' }] })
    await Promise.resolve()
    expect(screen.queryByRole('button', { name:'600519.SH 贵州茅台' })).toBeNull()
  })
})
describe('security picker', () => {
  it('uses market filtered API and refuses changes when beforeChange returns false', async () => {
    const get = vi.spyOn(api, 'getWatchlist').mockResolvedValue({ rows:[rows[1]] } as any)
    const onchange = vi.fn()
    render(SecurityPicker, { market:'CN', value:'600519.SH', onchange, beforeChange:() => false })
    const select = await screen.findByRole('combobox', { name:'关注证券' })
    await screen.findByText('600519.SH 贵州茅台')
    await fireEvent.change(select, { target:{ value:'600519.SH' } })
    expect(get).toHaveBeenCalledWith('CN', true)
    expect(onchange).not.toHaveBeenCalled()
  })
})

it('shows persisted US coverage and a dated manual verification event in readable Chinese',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({rows:[{...rows[0],name:'Micron',latest_period:'2026-09-03',datasets:{financials:{status:'failed'}},next_event:{date:'2099-01-01',kind:'research_verification',title:'核对下一季毛利'}}]}),{status:200})))
 try{
  render(Watchlist)
  await screen.findByText('Micron')
  expect(screen.getByText('标准财务: 来源失败')).toBeInTheDocument()
  expect(screen.getByText('核对下一季毛利')).toBeInTheDocument()
 }finally{vi.unstubAllGlobals()}
})


it('shows unsupported legacy identities for deletion and omits them from the picker',async()=>{
 const legacy={ticker:'AAPL.US',market:null,status:'active',identity_error:'证券身份无效，请删除后使用完整有效代码重新添加'}
 vi.spyOn(api,'getWatchlist').mockResolvedValue({rows:[rows[0],legacy]} as any)
 const remove=vi.spyOn(api,'deleteWatchlistItem').mockResolvedValue({})
 const mounted=render(Watchlist)
 await screen.findByText('AAPL.US')
 expect(screen.getByText(/证券身份无效/)).toBeInTheDocument()
 await fireEvent.click(screen.getAllByRole('button',{name:'删除'})[1])
 expect(remove).toHaveBeenCalledWith('AAPL.US')
 mounted.unmount()
 render(SecurityPicker,{market:'US',value:'MU',onchange:vi.fn()})
 await screen.findByRole('option',{name:'MU'})
 expect(screen.queryByRole('option',{name:'AAPL.US'})).toBeNull()
})
