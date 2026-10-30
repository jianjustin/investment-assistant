import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { getTheme, toggleTheme, applyTheme, onThemeChange } from './theme'

type Listener = (e: { matches: boolean }) => void

function stubSystem(initialDark: boolean) {
  const listeners = new Set<Listener>()
  const mql = {
    matches: initialDark,
    addEventListener: (_: string, fn: Listener) => listeners.add(fn),
    removeEventListener: (_: string, fn: Listener) => listeners.delete(fn),
  }
  vi.stubGlobal('matchMedia', vi.fn(() => mql))
  return {
    listeners,
    set(dark: boolean) { mql.matches = dark; listeners.forEach((fn) => fn({ matches: dark })) },
  }
}

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute('data-theme') })
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('theme', () => {
  it('defaults to light when the system gives no preference', () => { applyTheme(); expect(getTheme()).toBe('light') })

  it('follows system dark when nothing saved', () => {
    stubSystem(true)
    applyTheme()
    expect(getTheme()).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('keeps following the system until the user toggles', () => {
    const sys = stubSystem(false)
    applyTheme()
    expect(getTheme()).toBe('light')
    sys.set(true)
    expect(getTheme()).toBe('dark')
    toggleTheme()
    expect(getTheme()).toBe('light')
    sys.set(true)
    expect(getTheme()).toBe('light')
    expect(sys.listeners.size).toBe(0)
  })

  it('saved value wins over system', () => {
    stubSystem(true)
    localStorage.setItem('theme', 'light')
    applyTheme()
    expect(getTheme()).toBe('light')
  })

  it('toggles and persists', () => {
    applyTheme(); toggleTheme()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')
    toggleTheme()
    expect(localStorage.getItem('theme')).toBe('light')
  })

  it('localStorage throwing falls back to system', () => {
    stubSystem(true)
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    expect(() => applyTheme()).not.toThrow()
    expect(getTheme()).toBe('dark')
    expect(() => toggleTheme()).not.toThrow()
    expect(getTheme()).toBe('light')
  })

  it('onThemeChange fires on data-theme change and can be unsubscribed', async () => {
    const seen: string[] = []
    const off = onThemeChange((t) => seen.push(t))
    document.documentElement.setAttribute('data-theme', 'dark')
    await vi.waitFor(() => expect(seen).toEqual(['dark']))
    off()
    document.documentElement.setAttribute('data-theme', 'light')
    await new Promise((r) => setTimeout(r, 10))
    expect(seen).toEqual(['dark'])
  })
})
