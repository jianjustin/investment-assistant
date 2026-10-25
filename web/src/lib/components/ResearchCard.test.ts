import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import ResearchCard from './ResearchCard.svelte'
import GuidanceEditor from './GuidanceEditor.svelte'
import * as api from '../api'

const body = (text = 'original') => ({ improvement:{hypothesis:text,products:'',expected_window:'',next_event:'',next_event_date:null},evidence:[],scenarios:[],invalidations:[],links:[] })
const card = (text = 'original', version = 1) => ({body:body(text), version})
const props = () => ({symbol:'MU',card:card(),onSaved:async()=>{}})
const pending = () => { let resolve:(value:any)=>void = ()=>{}; const promise = new Promise<any>(r=>resolve=r); return {promise,resolve} }

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api,'get').mockResolvedValue({rows:[]})
  vi.spyOn(api,'getWatchlist').mockResolvedValue({rows:[{ticker:'RKLB',status:'active'},{ticker:'SNDK',status:'active'}]})
})

describe('research card editing', () => {
  it('uses empty currency-aware scenarios and arbitrary ticker links',async()=>{
    render(ResearchCard,props())
    await fireEvent.click(screen.getByRole('button',{name:'添加情景'}))
    expect((screen.getByLabelText('年度利润') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('币种') as HTMLSelectElement).value).toBe('USD')
    await fireEvent.click(screen.getByRole('button',{name:'关联美股研究'}))
    await fireEvent.input(screen.getByLabelText('美股公司'),{target:{value:'RKLB'}})
    expect((screen.getByLabelText('美股公司') as HTMLInputElement).value).toBe('RKLB')
  })
  it('keeps edits on failed save and same-security refresh',async()=>{
    vi.spyOn(api,'put').mockRejectedValue(new Error('HTTP 409'))
    const {rerender}=render(ResearchCard,props())
    await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'my unsaved thesis'}})
    await rerender({...props(),card:card('remote edit',2)})
    expect((screen.getByLabelText('投资假设') as HTMLTextAreaElement).value).toBe('my unsaved thesis')
    await fireEvent.click(screen.getByRole('button',{name:'保存观察卡'}))
    await screen.findByText(/HTTP 409/)
    expect((screen.getByLabelText('投资假设') as HTMLTextAreaElement).value).toBe('my unsaved thesis')
  })
  it('adopts the authoritative saved card and version',async()=>{
    vi.spyOn(api,'put').mockResolvedValue({card:card('normalized server text',2)})
    render(ResearchCard,props())
    await fireEvent.click(screen.getByRole('button',{name:'保存观察卡'}))
    await waitFor(()=>expect((screen.getByLabelText('投资假设') as HTMLTextAreaElement).value).toBe('normalized server text'))
    expect(screen.getByText(/版本 2/)).toBeTruthy()
  })
  it('keeps the body when a post-save readback fails',async()=>{
    vi.spyOn(api,'put').mockResolvedValue({})
    render(ResearchCard,{...props(),onSaved:async()=>{throw new Error('readback failed')}})
    await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'recover this'}})
    await fireEvent.click(screen.getByRole('button',{name:'保存观察卡'}))
    await screen.findByText(/回读|readback/)
    expect((screen.getByLabelText('投资假设') as HTMLTextAreaElement).value).toBe('recover this')
  })
  it('ignores old save responses after A to B to A',async()=>{
    const old=pending(); vi.spyOn(api,'put').mockReturnValueOnce(old.promise)
    const {rerender}=render(ResearchCard,props())
    await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'old submitted'}})
    await fireEvent.click(screen.getByRole('button',{name:'保存观察卡'}))
    await rerender({...props(),symbol:'RKLB',card:card('rocket')})
    await rerender({...props(),card:card('new MU')})
    await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'new MU edits'}})
    await act(async()=>old.resolve({card:card('old submitted',2)}))
    expect((screen.getByLabelText('投资假设') as HTMLTextAreaElement).value).toBe('new MU edits')
    expect(screen.queryByText(/观察卡已保存/)).toBeNull()
  })
  it('keeps edits typed while save is pending',async()=>{
    const write=pending(); vi.spyOn(api,'put').mockReturnValueOnce(write.promise)
    render(ResearchCard,props())
    await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'submitted'}})
    await fireEvent.click(screen.getByRole('button',{name:'保存观察卡'}))
    await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'typed later'}})
    await act(async()=>write.resolve({card:card('submitted',2)}))
    expect((screen.getByLabelText('投资假设') as HTMLTextAreaElement).value).toBe('typed later')
  })
})

it('accepts an explicitly confirmed same-security refresh',async()=>{
  const {rerender}=render(ResearchCard,props())
  await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'discard after confirmation'}})
  vi.spyOn(window,'confirm').mockReturnValue(true)
  const {confirmResearchNavigation}=await import('../navigation-guard')
  expect(confirmResearchNavigation()).toBe(true)
  await rerender({...props(),card:card('fresh server card',2)})
  expect((screen.getByLabelText('投资假设') as HTMLTextAreaElement).value).toBe('fresh server card')
})


it('cancel with two editors never authorizes a later independent read to discard either draft',async()=>{
  const mounted=render(ResearchCard,props())
  const guidance=render(GuidanceEditor,{symbol:'MU',records:[]})
  await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'keep card'}})
  await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'17'}})
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
  const {confirmResearchNavigation}=await import('../navigation-guard')
  expect(confirmResearchNavigation()).toBe(false)
  expect(confirm).toHaveBeenCalledTimes(1)
  await mounted.rerender({...props(),card:card('remote read',2)})
  await guidance.rerender({symbol:'MU',records:[]})
  expect(screen.getByLabelText('投资假设')).toHaveValue('keep card')
  expect(screen.getByLabelText('指引下限')).toHaveValue(17)
})
