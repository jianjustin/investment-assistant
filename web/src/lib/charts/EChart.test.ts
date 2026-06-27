import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/svelte'
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
})
