import { describe, it, expect, beforeAll, vi } from 'vitest'
import { fmtBeijing, weekdayText } from './format'

beforeAll(() => {
  // 尽量把测试环境固定在非北京时区，验证 fmtBeijing 不跟浏览器时区走
  vi.stubEnv('TZ', 'America/New_York')
})

describe('fmtBeijing', () => {
  it('fmtBeijing ignores the browser time zone', () => {
    expect(fmtBeijing('2026-10-26T22:30:00Z')).toBe('2026-10-27 06:30:00 北京')
    expect(fmtBeijing('2026-11-03T01:30:00Z')).toBe('2026-11-03 09:30:00 北京') // 美东冬令时之后
    expect(fmtBeijing(null)).toBe('—')
  })

  it('returns the raw value when it cannot be parsed', () => {
    expect(fmtBeijing('not-a-date')).toBe('not-a-date')
    expect(fmtBeijing('')).toBe('—')
  })
})

describe('weekdayText', () => {
  it('maps the common masks', () => {
    expect(weekdayText('1-5')).toBe('周一至周五')
    expect(weekdayText('1-7')).toBe('每天')
    expect(weekdayText('2-6')).toBe('周二至周六')
  })

  it('expands other masks one day at a time', () => {
    expect(weekdayText('1,3,5')).toBe('周一、周三、周五')
  })
})
