import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, waitFor } from '@testing-library/svelte'
import EChart from './EChart.svelte'

const mockChart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }

vi.mock('echarts', () => ({ init: vi.fn(() => mockChart) }))

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('EChart', () => {
  it('calls init and setOption on mount', async () => {
    const { unmount } = render(EChart, { option: { title: { text: 'test' } } })
    const echarts = await import('echarts')
    expect(echarts.init).toHaveBeenCalled()
    expect(mockChart.setOption).toHaveBeenCalledWith({ title: { text: 'test' } })
    unmount()
  })

  it('calls dispose on unmount', async () => {
    const { unmount } = render(EChart, { option: {} })
    unmount()
    expect(mockChart.dispose).toHaveBeenCalled()
  })

  it('initialises with a theme built from the CSS variables', async () => {
    document.documentElement.style.setProperty('--chart-1', '#123456')
    const { unmount } = render(EChart, { option: {} })
    const echarts = await import('echarts')
    const theme = (echarts.init as any).mock.calls[0][1]
    expect(theme.color[0]).toBe('#123456')
    unmount()
    document.documentElement.style.removeProperty('--chart-1')
  })

  it('re-themes on theme change', async () => {
    document.documentElement.setAttribute('data-theme', 'light')
    document.documentElement.style.setProperty('--chart-1', '#111111')
    const option = { title: { text: 'again' } }
    const { unmount } = render(EChart, { option })
    const echarts = await import('echarts')
    expect(echarts.init).toHaveBeenCalledTimes(1)

    document.documentElement.style.setProperty('--chart-1', '#222222')
    document.documentElement.setAttribute('data-theme', 'dark')
    await waitFor(() => expect(echarts.init).toHaveBeenCalledTimes(2))
    expect(mockChart.dispose).toHaveBeenCalledTimes(1)
    expect((echarts.init as any).mock.calls[1][1].color[0]).toBe('#222222')
    expect(mockChart.setOption).toHaveBeenLastCalledWith(option)
    unmount()
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.style.removeProperty('--chart-1')
  })
})
