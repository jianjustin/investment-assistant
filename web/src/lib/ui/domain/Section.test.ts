import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/svelte'
import { createRawSnippet } from 'svelte'
import Section from './Section.svelte'

afterEach(() => cleanup())

const snip = (html: string) => createRawSnippet(() => ({ render: () => html }))

describe('Section', () => {
  it('level defaults to 3 and the region is named by its heading', () => {
    render(Section, { title: '入场条件', children: snip('<p>内容</p>') })
    expect(screen.getByRole('heading', { level: 3, name: '入场条件' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '入场条件' })).toBeInTheDocument()
  })

  it('level 2 and 4, description and actions', () => {
    render(Section, { title: '二级', level: 2, description: '说明文字', actions: snip('<a href="#x">更多</a>'), children: snip('<p>x</p>') })
    expect(screen.getByRole('heading', { level: 2, name: '二级' })).toBeInTheDocument()
    expect(screen.getByText('说明文字')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '更多' })).toBeInTheDocument()
    cleanup()
    render(Section, { title: '四级', level: 4, children: snip('<p>x</p>') })
    expect(screen.getByRole('heading', { level: 4, name: '四级' })).toBeInTheDocument()
  })

  it('without a title there is no heading', () => {
    render(Section, { children: snip('<p>只有内容</p>') })
    expect(screen.queryByRole('heading')).toBeNull()
    expect(screen.getByText('只有内容')).toBeInTheDocument()
  })
})
