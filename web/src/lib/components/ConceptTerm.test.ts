import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import { createRawSnippet } from 'svelte'
import ConceptTerm from './ConceptTerm.svelte'
import * as api from '../api'
import { resetConceptIndex } from '../knowledge'

const index = () => ({
  knowledge_version: 'knowledge-1',
  groups: [{ id: 'plan', title: '规则计划 `plan-1`', count: 2 }],
  concepts: [
    { id: 'plan.stop', ref: 'concept:plan.stop@1', title: '止损', group: 'plan', version: 1, applies_to: ['plan-1'],
      summary: '参考价减 2 倍 ATR14，四舍五入到分。', related: [] },
    { id: 'plan.target1', ref: 'concept:plan.target1@2', title: '第一目标', group: 'plan', version: 2, applies_to: ['plan-1'],
      summary: '参考价加 4 倍 ATR14。', related: [] },
  ],
})
const text = (value: string) => createRawSnippet(() => ({ render: () => `<span>${value}</span>` }))

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockResolvedValue(index())
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('ConceptTerm', () => {
  it('shows title when no children', async () => {
    render(ConceptTerm, { id: 'plan.stop' })
    expect(await screen.findByText('止损')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /止损/ })).toBeInTheDocument()
  })

  it('expands summary, ref and full-card link', async () => {
    render(ConceptTerm, { id: 'plan.stop', children: text('止损价') })
    const button = await screen.findByRole('button', { name: /止损/ })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('参考价减 2 倍 ATR14，四舍五入到分。')).toBeInTheDocument()
    expect(screen.getByText('concept:plan.stop@1')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '看完整卡' })).toHaveAttribute('href', '#knowledge/plan.stop')
    expect(screen.getByText('止损价')).toBeInTheDocument()
    await fireEvent.click(button)
    await waitFor(() => expect(screen.queryByText('参考价减 2 倍 ATR14，四舍五入到分。')).toBeNull())
  })

  it('Esc collapses', async () => {
    render(ConceptTerm, { id: 'plan.stop' })
    const button = await screen.findByRole('button', { name: /止损/ })
    await fireEvent.click(button)
    expect(screen.getByRole('link', { name: '看完整卡' })).toBeInTheDocument()
    await fireEvent.keyDown(button, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('link', { name: '看完整卡' })).toBeNull())      // the popover unmounts on the next tick
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })

  it('only one open at a time', async () => {
    render(ConceptTerm, { id: 'plan.stop' })
    render(ConceptTerm, { id: 'plan.target1' })
    const stop = await screen.findByRole('button', { name: /止损/ })
    const target = await screen.findByRole('button', { name: /第一目标/ })
    await fireEvent.click(stop)
    expect(screen.getByText('参考价减 2 倍 ATR14，四舍五入到分。')).toBeInTheDocument()
    await fireEvent.click(target)
    expect(screen.getByText('参考价加 4 倍 ATR14。')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('参考价减 2 倍 ATR14，四舍五入到分。')).toBeNull())
    expect(stop).toHaveAttribute('aria-expanded', 'false')
  })

  it('popover opens, Esc closes, only one open', async () => {
    const first = render(ConceptTerm, { id: 'plan.stop' })
    render(ConceptTerm, { id: 'plan.target1' })
    const stop = await screen.findByRole('button', { name: '概念：止损' })
    const target = await screen.findByRole('button', { name: '概念：第一目标' })
    // the glyph is an icon, not the ⓘ character
    expect(stop.querySelector('svg[aria-hidden="true"]')).not.toBeNull()
    expect(stop.textContent!.trim()).toBe('')
    await fireEvent.click(stop)
    const popovers = () => [...document.querySelectorAll('[data-slot="popover-content"]')]
    expect(popovers()).toHaveLength(1)
    expect(popovers()[0]).toHaveTextContent('参考价减 2 倍 ATR14，四舍五入到分。')
    expect(first.container.contains(popovers()[0])).toBe(false)             // rendered in a portal
    await fireEvent.keyDown(document.activeElement ?? stop, { key: 'Escape' })
    await waitFor(() => expect(popovers()).toHaveLength(0))
    await fireEvent.click(stop)
    await fireEvent.click(target)
    await waitFor(() => expect(popovers()).toHaveLength(1))
    expect(popovers()[0]).toHaveTextContent('参考价加 4 倍 ATR14。')
    expect(stop).toHaveAttribute('aria-expanded', 'false')
    expect(target).toHaveAttribute('aria-expanded', 'true')
  })

  it('index failure shows 概念卡暂不可用', async () => {
    vi.mocked(api.getConcepts).mockReset().mockRejectedValue(new Error('概念卡加载失败：bad'))
    render(ConceptTerm, { id: 'plan.stop', children: text('止损价') })
    expect(screen.getByText('止损价')).toBeInTheDocument()
    const button = await screen.findByRole('button')
    await fireEvent.click(button)
    expect(await screen.findByText(/概念卡暂不可用：概念卡加载失败：bad/)).toBeInTheDocument()
    expect(screen.getByText('止损价')).toBeInTheDocument()
  })

  it('unknown id renders text without button', async () => {
    render(ConceptTerm, { id: 'plan.nope', children: text('某词') })
    expect(screen.getByText('某词')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('button')).toBeNull())
    expect(api.getConcepts).toHaveBeenCalled()
    expect(screen.getByText('某词')).toBeInTheDocument()
  })
})
