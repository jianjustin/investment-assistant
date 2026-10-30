import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/svelte'
import { createRawSnippet } from 'svelte'
import PageHeader from './PageHeader.svelte'

afterEach(() => cleanup())

const snip = (html: string) => createRawSnippet(() => ({ render: () => html }))

describe('PageHeader', () => {
  it('level defaults to 2', () => {
    render(PageHeader, { title: '今日计划' })
    expect(screen.getByRole('heading', { level: 2, name: '今日计划' })).toBeInTheDocument()
  })

  it('level 1 and 3', () => {
    render(PageHeader, { title: 'A', level: 1 })
    expect(screen.getByRole('heading', { level: 1, name: 'A' })).toBeInTheDocument()
    cleanup()
    render(PageHeader, { title: 'B', level: 3 })
    expect(screen.getByRole('heading', { level: 3, name: 'B' })).toBeInTheDocument()
  })

  it('meta sits under the title; actions has one area', () => {
    const { container } = render(PageHeader, {
      title: '计划', meta: snip('<span>口径 plan-2</span>'), actions: snip('<button>保存</button><a href="#x">更多</a>'),
    })
    expect(screen.getByText('口径 plan-2')).toBeInTheDocument()
    expect(container.querySelectorAll('[data-slot="page-header-actions"]').length).toBe(1)
    expect(screen.getByRole('button', { name: '保存' })).toBeInTheDocument()
    const heading = screen.getByRole('heading')
    expect(heading.compareDocumentPosition(screen.getByText('口径 plan-2')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('without meta and actions there is no empty container', () => {
    const { container } = render(PageHeader, { title: '计划' })
    expect(container.querySelector('[data-slot="page-header-actions"]')).toBeNull()
    expect(container.querySelector('[data-slot="page-header-meta"]')).toBeNull()
  })
})
