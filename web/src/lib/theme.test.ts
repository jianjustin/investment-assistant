import { describe, it, expect, beforeEach } from 'vitest'
import { getTheme, toggleTheme, applyTheme } from './theme'

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute('data-theme') })

describe('theme', () => {
  it('defaults to light', () => { applyTheme(); expect(getTheme()).toBe('light') })
  it('toggles and persists', () => {
    applyTheme(); toggleTheme()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')
  })
})
