import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/svelte'
import CutoffTime from './CutoffTime.svelte'
import { fmtBeijing } from '$lib/format'

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-30T12:00:00Z')) })
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('CutoffTime', () => {
  it('formats with fmtBeijing', () => {
    const at = '2026-10-30T09:00:00Z'
    const { container } = render(CutoffTime, { at })
    expect(container.textContent?.trim()).toBe(`截止 ${fmtBeijing(at)}`)
    expect(container.textContent).toContain('北京')
  })

  it('relative time is the tooltip, absolute time the text', () => {
    render(CutoffTime, { at: '2026-10-30T09:00:00Z' })
    expect(screen.getByText(/截止 2026-10-30 17:00:00 北京/)).toHaveAttribute('title', '3 小时前')
  })

  it('relative units', () => {
    const rel = (at: string) => {
      const { container, unmount } = render(CutoffTime, { at })
      const title = container.querySelector('time')!.getAttribute('title')
      unmount()
      return title
    }
    expect(rel('2026-10-30T11:59:40Z')).toBe('刚刚')
    expect(rel('2026-10-30T11:15:00Z')).toBe('45 分钟前')
    expect(rel('2026-10-28T12:00:00Z')).toBe('2 天前')
    expect(rel('2026-10-30T14:00:00Z')).toBe('2 小时后')
  })

  it('custom label', () => {
    const { container } = render(CutoffTime, { at: '2026-10-30T09:00:00Z', label: '数据时点' })
    expect(container.textContent).toContain('数据时点 2026-10-30 17:00:00 北京')
  })

  it('null shows 没算', () => {
    for (const at of [null, undefined, '']) {
      const { container, unmount } = render(CutoffTime, { at })
      expect(screen.getByText('没算')).toBeInTheDocument()
      expect(container.textContent).not.toContain('—')
      unmount()
    }
  })

  it('an unparseable value is shown as it is, without a tooltip', () => {
    const { container } = render(CutoffTime, { at: 'sometime' })
    expect(container.textContent).toContain('sometime')
    expect(container.querySelector('time')).not.toHaveAttribute('title')
  })
})
