import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, act } from '@testing-library/svelte'
import { Toaster } from './sonner/index'
import { notify } from './toast'

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }))
  vi.useFakeTimers()
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })

describe('notify', () => {
  it('success auto-dismisses after 3s, error stays', async () => {
    render(Toaster)
    await act(() => { notify.success('已保存'); notify.error('保存失败：网络中断'); notify.info('已提交批处理') })
    expect(await screen.findByText('已保存')).toBeInTheDocument()
    expect(screen.getByText('保存失败：网络中断')).toBeInTheDocument()
    expect(screen.getByText('已提交批处理')).toBeInTheDocument()

    await act(() => { vi.advanceTimersByTime(2500) })
    expect(screen.getByText('已保存')).toBeInTheDocument()

    await act(() => { vi.advanceTimersByTime(1500) })
    await act(() => { vi.advanceTimersByTime(1000) })
    expect(screen.queryByText('已保存')).toBeNull()
    expect(screen.queryByText('已提交批处理')).toBeNull()
    expect(screen.getByText('保存失败：网络中断')).toBeInTheDocument()

    await act(() => { vi.advanceTimersByTime(60_000) })
    expect(screen.getByText('保存失败：网络中断')).toBeInTheDocument()
  })
})
