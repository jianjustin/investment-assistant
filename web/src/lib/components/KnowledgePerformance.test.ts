import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/svelte'
import KnowledgePerformance from './KnowledgePerformance.svelte'
import * as api from '../api'
import { WorkbenchError } from '../workbench'
import { resetConceptIndex } from '../knowledge'
import { perf } from '../growth-fixtures'

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  vi.spyOn(api, 'getKnowledgePerformance').mockResolvedValue(perf())
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('KnowledgePerformance', () => {
  it('sample line always first', async () => {
    render(KnowledgePerformance, { id: 3 })
    const section = await screen.findByRole('region', { name: '表现回看' })
    const first = section.querySelector('[data-sample]') as HTMLElement
    expect(first).toHaveTextContent('样本 6 个单元 · 有结果 5 · 过期 1 · 均值 +0.42R · 中位 +0.30R')
    // nothing but the heading comes before it
    const before = [...section.children].slice(0, [...section.children].indexOf(first))
    expect(before.map(el => el.tagName)).toEqual(['H3'])
    expect(api.getKnowledgePerformance).toHaveBeenCalledWith(3)
    expect(section).toHaveTextContent('描述性统计，样本小且重叠，不代表这条经验有效')
    expect(section).toHaveTextContent('证据：未验证')
  })

  it('sample line stays first even with no sample at all', async () => {
    vi.mocked(api.getKnowledgePerformance).mockResolvedValue(perf({
      sample: { count: 0, determined: 0, expired: 0, r_mean: null, r_median: null }, rows: [], by_version: [],
      reviews_cited: 0, note: '样本 0 个（有结果 0 个），少于 5 个不给均值' }))
    render(KnowledgePerformance, { id: 3 })
    const section = await screen.findByRole('region', { name: '表现回看' })
    expect(section.querySelector('[data-sample]')).toHaveTextContent('样本 0 个单元 · 有结果 0 · 过期 0 · 少于 5 个不给均值')
  })

  it('below five shows 少于 5 个不给均值', async () => {
    vi.mocked(api.getKnowledgePerformance).mockResolvedValue(perf({
      sample: { count: 3, determined: 2, expired: 1, r_mean: null, r_median: null },
      note: '样本 3 个（有结果 2 个），少于 5 个不给均值' }))
    render(KnowledgePerformance, { id: 3 })
    const section = await screen.findByRole('region', { name: '表现回看' })
    const line = section.querySelector('[data-sample]')!
    expect(line).toHaveTextContent('少于 5 个不给均值')
    expect(line.textContent).not.toMatch(/均值 [+-]/)
    expect(line.textContent).not.toMatch(/中位/)
  })

  it('rows link to the plan page and by_version is a table', async () => {
    render(KnowledgePerformance, { id: 3 })
    const table = await screen.findByRole('table', { name: '每个单元的首个引用版本' })
    const row = within(table).getAllByRole('row')[1]
    expect(row).toHaveTextContent('NVDA')
    expect(row).toHaveTextContent('2026-10-22')
    expect(row).toHaveTextContent('第 1 版')            // plan version
    expect(row).toHaveTextContent('引用第 1 版知识')
    expect(row).toHaveTextContent('已平仓')
    expect(row).toHaveTextContent('+0.50R')
    expect(within(row).getByRole('link', { name: /NVDA/ })).toHaveAttribute('href', '#plan/p-agent')
    const byVersion = screen.getByRole('table', { name: '按知识版本' })
    expect(within(byVersion).getAllByRole('row')[1]).toHaveTextContent('第 1 版')
    expect(within(byVersion).getAllByRole('row')[1]).toHaveTextContent('4')
  })

  it('reviews cited separate', async () => {
    render(KnowledgePerformance, { id: 3 })
    const section = await screen.findByRole('region', { name: '表现回看' })
    const cited = within(section).getByText('复查中被引用 3 次')
    expect(cited.closest('[data-sample]')).toBeNull()
    expect(section.querySelector('[data-sample]')!.textContent).not.toMatch(/复查/)
  })

  it('shows the failure instead of an empty block', async () => {
    vi.mocked(api.getKnowledgePerformance).mockRejectedValue(new WorkbenchError('迁移 027 未执行', 503))
    render(KnowledgePerformance, { id: 3 })
    expect(await screen.findByText('迁移 027 未执行')).toBeInTheDocument()
  })
})
