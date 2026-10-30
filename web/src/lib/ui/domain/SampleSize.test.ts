import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/svelte'
import SampleSize from './SampleSize.svelte'

afterEach(() => cleanup())

describe('SampleSize', () => {
  it('below min warns 样本不足', () => {
    render(SampleSize, { n: 3 })
    expect(screen.getByText('n = 3')).toBeInTheDocument()
    expect(screen.getByText('样本不足').closest('[data-slot="badge"]')).toHaveAttribute('data-tone', 'warn')
  })

  it('at min plain', () => {
    render(SampleSize, { n: 5 })
    expect(screen.getByText('n = 5')).toBeInTheDocument()
    expect(screen.queryByText('样本不足')).toBeNull()
  })

  it('custom min', () => {
    render(SampleSize, { n: 8, min: 10 })
    expect(screen.getByText('样本不足')).toBeInTheDocument()
  })

  it('zero is insufficient, not empty', () => {
    render(SampleSize, { n: 0 })
    expect(screen.getByText('n = 0')).toBeInTheDocument()
    expect(screen.getByText('样本不足')).toBeInTheDocument()
  })

  it('null shows 没算', () => {
    const { container } = render(SampleSize, { n: null })
    expect(screen.getByText('没算')).toBeInTheDocument()
    expect(container.textContent).not.toContain('n =')
  })
})
