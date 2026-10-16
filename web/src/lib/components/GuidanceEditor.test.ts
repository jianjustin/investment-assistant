import { it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/svelte'
async function editor(){const path='./GuidanceEditor.svelte';const loaded=await import(path).catch(()=>null);expect(loaded,'Missing guidance editor').not.toBeNull();return loaded.default}
afterEach(()=>vi.unstubAllGlobals())
const original={id:9,metric:'revenue',target_start:'2026-04-01',target_end:'2026-06-30',basis:'us-gaap:consolidated',unit:'USD',low:90,high:110,issued_at:'2026-03-10T00:00:00Z',source_url:'https://example.com/outlook',source_locator:'table 2',note:''}
it('requires explicit period and accounting basis instead of assuming the next quarter',async()=>{
 render(await editor(),{symbol:'MU',records:[],comparisons:[]})
 expect(screen.getByLabelText('目标期间开始')).toHaveValue('')
 expect(screen.getByLabelText('会计口径')).toHaveValue('')
 expect(screen.getByRole('option',{name:'美国会计准则 · 合并口径'})).toBeInTheDocument()
 await fireEvent.click(screen.getByRole('button',{name:'追加指引版本'}))
 expect(await screen.findByRole('alert')).toHaveTextContent('请完整填写')
})
it('appends a revision without replacing the original range or inventing consensus',async()=>{
 const sent:any[]=[]
 vi.stubGlobal('fetch',vi.fn(async(_url,init)=>{sent.push(JSON.parse(init.body));return new Response(JSON.stringify({record:{...original,...sent[0],id:10}}),{status:200})}))
 render(await editor(),{symbol:'MU',records:[original],comparisons:[{guidance_id:9,status:'not_comparable',actual:null,reason:'Exact target period actual unavailable'}]})
 expect(screen.getByText('未接入一致预期')).toBeInTheDocument()
 expect(screen.getByText(/区间中点 100 USD/)).toBeInTheDocument()
 expect(screen.getByText('目标期间没有可比实际值')).toBeInTheDocument()
 await fireEvent.click(screen.getByRole('button',{name:'修订此版本'}))
 await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'95'}})
 await fireEvent.click(screen.getByRole('button',{name:'追加指引版本'}))
 await screen.findByText('指引版本已追加，原始记录保留。')
 expect(sent[0]).toMatchObject({supersedes_id:9,low:95,high:110,target_start:'2026-04-01',basis:'us-gaap:consolidated'})
 expect(screen.getByRole('heading',{name:/原始指引/})).toBeInTheDocument()
 expect(screen.getByRole('heading',{name:/修订指引/})).toBeInTheDocument()
})

it('rejects a late guidance save after leaving and returning to the same security',async()=>{
 let finish:(value:any)=>void=()=>{}
 vi.stubGlobal('fetch',vi.fn(()=>new Promise(resolve=>{finish=resolve})))
 const Editor=await editor()
 const mounted=render(Editor,{symbol:'MU',records:[original],comparisons:[]})
 await fireEvent.click(screen.getByRole('button',{name:'修订此版本'}))
 await fireEvent.click(screen.getByRole('button',{name:'追加指引版本'}))
 await waitFor(()=>expect(fetch).toHaveBeenCalled())
 await mounted.rerender({symbol:'NVDA',records:[],comparisons:[]})
 await mounted.rerender({symbol:'MU',records:[],comparisons:[]})
 await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'111'}})
 await act(async()=>finish(new Response(JSON.stringify({record:{...original,id:10,supersedes_id:9}}),{status:200})))
 expect(screen.getByLabelText('指引下限')).toHaveValue(111)
 expect(screen.queryByText('指引版本已追加，原始记录保留。')).toBeNull()
 expect(screen.queryByRole('heading',{name:/修订指引/})).toBeNull()
})


it('protects unsaved guidance on unload and clears dirty only for the submitted draft',async()=>{
 const {confirmResearchNavigation}=await import('../navigation-guard')
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 let finish:(value:any)=>void=()=>{}
 vi.stubGlobal('fetch',vi.fn(()=>new Promise(resolve=>finish=resolve)))
 render(await editor(),{symbol:'MU',records:[original],comparisons:[]})
 await fireEvent.click(screen.getByRole('button',{name:'修订此版本'}))
 const unload=new Event('beforeunload',{cancelable:true});window.dispatchEvent(unload)
 expect(unload.defaultPrevented).toBe(true)
 expect(confirmResearchNavigation()).toBe(false)
 await fireEvent.click(screen.getByRole('button',{name:'追加指引版本'}))
 await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'99'}})
 await act(async()=>finish(new Response(JSON.stringify({record:{...original,id:10,supersedes_id:9}}),{status:200})))
 await screen.findByText('指引版本已追加，原始记录保留。')
 expect(screen.getByLabelText('指引下限')).toHaveValue(99)
 expect(confirmResearchNavigation()).toBe(false)
 await fireEvent.click(screen.getByRole('button',{name:'追加指引版本'}))
 await act(async()=>finish(new Response(JSON.stringify({record:{...original,id:11,low:99,supersedes_id:9}}),{status:200})))
 await waitFor(()=>expect(screen.getByLabelText('指引下限')).toHaveValue(null))
 expect(confirmResearchNavigation()).toBe(true)
 const cleanUnload=new Event('beforeunload',{cancelable:true});window.dispatchEvent(cleanUnload)
 expect(cleanUnload.defaultPrevented).toBe(false)
 confirm.mockRestore()
})
