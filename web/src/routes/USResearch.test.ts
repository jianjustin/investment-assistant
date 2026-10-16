import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/svelte'
import Data from './Data.svelte'
import Strategy from './Strategy.svelte'
import Tools from './Tools.svelte'
import App from '../app.svelte'
const source = 'https://www.sec.gov/Archives/example'
const metric = (value: number | null, unit = 'USD') => ({ value, unit, basis:'us-gaap:consolidated', method:'reported', input_ids:[42], sources:[{source_url:source,start:'2026-04-01',end:'2026-06-30',filed:'2026-08-01',concept:'Revenues',source_locator:'/facts/1'}], missing_reason:value === null ? 'Missing compatible calculation input' : null })
const view = (ticker = 'MU') => ({ ticker,security_id:`US:stock:${ticker}`,currency:'USD',financials:[{period:'2026-04-01/2026-06-30',start:'2026-04-01',end:'2026-06-30',days:91,metrics:{revenue:metric(100),cfo:metric(0),fcf:metric(null)},ttm:{},warnings:[]}],market:{bars:[],benchmarks:{SPY:[],QQQ:[]},quote:{market_cap_verified:false},performance:{windows:{}},limitations:[]},valuation:{ps_ttm:metric(null,'multiple')},statuses:[{dataset:'financials',status:'failed',retained_old_values:true,succeeded_at:'2026-08-01',attempted_at:'2026-10-16',error:'来源失败',last_success_details:{identity:{name:'测试公司'}}}],template:[{question:'需求是否兑现？',value:null,status:'needs_evidence'}],card:null,guidance:{records:[],comparisons:[],consensus:'未接入一致预期'},filings:[],pit:{strict:false} })
let drawn:string[]=[]
let respond: (url:string, init?:RequestInit)=>Promise<any>
const json = (body:any) => new Response(JSON.stringify(body), {status:200,headers:{'Content-Type':'application/json'}})
beforeEach(()=>{
 vi.restoreAllMocks()
 drawn=[]
 const context=new Proxy({fillText:(text:string)=>{drawn.push(String(text))},measureText:(text:string)=>({width:text.length*7}),createLinearGradient:()=>({addColorStop(){}})}, {get:(target:any,key)=>key in target?target[key]:()=>{}})
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(context as any)
 vi.spyOn(HTMLElement.prototype,'clientWidth','get').mockReturnValue(800)
 vi.spyOn(HTMLElement.prototype,'clientHeight','get').mockReturnValue(320)
 history.replaceState(null,'','#data/us-research?market=US&symbol=MU')
 respond = async(url)=>url.includes('/api/watchlist?market=CN')?json({rows:[]}):url.startsWith('/api/watchlist') ? json({rows:[{ticker:'MU',status:'active'},{ticker:'NVDA',status:'active'}]}) : url.includes('/api/us-research/') ? json(view(url.split('/')[3].split('?')[0])) : json({rows:[],records:[],tickers:[]})
 vi.stubGlobal('fetch',vi.fn((url,init)=>respond(String(url),init)))
})
afterEach(()=>vi.unstubAllGlobals())
it('loads the explicit US selection and distinguishes a real zero from a missing cash flow',async()=>{
 render(Data,{sub:'us-research'})
 await screen.findByRole('heading',{name:/MU/})
 expect(await screen.findByText('未接入一致预期')).toBeInTheDocument()
 expect(screen.getByText('显示旧值')).toBeInTheDocument()
 expect(screen.getAllByText('缺少可比计算输入').length).toBeGreaterThan(0)
 expect(screen.getByRole('row',{name:/经营现金流/})).toHaveTextContent('0 USD')
 expect(screen.getByRole('row',{name:/标准自由现金流/})).toHaveTextContent('—')
 expect(screen.getByRole('link',{name:'打开研究观察卡 →'})).toHaveAttribute('href','#strategy/observation?market=US&symbol=MU')
 await fireEvent.click(screen.getAllByText('计算与来源')[0])
 expect(screen.getAllByRole('link',{name:/原文/})[0]).toHaveAttribute('href',source)
 expect(screen.getAllByText(/2026-04-01.*2026-06-30/).length).toBeGreaterThan(0)
})
it('loads an explicit identity when watchlist reading fails, and never invents an empty-list default',async()=>{
 respond = async(url)=>url.includes('/api/watchlist?market=CN')?json({rows:[]}):url.startsWith('/api/watchlist') ? Promise.reject(new Error('offline')) : json(view())
 const mounted=render(Data,{sub:'us-research'})
 await screen.findByText('未接入一致预期')
 expect(await screen.findByRole('alert')).toHaveTextContent('读取关注列表失败')
 mounted.unmount()
 history.replaceState(null,'','#data/us-research')
 respond=async()=>json({rows:[]})
 render(Data,{sub:'us-research'})
 await screen.findByText('暂无美股关注证券，请先在关注列表添加。')
 expect(screen.queryByRole('heading',{name:/MU/})).toBeNull()
})
it('rejects a late A response after A to B to A selection',async()=>{
 let finish:(value:any)=>void=()=>{}
 let calls=0
 respond=async(url)=>{
  if(url.startsWith('/api/watchlist'))return json({rows:[{ticker:'MU',status:'active'},{ticker:'NVDA',status:'active'}]})
  if(url.startsWith('/api/us-research/MU') && ++calls===1)return new Promise(resolve=>{finish=resolve})
  return json({...view(url.includes('NVDA')?'NVDA':'MU'),currency:'EUR'})
 }
 render(Data,{sub:'us-research'})
 await screen.findByText('NVDA')
 const picker=screen.getByLabelText('关注证券')
 await fireEvent.change(picker,{target:{value:'NVDA'}})
 await screen.findByRole('heading',{name:/NVDA/})
 await fireEvent.change(picker,{target:{value:'MU'}})
 await screen.findByText(/币种 EUR/)
 await act(async()=>finish(json({...view(),currency:'STALE'})))
 expect(screen.queryByText(/币种 STALE/)).toBeNull()
})
it('reports nested partial failures and reloads retained data after manual refresh',async()=>{
 respond=async(url,init)=>url.startsWith('/api/watchlist') ? json({rows:[{ticker:'MU',status:'active'}]}) : init?.method==='POST' ? json({run_id:'outer',status:'pending'}) : url==='/api/runs/outer' ? json({status:'done',run_id:'outer',result:{status:'error',summary:{errors:[{dataset:'financials'}],results:[]}}}) : json(view())
 render(Data,{sub:'us-research'})
 await screen.findByText('未接入一致预期')
 await fireEvent.click(screen.getByRole('button',{name:'手动更新'}))
 await screen.findByText(/更新有缺失或失败/)
 expect(screen.queryByText('全部更新成功')).toBeNull()
 expect(screen.getByRole('link',{name:'查看持久运行报告'})).toHaveAttribute('href','#tools/runs')
})

