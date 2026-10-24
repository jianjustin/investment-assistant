import { describe, expect, it } from 'vitest'
import { isCore, sectorOf, withPoolTags } from './pool-tags'

describe('pool tags', () => {
  it('isCore is case-insensitive', () => {
    expect(isCore(['core'])).toBe(true)
    expect(isCore(['Core'])).toBe(true)
    expect(isCore(['CORE'])).toBe(true)
    expect(isCore(['sector:SMH'])).toBe(false)
    expect(isCore([])).toBe(false)
  })
  it('sectorOf normalizes case', () => {
    expect(sectorOf(['sector:smh'])).toBe('SMH')
    expect(sectorOf(['sector:QQQ'])).toBe('QQQ')
    expect(sectorOf(['core'])).toBeNull()
    expect(sectorOf(['sector:XLE'])).toBeNull()
  })
  it('withPoolTags keeps other tags', () => {
    expect(withPoolTags(['memory', 'core'], false, null)).toEqual(['memory'])
    expect(withPoolTags(['memory'], true, null)).toEqual(['memory', 'core'])
  })
  it('withPoolTags replaces sector', () => {
    expect(withPoolTags(['sector:SMH'], false, 'XLK')).toEqual(['sector:XLK'])
    expect(withPoolTags(['sector:SMH', 'core'], true, null)).toEqual(['core'])
    expect(withPoolTags([], false, 'QQQ')).toEqual(['sector:QQQ'])
    expect(withPoolTags(['sector:smh'], false, null)).toEqual([])
  })
})
