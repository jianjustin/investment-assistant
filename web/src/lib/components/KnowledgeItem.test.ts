import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import KnowledgeItem from './KnowledgeItem.svelte'
import * as api from '../api'
import { WorkbenchError } from '../workbench'
import { resetConceptIndex } from '../knowledge'
import { itemView, perf, version } from '../growth-fixtures'

const archived = () => itemView({ item: { ...itemView().item, status: 'archived' },
  status_history: [{ status: 'archived', reason: '过时了', created_at: '2026-10-25T10:00:00Z' }] })

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  vi.spyOn(api, 'getKnowledgeItem').mockResolvedValue(itemView())
  vi.spyOn(api, 'getKnowledgePerformance').mockResolvedValue(perf())
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('KnowledgeItem', () => {
  it('shows the current version in full, as plain text, with its attachments', async () => {
    render(KnowledgeItem, { id: 3 })
    expect(await screen.findByRole('heading', { name: '回踩别追（改）' })).toBeInTheDocument()
    expect(api.getKnowledgeItem).toHaveBeenCalledWith(3, undefined)
    const body = screen.getByText(/第 2 版正文/)
    expect(body.textContent).toBe('第 2 版正文\n第二行')
    expect(body.className).toMatch(/whitespace-pre-wrap/)
    expect(screen.getByText('趋势回踩触发后的第一天')).toBeInTheDocument()
    expect(screen.getByText('放量突破时除外')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'NVDA' })).toHaveAttribute('href', '#instrument/NVDA')
    expect(await screen.findByRole('button', { name: '概念：review.discipline_chase' })).toBeInTheDocument()
    expect(screen.getByText('有效')).toBeInTheDocument()
    expect(screen.queryByText(/这是第/)).toBeNull()
  })

  it('item shows version history with changed fields', async () => {
    render(KnowledgeItem, { id: 3 })
    const history = await screen.findByRole('list', { name: '版本历史' })
    const rows = within(history).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('第 2 版')
    expect(rows[0]).toHaveTextContent('2026-10-22 18:00:00 北京')
    expect(rows[0]).toHaveTextContent('改了：标题、正文、适用范围')
    expect(within(rows[0]).getByRole('link', { name: '第 2 版' })).toHaveAttribute('href', '#knowledge/mine/3@2')
    expect(rows[1]).toHaveTextContent('第 1 版')
    expect(rows[1]).toHaveTextContent('首版 · 手写')
    expect(within(rows[1]).getByRole('link', { name: '第 1 版' })).toHaveAttribute('href', '#knowledge/mine/3@1')
  })

  it('old version banner 这是第 k 版，最新为第 n 版', async () => {
    render(KnowledgeItem, { id: 3, version: 1 })
    expect(await screen.findByText('这是第 1 版，最新为第 2 版')).toBeInTheDocument()
    expect(api.getKnowledgeItem).toHaveBeenCalledWith(3, 1)
    expect(screen.getByRole('link', { name: '查看最新版' })).toHaveAttribute('href', '#knowledge/mine/3')
    expect(screen.getByRole('heading', { name: '回踩别追 v1' })).toBeInTheDocument()
    expect(screen.getByText(/第 1 版正文/)).toBeInTheDocument()
  })

  it('revise sends base_version and handles 409 knowledge_stale', async () => {
    vi.spyOn(api, 'postKnowledgeVersion')
      .mockRejectedValueOnce(new WorkbenchError('knowledge_stale: 这条知识已更新到第 3 版，请刷新后再改', 409))
      .mockResolvedValueOnce({ status: 'created' } as any)
    render(KnowledgeItem, { id: 3 })
    await fireEvent.click(await screen.findByRole('button', { name: '改' }))
    const title = screen.getByLabelText('标题') as HTMLInputElement
    expect(title.value).toBe('回踩别追（改）')           // prefilled with the current version
    await fireEvent.input(title, { target: { value: '回踩别追（再改）' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交' }))
    expect(await screen.findByText('这条知识已更新到第 3 版，请刷新后再改')).toBeInTheDocument()
    expect(vi.mocked(api.postKnowledgeVersion).mock.calls[0][0]).toBe(3)
    expect(vi.mocked(api.postKnowledgeVersion).mock.calls[0][1]).toMatchObject({
      base_version: 2, title: '回踩别追（再改）', scope: '趋势回踩触发后的第一天', concepts: ['review.discipline_chase'], tickers: ['NVDA'] })
    expect(vi.mocked(api.postKnowledgeVersion).mock.calls[0][1].request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect((screen.getByLabelText('标题') as HTMLInputElement).value).toBe('回踩别追（再改）')   // form kept
    // refreshing reloads the item; the form stays open with what the user typed
    vi.mocked(api.getKnowledgeItem).mockClear()
    await fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    await waitFor(() => expect(api.getKnowledgeItem).toHaveBeenCalledTimes(1))
    // a retry on the same content succeeds
    await fireEvent.click(screen.getByRole('button', { name: '提交' }))
    await waitFor(() => expect(api.postKnowledgeVersion).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByLabelText('标题')).toBeNull())      // form closed after success
  })

  it('archive and restore with reason', async () => {
    const post = vi.spyOn(api, 'postKnowledgeStatus').mockResolvedValue({ status: 'created' } as any)
    render(KnowledgeItem, { id: 3 })
    await fireEvent.click(await screen.findByRole('button', { name: '归档' }))
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '  过时了  ' } })
    await fireEvent.click(screen.getByRole('button', { name: '确认归档' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0]).toBe(3)
    expect(post.mock.calls[0][1]).toMatchObject({ status: 'archived', reason: '过时了' })
    expect(post.mock.calls[0][1].request_id).toMatch(/^[0-9a-f-]{36}$/)
    cleanup()

    vi.mocked(api.getKnowledgeItem).mockResolvedValue(archived())
    render(KnowledgeItem, { id: 3 })
    expect(await screen.findByText('已归档')).toBeInTheDocument()
    expect(screen.getByText(/过时了/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '改' })).toBeNull()          // archived: restore first
    expect(screen.getByText('已归档，先恢复才能改')).toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: '恢复' }))
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '又有用了' } })
    await fireEvent.click(screen.getByRole('button', { name: '确认恢复' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
    expect(post.mock.calls[1][1]).toMatchObject({ status: 'active', reason: '又有用了' })
  })

  it('shows a status conflict in Chinese and keeps the reason', async () => {
    vi.spyOn(api, 'postKnowledgeStatus').mockRejectedValue(new WorkbenchError('status_unchanged', 409))
    render(KnowledgeItem, { id: 3 })
    await fireEvent.click(await screen.findByRole('button', { name: '归档' }))
    await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '过时了' } })
    await fireEvent.click(screen.getByRole('button', { name: '确认归档' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('状态没有变化')
    expect((screen.getByLabelText('理由') as HTMLInputElement).value).toBe('过时了')
  })

  it('citations list links to plans', async () => {
    render(KnowledgeItem, { id: 3 })
    const list = await screen.findByRole('list', { name: '被引用' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('NVDA 2026-10-22 第 1 版')
    expect(rows[0]).toHaveTextContent('引用的是第 1 版')
    expect(rows[0]).toHaveTextContent('论点')
    expect(within(rows[0]).getByRole('link')).toHaveAttribute('href', '#plan/p-agent')
    expect(rows[1]).toHaveTextContent('复查')
    expect(rows[1]).toHaveTextContent('引用的是第 2 版')
    expect(within(rows[1]).getByRole('link')).toHaveAttribute('href', '#plan/p-agent')
  })

  it('says so when nothing cites the entry', async () => {
    vi.mocked(api.getKnowledgeItem).mockResolvedValue(itemView({ citations: [] }))
    render(KnowledgeItem, { id: 3 })
    expect(await screen.findByText('还没有被计划或复查引用')).toBeInTheDocument()
  })

  it('embeds the performance block', async () => {
    render(KnowledgeItem, { id: 3 })
    expect(await screen.findByRole('region', { name: '表现回看' })).toBeInTheDocument()
    expect(api.getKnowledgePerformance).toHaveBeenCalledWith(3)
  })

  it('a missing entry and a missing migration are reported', async () => {
    vi.mocked(api.getKnowledgeItem).mockRejectedValue(new WorkbenchError('not found', 404))
    render(KnowledgeItem, { id: 99 })
    expect(await screen.findByText('没有这条知识：99')).toBeInTheDocument()
    cleanup()
    vi.mocked(api.getKnowledgeItem).mockRejectedValue(new WorkbenchError('迁移 027 未执行', 503))
    render(KnowledgeItem, { id: 3 })
    expect(await screen.findByText('迁移 027 未执行')).toBeInTheDocument()
  })
})