it('uses any future ticker deep link without requiring the stock to be on the watchlist',async()=>{
 history.replaceState(null,'','#data/us-research?market=US&symbol=BRK.B')
 render(Data,{sub:'us-research'})
 await screen.findByText('未接入一致预期')
 expect(screen.getByRole('heading',{name:/BRK.B/})).toBeInTheDocument()
 expect(screen.getByRole('link',{name:'打开研究观察卡 →'})).toHaveAttribute('href','#strategy/observation?market=US&symbol=BRK.B')
})
it('cancels stock and market changes without changing URL or dirty card text, and retains it across a guidance-save reload',async()=>{
 history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
 const original={id:9,metric:'revenue',target_start:'2026-04-01',target_end:'2026-06-30',basis:'us-gaap:consolidated',unit:'USD',low:90,high:110,issued_at:'2026-03-10T00:00:00Z',source_url:'https://example.com/outlook',source_locator:'table 2',note:''}
 respond=async(url,init)=>url.startsWith('/api/watchlist')?json({rows:[{ticker:'MU',status:'active'},{ticker:'NVDA',status:'active'}]}):init?.method==='POST'?json({record:{...original,id:10,supersedes_id:9}}):url.includes('us-references')?json({rows:[]}):json({...view(),guidance:{records:[original],comparisons:[],consensus:'未接入一致预期'}})
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 render(Strategy,{sub:'observation'})
 await screen.findByLabelText('投资假设')
 await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'keep my draft'}})
 await fireEvent.change(screen.getByLabelText('关注证券'),{target:{value:'NVDA'}})
 expect(screen.getByLabelText('关注证券')).toHaveValue('MU')
 expect(location.hash).toContain('symbol=MU')
 expect(confirm).toHaveBeenCalledTimes(1)
 await fireEvent.click(screen.getByRole('button',{name:'A 股'}))
 expect(confirm).toHaveBeenCalledTimes(2)
 expect(location.hash).toContain('market=US&symbol=MU')
 await fireEvent.click(screen.getByRole('button',{name:'修订此版本'}))
 await fireEvent.click(screen.getByRole('button',{name:'追加指引版本'}))
 await screen.findByText('指引版本已追加，原始记录保留。')
 expect(screen.getByLabelText('投资假设')).toHaveValue('keep my draft')
 expect(confirm).toHaveBeenCalledTimes(2)
})
it('allows a confirmed refresh but preserves any new text typed during its pending response',async()=>{
 history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
 let finish:(v:any)=>void=()=>{}
 let loads=0
 respond=async(url)=>url.startsWith('/api/watchlist')?json({rows:[{ticker:'MU',status:'active'}]}):url.includes('us-references')?json({rows:[]}):++loads===1?json(view()):new Promise(resolve=>{finish=resolve})
 vi.spyOn(window,'confirm').mockReturnValue(true)
 render(Strategy,{sub:'observation'})
 await screen.findByLabelText('投资假设')
 await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'first draft'}})
 await fireEvent.click(screen.getByRole('button',{name:'读取本地数据'}))
 await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'new draft during read'}})
 await act(async()=>finish(json(view())))
 expect(screen.getByLabelText('投资假设')).toHaveValue('new draft during read')
})
it('does not present an old completed refresh after leaving and returning to the same ticker',async()=>{
 let finish:(v:any)=>void=()=>{}
 respond=async(url,init)=>url.startsWith('/api/watchlist')?json({rows:[{ticker:'MU',status:'active'},{ticker:'NVDA',status:'active'}]}):init?.method==='POST'?json({run_id:'old',status:'pending'}):url==='/api/runs/old'?new Promise(resolve=>{finish=resolve}):json(view(url.includes('NVDA')?'NVDA':'MU'))
 render(Data,{sub:'us-research'})
 await screen.findByText('未接入一致预期')
 await fireEvent.click(screen.getByRole('button',{name:'手动更新'}))
 await waitFor(()=>expect(fetch).toHaveBeenCalledWith('/api/runs/old',expect.anything()))
 await fireEvent.change(screen.getByLabelText('关注证券'),{target:{value:'NVDA'}})
 await screen.findByText('未接入一致预期')
 await fireEvent.change(screen.getByLabelText('关注证券'),{target:{value:'MU'}})
 await screen.findByText('未接入一致预期')
 await act(async()=>finish(json({status:'done',run_id:'old',result:{status:'success',summary:{errors:[],results:[]}}})))
 expect(screen.queryByText(/手动更新完成/)).toBeNull()
})
it('keeps ordinary signal and score pages usable after returning from research',async()=>{
 const mounted=render(Data,{sub:'us-research'})
 await screen.findByText('未接入一致预期')
 await mounted.rerender({sub:'signals'})
 expect(await screen.findByText('近 30 天状态演变')).toBeInTheDocument()
 mounted.unmount()
 const strategy=render(Strategy,{sub:'observation'})
 await screen.findByText('未接入一致预期')
 await strategy.rerender({sub:'scores'})
 expect(await screen.findByText('暂无数据')).toBeInTheDocument()
})
it('shows a Chinese name and filter for persisted US research reports',async()=>{
 respond=async(url)=>url.startsWith('/api/jobs/scheduled')?json({jobs:[],degraded:false}):json({reports:[{run_id:'persisted',task:'us-research',status:'error',summary:{errors:[{dataset:'financials'}]}}],degraded:false})
 render(Tools,{sub:'runs'})
 expect(await screen.findByRole('cell',{name:'美股研究'})).toBeInTheDocument()
 expect(screen.getByRole('option',{name:'美股研究'})).toHaveValue('us-research')
})

