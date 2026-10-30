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

  it('badgeLabel names the badge for assistive tech and as a tooltip', () => {
    render(TabNav, { label: '复盘页签', items: [{ href: '#review/cards', label: '复盘卡', current: false, badge: 2, badgeLabel: '待审定 2 张' },
                                                { href: '#review/trades', label: '成交', current: false, badge: 5 }] })
    const badge = screen.getByLabelText('待审定 2 张')
    expect(badge).toHaveTextContent('2')
    expect(badge).toHaveAttribute('title', '待审定 2 张')
    // without a label the badge is unchanged: no aria-label, no title
    const plain = screen.getByRole('link', { name: /成交/ }).querySelector('span')!
    expect(plain).not.toHaveAttribute('aria-label')
    expect(plain).not.toHaveAttribute('title')
  })
})
