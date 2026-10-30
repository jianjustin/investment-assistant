import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/svelte'
import { createRawSnippet } from 'svelte'
import { Button } from './index'

const text = (s: string) => createRawSnippet(() => ({ render: () => `<span>${s}</span>` }))

afterEach(() => cleanup())

describe('Button', () => {
  it('renders a native button by default', () => {
    render(Button, { children: text('保存') })
    const btn = screen.getByRole('button', { name: '保存' })
    expect(btn.tagName).toBe('BUTTON')
    expect(btn).toHaveAttribute('type', 'button')
    expect(btn).not.toBeDisabled()
  })

  it('renders a link with href', () => {
    render(Button, { href: '#plan/1', children: text('查看') })
    const link = screen.getByRole('link', { name: '查看' })
    expect(link.tagName).toBe('A')
    expect(link).toHaveAttribute('href', '#plan/1')
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('busy disables and shows busyText with aria-busy', () => {
    render(Button, { busy: true, busyText: '提交中…', children: text('提交') })
    const btn = screen.getByRole('button', { name: /提交中/ })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('aria-busy', 'true')
    expect(screen.queryByText('提交')).toBeNull()
  })

  it('busy without busyText keeps the label', () => {
    render(Button, { busy: true, children: text('提交') })
    const btn = screen.getByRole('button', { name: '提交' })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('aria-busy', 'true')
  })

  it('variant link is underlined, others are not', () => {
    const underlined: Record<string, boolean> = {}
    for (const variant of ['primary', 'outline', 'ghost', 'link', 'destructive'] as const) {
      const { unmount } = render(Button, { variant, children: text(variant) })
      underlined[variant] = screen.getByRole('button', { name: variant }).classList.contains('underline')
      unmount()
    }
    expect(underlined).toEqual({ primary: false, outline: false, ghost: false, link: true, destructive: false })
  })

  it('sizes are 28px / 32px / 28px square', () => {
    const cls = (size: 'sm' | 'md' | 'icon') => {
      const { unmount } = render(Button, { size, children: text(size) })
      const c = screen.getByRole('button', { name: size }).className
      unmount()
      return c
    }
    expect(cls('sm')).toMatch(/\bh-7\b/)
    expect(cls('md')).toMatch(/\bh-8\b/)
    expect(cls('icon')).toMatch(/\bsize-7\b/)
  })

  it('default variant is outline', () => {
    render(Button, { children: text('x') })
    expect(screen.getByRole('button').className).toMatch(/\bbg-card\b/)
  })
})
