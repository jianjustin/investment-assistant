import { it,expect,vi } from 'vitest'
import { registerNavigationGuard, guardHashNavigation, confirmResearchNavigation } from './navigation-guard'
it('restores a cancelled page hash and confirms only once per event',()=>{
  history.replaceState(null,'','#strategy/observation?market=US&symbol=MU')
  const guard=vi.fn(()=>false); const dispose=registerNavigationGuard(guard)
  history.replaceState(null,'','#data/us-research?market=US&symbol=RKLB')
  const event=new HashChangeEvent('hashchange')
  expect(guardHashNavigation(event,'#strategy/observation?market=US&symbol=MU')).toBe(false)
  expect(window.location.hash).toContain('symbol=MU')
  expect(guardHashNavigation(event,'#strategy/observation?market=US&symbol=MU')).toBe(false)
  expect(guard).toHaveBeenCalledTimes(1)
  dispose()
})


it('asks once for two dirty editors and commits neither snapshot on cancellation',()=>{
  const first=vi.fn(),second=vi.fn()
  const a=registerNavigationGuard({snapshot:()=> 'card',dirty:()=>true,discard:first})
  const b=registerNavigationGuard({snapshot:()=> 'guidance',dirty:()=>true,discard:second})
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
  expect(confirmResearchNavigation()).toBe(false)
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(first).not.toHaveBeenCalled();expect(second).not.toHaveBeenCalled()
  confirm.mockReturnValueOnce(true).mockReturnValue(false)
  expect(confirmResearchNavigation()).toBe(true)
  expect(confirm).toHaveBeenCalledTimes(2)
  expect(first).toHaveBeenCalledWith('card');expect(second).toHaveBeenCalledWith('guidance')
  a();b();confirm.mockRestore()
})
