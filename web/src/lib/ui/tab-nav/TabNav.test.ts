import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/svelte'
import TabNav from './TabNav.svelte'

afterEach(() => cleanup())

const items = [
  { href: '#review/cards', label: '复盘卡', current: true, badge: 3 },
  { href: '#review/trades', label: '成交', current: false },
  { href: '#review/stats', label: '统计', current: false, badge: '新' },
]

describe('TabNav', () => {
  it('renders links with aria-current on the current item', () => {
    render(TabNav, { label: '复盘页签', items })
    const nav = screen.getByRole('navigation', { name: '复盘页签' })
    expect(nav).toBeInTheDocument()
    const links = screen.getAllByRole('link')
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['#review/cards', '#review/trades', '#review/stats'])
    expect(screen.getByRole('link', { name: /复盘卡/ })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: '成交' })).not.toHaveAttribute('aria-current')
  })

  it('badge text is shown', () => {
    render(TabNav, { label: '复盘页签', items })
    expect(screen.getByRole('link', { name: /复盘卡/ })).toHaveTextContent('3')
    expect(screen.getByRole('link', { name: /统计/ })).toHaveTextContent('新')
    expect(screen.getByRole('link', { name: '成交' })).toHaveTextContent(/^成交$/)
  })
})
