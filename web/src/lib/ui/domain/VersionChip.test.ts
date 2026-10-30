import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/svelte'
import VersionChip from './VersionChip.svelte'

afterEach(() => cleanup())

describe('VersionChip', () => {
  it('shows 第 k 版', () => {
    render(VersionChip, { version: 2 })
    expect(screen.getByText('第 2 版')).toBeInTheDocument()
    expect(screen.queryByText('最新')).toBeNull()
  })

  it('latest suffix', () => {
    render(VersionChip, { version: 3, latest: 3 })
    expect(screen.getByText('第 3 版')).toBeInTheDocument()
    expect(screen.getByText('最新')).toBeInTheDocument()
  })

  it('older links to latest', () => {
    render(VersionChip, { version: 1, latest: 3, latestHref: '#plan/p3' })
    expect(screen.queryByText('最新')).toBeNull()
    expect(screen.getByRole('link', { name: '最新第 3 版' })).toHaveAttribute('href', '#plan/p3')
  })

  it('older without a latest link is plain text', () => {
    render(VersionChip, { version: 1, latest: 3 })
    expect(screen.getByText('最新第 3 版')).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('the version itself can be a link', () => {
    render(VersionChip, { version: 2, latest: 2, href: '#plan/p2' })
    expect(screen.getByRole('link', { name: '第 2 版' })).toHaveAttribute('href', '#plan/p2')
  })

  it('ref is the monospace title', () => {
    const { container } = render(VersionChip, { version: 1, ref: 'concept:plan.stop@1' })
    const chip = container.firstElementChild!
    expect(chip).toHaveAttribute('title', 'concept:plan.stop@1')
    expect(chip.querySelector('.font-mono')).toBeNull()   // title is a native tooltip; the ref is also kept as data
    expect(chip).toHaveAttribute('data-ref', 'concept:plan.stop@1')
  })
})
