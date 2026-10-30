import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/svelte'
import SourceBadge from './SourceBadge.svelte'

afterEach(() => cleanup())

describe('SourceBadge', () => {
  it('shows the source name', () => {
    render(SourceBadge, { source: 'yahoo' })
    expect(screen.getByText('yahoo')).toBeInTheDocument()
    expect(screen.queryByText('备源')).toBeNull()
  })

  it('fallback is flagged in words, not colour alone', () => {
    const { container } = render(SourceBadge, { source: 'stooq', fallback: true })
    expect(screen.getByText('stooq')).toBeInTheDocument()
    expect(screen.getByText('备源')).toBeInTheDocument()
    expect(container.querySelector('[data-slot="badge"]')).toHaveAttribute('data-fallback', 'true')
  })
})