it('enters an explicit US observation link from an already mounted score page',async()=>{
 vi.stubGlobal('EventSource',class{addEventListener(){}close(){}})
 history.replaceState(null,'','#strategy/scores')
 render(App)
 await screen.findByText('暂无数据')
 location.hash='#strategy/observation?market=US&symbol=NVDA'
 window.dispatchEvent(new HashChangeEvent('hashchange'))
 await screen.findByText('未接入一致预期')
 expect(screen.getByRole('heading',{name:/NVDA/})).toBeInTheDocument()
 expect(location.hash).toContain('market=US&symbol=NVDA')
 expect((fetch as any).mock.calls.some(([url]:[string])=>url.includes('/api/watchlist?market=CN'))).toBe(false)
})
it('displays the twelve latest actual quarters, percentages and a recent-year price window',async()=>{
 const payload=view()
 payload.financials=[['2023-06-01','2023-08-31'],['2023-09-01','2023-11-30'],['2023-12-01','2024-02-29'],['2024-03-01','2024-05-31'],['2024-06-01','2024-08-31'],['2024-09-01','2024-11-30'],['2024-12-01','2025-02-28'],['2025-03-01','2025-05-31'],['2025-06-01','2025-08-31'],['2025-09-01','2025-11-30'],['2025-12-01','2026-02-28'],['2026-03-01','2026-05-31'],['2026-06-01','2026-08-31']].map(([start,end])=>({period:`${start}/${end}`,start,end,days:92,metrics:{revenue:metric(100),gross_margin:metric(0.25,'ratio'),cfo:metric(0),fcf:metric(null)},ttm:{revenue:metric(380)},warnings:[]}))
 payload.market.bars=[{date:'2024-10-15',close:999,adjusted_close:999,currency:'USD'},{date:'2025-10-16',close:15,adjusted_close:14,currency:'USD'},{date:'2026-10-15',close:20,adjusted_close:19,currency:'USD'}] as any
 respond=async(url)=>url.startsWith('/api/watchlist')?json({rows:[]}):json(payload)
 render(Data,{sub:'us-research'})
 await screen.findByText('未接入一致预期')
 expect(screen.getByText(/最近 12 个实际财季/)).toBeInTheDocument()
 expect(screen.queryByText('2023-08-31')).toBeNull()
 expect(screen.getAllByText('25%').length).toBe(12)
 await fireEvent.change(screen.getByLabelText('财务期间口径'),{target:{value:'ttm'}})
 expect(screen.getAllByText('380 USD').length).toBe(12)
 await fireEvent.click(screen.getByText('价格原始记录与报价来源'))
 expect(screen.queryByRole('row',{name:/2024-10-15/})).toBeNull()
 expect(screen.getByRole('row',{name:/2025-10-16/})).toHaveTextContent('15 USD')
})
it('preserves a failed guidance draft and keeps original history separate from comparison',async()=>{
 history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
 respond=async(url,init)=>url.startsWith('/api/watchlist')?json({rows:[{ticker:'MU',status:'active'}]}):init?.method==='POST'?new Response('{}',{status:409}):url.includes('us-references')?json({rows:[]}):json(view())
 render(Strategy,{sub:'observation'})
 await screen.findByText('未接入一致预期')
 for(const [name,value] of [['指引指标','revenue'],['目标期间开始','2026-04-01'],['目标期间结束','2026-06-30'],['会计口径','us-gaap:consolidated'],['单位','USD'],['指引下限','0'],['指引上限','100'],['发布时间（本机时区）','2026-03-10T12:00'],['原文链接','https://example.com/outlook'],['原文定位','table 2']]){
  const input=screen.getByLabelText(name)
  if(input.tagName==='SELECT')await fireEvent.change(input,{target:{value}});else await fireEvent.input(input,{target:{value}})
 }
 await fireEvent.click(screen.getByRole('button',{name:'追加指引版本'}))
 expect(await screen.findByRole('alert')).toHaveTextContent('输入已保留')
 expect(screen.getByLabelText('指引下限')).toHaveValue(0)
 expect(screen.getByLabelText('原文定位')).toHaveValue('table 2')
})

