import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte'
import { createRawSnippet } from 'svelte'
import DataBlock from './DataBlock.svelte'

afterEach(() => cleanup())

const content = createRawSnippet(() => ({ render: () => '<p>计划内容</p>' }))

describe('DataBlock', () => {
  it('loading shows skeletons and no text', () => {
    const { container } = render(DataBlock, { state: 'loading', children: content })
    expect(container.textContent?.trim()).toBe('')
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0)
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull()
    expect(screen.queryByText('计划内容')).toBeNull()
  })

  it('loading has row, block and table presets', () => {
    const counts: number[] = []
    for (const skeleton of ['row', 'block', 'table'] as const) {
      const { container, unmount } = render(DataBlock, { state: 'loading', skeleton })
      counts.push(container.querySelectorAll('[data-slot="skeleton"]').length)
      unmount()
    }
    expect(counts[0]).toBe(1)
    expect(counts[1]).toBe(1)
    expect(counts[2]).toBeGreaterThan(3)
  })

  it('empty is one secondary line with the reason', () => {
    render(DataBlock, { state: 'empty', message: '今日无触发', children: content })
    expect(screen.getByText('今日无触发')).toHaveClass('text-muted-foreground')
    expect(screen.queryByText('没算')).toBeNull()
    expect(screen.queryByText('计划内容')).toBeNull()
  })

  it('not_computed has the 没算 badge and what is missing', () => {
    const { container } = render(DataBlock, { state: 'not_computed', message: '缺资金快照，未计算股数', children: content })
    expect(screen.getByText('缺资金快照，未计算股数')).toBeInTheDocument()
    const badge = screen.getByText('没算').closest('[data-slot="badge"]')!
    expect(badge).toHaveAttribute('data-tone', 'warn')
    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(screen.queryByText('计划内容')).toBeNull()
  })

  it('degraded shows the content and a warn alert', () => {
    render(DataBlock, { state: 'degraded', message: 'Yahoo 空结果，日线用上一交易日', children: content })
    expect(screen.getByText('计划内容')).toBeInTheDocument()
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Yahoo 空结果，日线用上一交易日')
    expect(alert.className).toContain('border-warn/40')
    // the alert comes first
    expect(alert.compareDocumentPosition(screen.getByText('计划内容')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('error has a danger alert and a retry button that calls back', async () => {
    const onRetry = vi.fn()
    render(DataBlock, { state: 'error', message: '概念卡暂不可用：网络中断', onRetry, children: content })
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('概念卡暂不可用：网络中断')
    expect(alert.className).toContain('border-destructive/40')
    await fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('计划内容')).toBeNull()
  })

  it('error without onRetry has no button; retryLabel renames it', () => {
    render(DataBlock, { state: 'error', message: '失败' })
    expect(screen.queryByRole('button')).toBeNull()
    cleanup()
    render(DataBlock, { state: 'error', message: '失败', onRetry: () => {}, retryLabel: '再试一次' })
    expect(screen.getByRole('button', { name: '再试一次' })).toBeInTheDocument()
  })

  it('ready renders only the content', () => {
    const { container } = render(DataBlock, { state: 'ready', children: content })
    expect(screen.getByText('计划内容')).toBeInTheDocument()
    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(container.querySelector('[data-slot="skeleton"]')).toBeNull()
  })

  it('page fills the content area', () => {
    const { container } = render(DataBlock, { state: 'error', message: '整页取不到', page: true })
    expect(container.firstElementChild!.className).toContain('min-h-')
    cleanup()
    const plain = render(DataBlock, { state: 'error', message: '块取不到' })
    expect(plain.container.firstElementChild!.className).not.toContain('min-h-')
  })
})
