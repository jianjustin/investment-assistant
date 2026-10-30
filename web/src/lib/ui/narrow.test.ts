import { describe, it, expect, vi, afterEach } from 'vitest'
import { NARROW_QUERY, useNarrow } from './narrow.svelte'

afterEach(() => vi.unstubAllGlobals())

describe('useNarrow', () => {
  it('uses the 767px query', () => {
    expect(NARROW_QUERY).toBe('(max-width: 767px)')
  })

  it('false without matchMedia', () => {
    vi.stubGlobal('matchMedia', undefined)
    expect(useNarrow().current).toBe(false)
  })

  it('false when matchMedia throws', () => {
    vi.stubGlobal('matchMedia', () => { throw new Error('boom') })
    expect(useNarrow().current).toBe(false)
  })

  it('follows media query changes', () => {
    const listeners = new Set<() => void>()
    const mql = {
      matches: false,
      addEventListener: (_: string, fn: () => void) => listeners.add(fn),
      removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
    }
    const matchMedia = vi.fn(() => mql)
    vi.stubGlobal('matchMedia', matchMedia)
    const narrow = useNarrow()
    expect(matchMedia).toHaveBeenCalledWith(NARROW_QUERY)
    expect(narrow.current).toBe(false)
    mql.matches = true
    listeners.forEach((fn) => fn())
    expect(narrow.current).toBe(true)
  })
})