it('accepts a company-specific guidance metric with an explicit company basis',async()=>{
 history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
 let submitted:any=null
 respond=async(url,init)=>url.startsWith('/api/watchlist')?json({rows:[{ticker:'MU',status:'active'}]}):init?.method==='POST'?(submitted=JSON.parse(String(init.body)),json({record:{...submitted,id:8}})):url.includes('us-references')?json({rows:[]}):json(view())
 render(Strategy,{sub:'observation'})
 await screen.findByText('未接入一致预期')
 await fireEvent.click(screen.getByText('公司自定义指标与特定口径'))
 for(const [name,value] of [['自定义指引指标','hbm_revenue'],['目标期间开始','2026-04-01'],['目标期间结束','2026-06-30'],['完整会计口径','company:HBM-defined'],['单位','USD'],['指引下限','10'],['指引上限','20'],['发布时间（本机时区）','2026-03-10T12:00'],['原文链接','https://example.com/outlook'],['原文定位','table 2']])await fireEvent.input(screen.getByLabelText(name),{target:{value}})
 await fireEvent.click(screen.getByRole('button',{name:'追加指引版本'}))
 await screen.findByText('指引版本已追加，原始记录保留。')
 expect(submitted).toMatchObject({metric:'hbm_revenue',basis:'company:HBM-defined',low:10,high:20})
})

