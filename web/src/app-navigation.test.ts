import {it,expect,vi,afterEach} from 'vitest'
import {fireEvent,render,screen,waitFor} from '@testing-library/svelte'
import App from './app.svelte'
import * as api from './lib/api'

afterEach(()=>vi.unstubAllGlobals())

it('keeps the active card and edited security when app page navigation is cancelled',async()=>{
  vi.stubGlobal('EventSource',class { addEventListener() {} close() {} })
  history.replaceState(null,'','#strategy/observation?market=CN&symbol=600519.SH')
  vi.spyOn(api,'getWatchlist').mockResolvedValue({rows:[{ticker:'600519.SH',status:'active'}]})
  vi.spyOn(api,'getStrategyScores').mockResolvedValue({rows:[]} as any)
  vi.spyOn(api,'getEventStudyKinds').mockResolvedValue({kinds:[]})
  vi.spyOn(api,'get').mockImplementation(async(path:string)=>path.includes('us-references')?{rows:[]}:{profile:{name:'当前证券'},window:{start:'2026-01-01',end:'2026-10-01'},card:{version:1,body:{improvement:{hypothesis:'original',products:'',expected_window:'',next_event:''},evidence:[],scenarios:[],invalidations:[],links:[]}},financials:[],announcements:[],statuses:[],performance:{},bars:[],raw_bars:[],valuation:null,coverage:{},adjustment:{},comparisons:[],calendar:{},pit:{},upstream:{}})
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
  render(App)
  await screen.findByLabelText('投资假设')
  await fireEvent.input(screen.getByLabelText('投资假设'),{target:{value:'keep app draft'}})
  window.location.hash='#settings/watchlist'
  window.dispatchEvent(new HashChangeEvent('hashchange'))
  await waitFor(()=>expect(window.location.hash).toContain('symbol=600519.SH'))
  expect((screen.getByLabelText('投资假设') as HTMLTextAreaElement).value).toBe('keep app draft')
  expect(confirm).toHaveBeenCalled()
})
