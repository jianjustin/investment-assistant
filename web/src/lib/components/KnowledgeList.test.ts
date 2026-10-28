import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import KnowledgeList from './KnowledgeList.svelte'
import * as api from '../api'
import { WorkbenchError } from '../workbench'
import { resetConceptIndex } from '../knowledge'
import { entry, knowledgeDraft } from '../growth-fixtures'

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  vi.spyOn(api, 'getMyKnowledge').mockResolvedValue({ items: [
    entry(), entry({ id: 4, title: '财报前不加仓', scope: '持仓、财报前', concepts: ['concept:plan.earnings@1'],
                     tickers: [], current_version: 1, status: 'archived', citation_count: 0, sample_count: 0 })] })
  vi.spyOn(api, 'getKnowledgeDrafts').mockResolvedValue({ drafts: [knowledgeDraft(), knowledgeDraft({ id: 202 })] })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('KnowledgeList', () => {
  it('rows show title, attachments, version, status, times, citations and samples', async () => {
    render(KnowledgeList)
    const link = await screen.findByRole('link', { name: '回踩别追' })
    expect(link).toHaveAttribute('href', '#knowledge/mine/3')
    const row = link.closest('tr')!
    expect(row).toHaveTextContent('趋势回踩触发后')
    expect(row).toHaveTextContent('第 2 版')
    expect(row).toHaveTextContent('有效')
    expect(row).toHaveTextContent('写入 2026-10-20 18:00:00 北京')
    expect(row).toHaveTextContent('最近修改 2026-10-22 18:00:00 北京')
    expect(row).toHaveTextContent('被引用 4 次')
    expect(row).toHaveTextContent('表现样本 3')
    expect(within(row).getByRole('link', { name: 'NVDA' })).toHaveAttribute('href', '#instrument/NVDA')
    const archived = screen.getByRole('link', { name: '财报前不加仓' }).closest('tr')!
    expect(archived).toHaveTextContent('已归档')
  })

  it('list filters', async () => {
    render(KnowledgeList)
    await screen.findByRole('link', { name: '回踩别追' })
    expect(api.getMyKnowledge).toHaveBeenLastCalledWith({ status: 'active' })
    await fireEvent.change(screen.getByLabelText('状态'), { target: { value: 'all' } })
    await waitFor(() => expect(api.getMyKnowledge).toHaveBeenLastCalledWith({ status: 'all' }))
    await fireEvent.change(screen.getByLabelText('标的'), { target: { value: ' aapl ' } })
    await waitFor(() => expect(api.getMyKnowledge).toHaveBeenLastCalledWith({ status: 'all', ticker: 'AAPL' }))
    await fireEvent.change(screen.getByLabelText('概念'), { target: { value: 'plan.stop' } })
    await waitFor(() => expect(api.getMyKnowledge).toHaveBeenLastCalledWith({ status: 'all', ticker: 'AAPL', concept: 'plan.stop' }))
  })

  it('links to writing a new entry and to the open drafts with their count', async () => {
    render(KnowledgeList)
    expect(await screen.findByRole('link', { name: '写一条' })).toHaveAttribute('href', '#knowledge/mine/new')
    const drafts = await screen.findByRole('link', { name: '草稿（2）' })
    expect(drafts).toHaveAttribute('href', '#knowledge/mine/drafts')
    expect(api.getKnowledgeDrafts).toHaveBeenCalledWith('open')
  })

  it('shows an empty state and keeps working when the drafts count is unavailable', async () => {
    vi.mocked(api.getMyKnowledge).mockResolvedValue({ items: [] })
    vi.mocked(api.getKnowledgeDrafts).mockRejectedValue(new Error('x'))
    render(KnowledgeList)
    expect(await screen.findByText('还没有我的知识')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '草稿' })).toBeInTheDocument()
  })

  it('says so when migration 027 has not run', async () => {
    vi.mocked(api.getMyKnowledge).mockRejectedValue(new WorkbenchError('迁移 027 未执行', 503))
    render(KnowledgeList)
    expect(await screen.findByText('迁移 027 未执行')).toBeInTheDocument()
  })
})