it.each(['MU','SNDK','CRDO','NVDA','MSFT','GOOG','TSLA','RKLB'])('renders the existing %s security without a fixed company allowlist',async(ticker)=>{
 history.replaceState(null,'','#data/us-research?market=US&symbol='+ticker)
 render(Data,{sub:'us-research'})
 await screen.findByText('未接入一致预期')
 expect(screen.getByRole('heading',{name:new RegExp(ticker)})).toBeInTheDocument()
 expect(screen.getByText('需求是否兑现？')).toBeInTheDocument()
 expect(screen.getByText('尚未保存行业证据。')).toBeInTheDocument()
})
it('does not leak later guidance into a historical observation after a current view was opened',async()=>{
 const record={id:9,metric:'revenue',target_start:'2026-04-01',target_end:'2026-06-30',basis:'us-gaap:consolidated',unit:'USD',low:90,high:110,issued_at:'2026-03-10T00:00:00Z',source_url:'https://example.com/outlook',source_locator:'table 2',note:''}
 respond=async(url)=>url.startsWith('/api/watchlist')?json({rows:[{ticker:'MU',status:'active'}]}):url.includes('as_of=')?json({...view(),pit:{strict:false,as_of:'2025-01-01T00:00:00Z'},guidance:{records:[],comparisons:[],consensus:'未接入一致预期'}}):json({...view(),guidance:{records:[record],comparisons:[],consensus:'未接入一致预期'}})
 render(Data,{sub:'us-research'})
 await screen.findByRole('heading',{name:/原始指引/})
 await fireEvent.click(screen.getByText('本机历史观察'))
 await fireEvent.input(screen.getByLabelText('本机观察截止时间'),{target:{value:'2025-01-01T08:00'}})
 await fireEvent.click(screen.getByRole('button',{name:'按截止时间读取'}))
 await screen.findByText(/历史观察截止 2025-01-01/)
 expect(screen.queryByRole('heading',{name:/原始指引/})).toBeNull()
 expect(screen.queryByRole('button',{name:'追加指引版本'})).toBeNull()
})

it('cancels a US hash navigation once at the app and page boundary, retaining URL, symbol and draft',async()=>{
 vi.stubGlobal('EventSource',class{addEventListener(){}close(){}})
 history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 const initial=respond
 respond=(url,init)=>url.includes('us-references')?Promise.resolve(json({rows:[]})):initial(url,init)
 render(App)
 await screen.findByLabelText('投资假设')
 await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'retain on hash cancel'}})
 const oldURL=location.href
 history.replaceState(null,'','#strategy/observation?market=US&symbol=NVDA')
 window.dispatchEvent(new HashChangeEvent('hashchange',{oldURL,newURL:location.href}))
 await waitFor(()=>expect(location.hash).toContain('symbol=MU'))
 expect(screen.getByLabelText('关注证券')).toHaveValue('MU')
 expect(screen.getByLabelText('投资假设')).toHaveValue('retain on hash cancel')
 expect(confirm).toHaveBeenCalledTimes(1)
})

it('formats financial margin trend axis labels as percentages as well as the table',async()=>{
 const payload=view()
 payload.financials[0].metrics={...payload.financials[0].metrics,gross_margin:metric(0.25,'ratio')} as any
 respond=async(url)=>url.startsWith('/api/watchlist')?json({rows:[]}):json(payload)
 render(Data,{sub:'us-research'})
 await screen.findByText('未接入一致预期')
 await fireEvent.change(screen.getByLabelText('趋势指标'),{target:{value:'gross_margin'}})
 await waitFor(()=>expect(drawn.some(text=>text.endsWith('%'))).toBe(true))
})


