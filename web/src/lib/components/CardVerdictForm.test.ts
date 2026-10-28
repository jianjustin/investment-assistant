import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import CardVerdictForm from './CardVerdictForm.svelte'
import * as api from '../api'
import { WorkbenchError } from '../workbench'
import { resetConceptIndex } from '../knowledge'
import { lessonRows } from '../growth-fixtures'

const group = (title: string) => screen.getByRole('group', { name: new RegExp(title) })
const submit = () => screen.getByRole('button', { name: '提交审定' })

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  vi.spyOn(api, 'postCardVerdict').mockResolvedValue({ status: 'created' } as any)
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('CardVerdictForm', () => {
  it('every draft must be approved or dismissed before submit', async () => {
    render(CardVerdictForm, { cardId: 12, drafts: lessonRows(), verdict: null })
    expect(submit()).toBeDisabled()
    expect(screen.getByText('还有 2 条教训草稿没有处理')).toBeInTheDocument()
    await fireEvent.click(within(group('回踩不追高')).getByRole('button', { name: '采纳' }))
    expect(submit()).toBeDisabled()
    expect(screen.getByText('还有 1 条教训草稿没有处理')).toBeInTheDocument()
    await fireEvent.click(within(group('止损按计划执行')).getByRole('button', { name: '不采纳' }))
    expect(submit()).toBeEnabled()
    expect(screen.queryByText(/条教训草稿没有处理/)).toBeNull()
    expect(within(group('回踩不追高')).getByRole('button', { name: '采纳' })).toHaveAttribute('aria-pressed', 'true')
    // changing one's mind is fine
    await fireEvent.click(within(group('回踩不追高')).getByRole('button', { name: '不采纳' }))
    expect(submit()).toBeEnabled()
  })

  it('edited fields are sent', async () => {
    const onSubmitted = vi.fn()
    render(CardVerdictForm, { cardId: 12, drafts: lessonRows(), verdict: null, onSubmitted })
    await fireEvent.click(within(group('回踩不追高')).getByRole('button', { name: '采纳' }))
    await fireEvent.input(within(group('回踩不追高')).getByLabelText('标题'), { target: { value: '回踩后别追' } })
    await fireEvent.input(within(group('回踩不追高')).getByLabelText('适用范围'), { target: { value: '回踩修复触发后一周内' } })
    await fireEvent.click(within(group('止损按计划执行')).getByRole('button', { name: '不采纳' }))
    await fireEvent.input(screen.getByLabelText('我的复盘'), { target: { value: '  当时太急了  ' } })
    await fireEvent.click(submit())
    await waitFor(() => expect(api.postCardVerdict).toHaveBeenCalledTimes(1))
    const [id, body] = vi.mocked(api.postCardVerdict).mock.calls[0]
    expect(id).toBe(12)
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(body.note).toBe('当时太急了')
    expect(body.lessons).toEqual([
      { draft_id: 101, action: 'approve', title: '回踩后别追', body: '价格高于入场上沿就等回落。',
        scope: '回踩修复触发后一周内', counter_examples: '放量突破时追高可能是对的',
        concepts: ['review.discipline_chase'], tickers: ['NVDA'] },
      { draft_id: 102, action: 'dismiss', title: '止损按计划执行', body: '触及止损次日就卖。', scope: '持仓期间',
        counter_examples: '财报前后跳空除外', concepts: ['plan.stop'], tickers: [] },
    ])
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledTimes(1))
  })

  it('refuses an adopted lesson whose edit breaks the limits, and sends nothing', async () => {
    render(CardVerdictForm, { cardId: 12, drafts: lessonRows(), verdict: null })
    await fireEvent.click(within(group('回踩不追高')).getByRole('button', { name: '采纳' }))
    await fireEvent.click(within(group('止损按计划执行')).getByRole('button', { name: '不采纳' }))
    await fireEvent.input(within(group('回踩不追高')).getByLabelText('适用范围'), { target: { value: '   ' } })
    await fireEvent.click(submit())
    expect(await screen.findByText(/适用范围必填/)).toBeInTheDocument()
    expect(api.postCardVerdict).not.toHaveBeenCalled()
  })

  it('extra lesson without draft_id', async () => {
    render(CardVerdictForm, { cardId: 12, drafts: [], verdict: null })
    expect(submit()).toBeEnabled()                 // no draft to handle: the note alone is a valid verdict
    await fireEvent.click(screen.getByRole('button', { name: '另写一条' }))
    const extra = screen.getByRole('group', { name: /另写的教训 1/ })
    await fireEvent.input(within(extra).getByLabelText('标题'), { target: { value: '财报前不加仓' } })
    await fireEvent.input(within(extra).getByLabelText('正文'), { target: { value: '财报前三天不再加仓。' } })
    await fireEvent.input(within(extra).getByLabelText('适用范围'), { target: { value: '持仓、财报前' } })
    await fireEvent.input(within(extra).getByLabelText('反例'), { target: { value: '已经大幅浮盈时' } })
    await fireEvent.input(within(extra).getByLabelText('概念'), { target: { value: 'plan.earnings' } })
    await fireEvent.click(within(extra).getByRole('button', { name: '添加概念' }))
    await within(extra).findByRole('button', { name: '移除概念 plan.earnings' })      // the add is async (concept index lookup)
    await fireEvent.click(submit())
    await waitFor(() => expect(api.postCardVerdict).toHaveBeenCalledTimes(1))
    const body = vi.mocked(api.postCardVerdict).mock.calls[0][1]
    expect(body.lessons).toEqual([{ action: 'approve', title: '财报前不加仓', body: '财报前三天不再加仓。',
      scope: '持仓、财报前', counter_examples: '已经大幅浮盈时', concepts: ['plan.earnings'], tickers: [] }])
    expect('draft_id' in body.lessons[0]).toBe(false)
  })

  it('a hand-written lesson may leave the counter example empty (spec 5.1), an adopted draft may not', async () => {
    render(CardVerdictForm, { cardId: 12, drafts: lessonRows().slice(0, 1), verdict: null })
    await fireEvent.click(screen.getByRole('button', { name: '另写一条' }))
    const extra = screen.getByRole('group', { name: /另写的教训 1/ })
    await fireEvent.input(within(extra).getByLabelText('标题'), { target: { value: '财报前不加仓' } })
    await fireEvent.input(within(extra).getByLabelText('正文'), { target: { value: '财报前三天不再加仓。' } })
    await fireEvent.input(within(extra).getByLabelText('适用范围'), { target: { value: '持仓、财报前' } })
    await fireEvent.input(within(extra).getByLabelText('概念'), { target: { value: 'plan.earnings' } })
    await fireEvent.click(within(extra).getByRole('button', { name: '添加概念' }))
    await within(extra).findByRole('button', { name: '移除概念 plan.earnings' })
    await fireEvent.click(within(group('回踩不追高')).getByRole('button', { name: '不采纳' }))
    await fireEvent.click(submit())
    await waitFor(() => expect(api.postCardVerdict).toHaveBeenCalledTimes(1))
    const lessons = vi.mocked(api.postCardVerdict).mock.calls[0][1].lessons
    expect(lessons[lessons.length - 1]).toMatchObject({ action: 'approve', title: '财报前不加仓', counter_examples: '' })
  })

  it('an adopted Agent draft still needs its counter example', async () => {
    render(CardVerdictForm, { cardId: 12, drafts: lessonRows().slice(0, 1), verdict: null })
    await fireEvent.click(within(group('回踩不追高')).getByRole('button', { name: '采纳' }))
    await fireEvent.input(within(group('回踩不追高')).getByLabelText('反例'), { target: { value: '   ' } })
    await fireEvent.click(submit())
    expect(await screen.findByText(/反例必填/)).toBeInTheDocument()
    expect(api.postCardVerdict).not.toHaveBeenCalled()
  })

  it('failure keeps input and request_id', async () => {
    vi.mocked(api.postCardVerdict).mockRejectedValueOnce(new WorkbenchError('boom', 500))
    render(CardVerdictForm, { cardId: 12, drafts: lessonRows(), verdict: null })
    await fireEvent.click(within(group('回踩不追高')).getByRole('button', { name: '采纳' }))
    await fireEvent.click(within(group('止损按计划执行')).getByRole('button', { name: '不采纳' }))
    await fireEvent.input(within(group('回踩不追高')).getByLabelText('标题'), { target: { value: '我改过的标题' } })
    await fireEvent.input(screen.getByLabelText('我的复盘'), { target: { value: '复盘笔记' } })
    await fireEvent.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent('boom')
    // everything the user typed is still there
    expect((within(group('回踩不追高')).getByLabelText('标题') as HTMLInputElement).value).toBe('我改过的标题')
    expect((screen.getByLabelText('我的复盘') as HTMLTextAreaElement).value).toBe('复盘笔记')
    expect(within(group('回踩不追高')).getByRole('button', { name: '采纳' })).toHaveAttribute('aria-pressed', 'true')
    // retrying the same content reuses the request id, so the server can replay instead of duplicating
    await fireEvent.click(submit())
    await waitFor(() => expect(api.postCardVerdict).toHaveBeenCalledTimes(2))
    const [first, second] = vi.mocked(api.postCardVerdict).mock.calls.map(c => c[1].request_id)
    expect(second).toBe(first)
  })

  it('a changed payload after a failure gets a fresh request id', async () => {
    vi.mocked(api.postCardVerdict).mockRejectedValueOnce(new WorkbenchError('boom', 500))
    render(CardVerdictForm, { cardId: 12, drafts: lessonRows().slice(0, 1), verdict: null })
    await fireEvent.click(within(group('回踩不追高')).getByRole('button', { name: '不采纳' }))
    await fireEvent.click(submit())
    await screen.findByRole('alert')
    await fireEvent.input(screen.getByLabelText('我的复盘'), { target: { value: '补一句' } })
    await fireEvent.click(submit())
    await waitFor(() => expect(api.postCardVerdict).toHaveBeenCalledTimes(2))
    const [first, second] = vi.mocked(api.postCardVerdict).mock.calls.map(c => c[1].request_id)
    expect(second).not.toBe(first)
  })

  it('a second review is refused with the reason in Chinese', async () => {
    vi.mocked(api.postCardVerdict).mockRejectedValueOnce(new WorkbenchError('card_reviewed', 409))
    render(CardVerdictForm, { cardId: 12, drafts: [], verdict: null })
    await fireEvent.click(submit())
    expect(await screen.findByRole('alert')).toHaveTextContent('这张卡已经审定过了，要改经验请到「我的知识」改版本')
  })

  it('reviewed card shows verdict and know links', async () => {
    render(CardVerdictForm, { cardId: 12, drafts: lessonRows(), verdict: {
      note: '我的复盘笔记', created_at: '2026-10-24T02:00:00Z', lessons: [
        { draft_id: 101, action: 'approve', title: '回踩不追高', ref: 'know:21@1' },
        { draft_id: 102, action: 'dismiss', title: '止损按计划执行', ref: null },
        { draft_id: null, action: 'approve', title: '另写的一条', ref: 'know:22@1' },
      ] } })
    expect(screen.queryByRole('button', { name: '提交审定' })).toBeNull()
    expect(screen.getByText('已审定')).toBeInTheDocument()
    expect(screen.getByText('2026-10-24 10:00:00 北京')).toBeInTheDocument()
    expect(screen.getByText('我的复盘笔记')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'know:21@1' })).toHaveAttribute('href', '#knowledge/mine/21@1')
    expect(screen.getByRole('link', { name: 'know:22@1' })).toHaveAttribute('href', '#knowledge/mine/22@1')
    const dismissed = screen.getByText('止损按计划执行').closest('li')!
    expect(dismissed).toHaveTextContent('不采纳')
    expect(dismissed.className).toMatch(/text-muted/)
  })
})