it.each(['symbol','market','page','cutoff'])('protects a guidance draft on %s transition',async(path)=>{
 history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
 vi.stubGlobal('EventSource',class{addEventListener(){}close(){}})
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 render(App)
 await screen.findByLabelText('指引下限')
 await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'123'}})
 if(path==='symbol')await fireEvent.change(screen.getByLabelText('关注证券'),{target:{value:'NVDA'}})
 else if(path==='cutoff'){
  await fireEvent.input(screen.getByLabelText('本机观察截止时间'),{target:{value:'2025-01-01T08:00'}})
  await fireEvent.click(screen.getByRole('button',{name:'按截止时间读取'}))
 }else{
  const oldURL=location.href
  history.replaceState(null,'',path==='market'?'#strategy/observation?market=CN&symbol=600519.SH':'#data/us-research?market=US&symbol=MU')
  window.dispatchEvent(new HashChangeEvent('hashchange',{oldURL,newURL:location.href}))
 }
 expect(screen.getByLabelText('指引下限')).toHaveValue(123)
 expect(screen.getByLabelText('关注证券')).toHaveValue('MU')
 expect(location.hash).toBe('#strategy/observation?market=US&symbol=MU')
 expect(confirm).toHaveBeenCalledTimes(1)
})

it('makes one atomic decision for two drafts and cancel cannot pre-authorize a later discard',async()=>{
 history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 render(Strategy,{sub:'observation'})
 await screen.findByLabelText('投资假设')
 await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'card draft'}})
 await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'123'}})
 await fireEvent.click(screen.getByRole('button',{name:'读取本地数据'}))
 expect(confirm).toHaveBeenCalledTimes(1)
 // A later independent read (such as guidance-save reload) must not adopt after cancellation.
 expect(screen.getByLabelText('投资假设')).toHaveValue('card draft')
 expect(screen.getByLabelText('指引下限')).toHaveValue(123)
 const event=new Event('beforeunload',{cancelable:true})
 window.dispatchEvent(event)
 expect(event.defaultPrevented).toBe(true)
 confirm.mockReturnValue(true)
 await fireEvent.click(screen.getByRole('button',{name:'读取本地数据'}))
 await waitFor(()=>expect(screen.getByLabelText('投资假设')).toHaveValue(''))
 expect(screen.getByLabelText('指引下限')).toHaveValue(null)
})

it('preserves newer drafts while an accepted historical read is pending',async()=>{
 history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
 let finish:(v:any)=>void=()=>{}
 const initial=respond
 respond=(url,init)=>url.includes('as_of=')?new Promise(resolve=>finish=resolve):initial(url,init)
 vi.spyOn(window,'confirm').mockReturnValue(true)
 render(Strategy,{sub:'observation'})
 await screen.findByLabelText('投资假设')
 await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'confirmed card'}})
 await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'1'}})
 await fireEvent.input(screen.getByLabelText('本机观察截止时间'),{target:{value:'2025-01-01T08:00'}})
 await fireEvent.click(screen.getByRole('button',{name:'按截止时间读取'}))
 await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'newer card'}})
 await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'2'}})
 await act(async()=>finish(json({...view(),pit:{strict:false,as_of:'2025-01-01T00:00:00Z'}})))
 await waitFor(()=>expect(screen.queryByText('正在读取本地数据…')).toBeNull())
 expect(screen.getByText('读取期间出现新编辑，已保留当前内容；请保存后重新读取历史。')).toBeInTheDocument()
 expect(screen.getByLabelText('投资假设')).toHaveValue('newer card')
 expect(screen.getByLabelText('指引下限')).toHaveValue(2)
 expect(screen.queryByText(/历史观察截止 2025-01-01/)).toBeNull()
})


it('discards only confirmed drafts on a current refresh and preserves edits typed during the read',async()=>{
 history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
 const initial=respond
 let finish:(v:any)=>void=()=>{}
 vi.spyOn(window,'confirm').mockReturnValue(true)
 render(Strategy,{sub:'observation'})
 await screen.findByLabelText('投资假设')
 await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'confirmed card'}})
 await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'1'}})
 respond=(url,init)=>url.includes('/api/us-research/')?new Promise(resolve=>finish=resolve):initial(url,init)
 await fireEvent.click(screen.getByRole('button',{name:'读取本地数据'}))
 await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'new card'}})
 await fireEvent.input(screen.getByLabelText('指引下限'),{target:{value:'2'}})
 await act(async()=>finish(json(view())))
 await waitFor(()=>expect(screen.queryByText('正在读取本地数据…')).toBeNull())
 expect(screen.getByLabelText('投资假设')).toHaveValue('new card')
 expect(screen.getByLabelText('指引下限')).toHaveValue(2)
})
