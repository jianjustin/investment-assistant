import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import Discussion from './Discussion.svelte'
import * as api from '../api'
import { WorkbenchError } from '../workbench'
import { DISCUSS_POLL_MS } from '../growth'
import { resetConceptIndex } from '../knowledge'
import {
  USER_INPUT_REQUEST_ID_VECTOR as VECTOR, answerTurn, discussion, entry, knowledgeDraft, userTurn,
} from '../growth-fixtures'

const calls = () => vi.mocked(api.getDiscussion).mock.calls.length
const ask = async (text: string) => {
  await fireEvent.input(screen.getByLabelText('你的问题'), { target: { value: text } })
  await fireEvent.click(screen.getByRole('button', { name: '提问' }))
}
const pending = () => discussion([userTurn({ state: 'pending' })])

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  vi.spyOn(api, 'getDiscussion').mockResolvedValue(discussion())
  vi.spyOn(api, 'getReasoning').mockResolvedValue({ run: { id: 'run-answer', ticker: 'NVDA', signal_date: '2026-10-22',
    mode: 'discuss', agent_version: 'agent-discuss-1', status: 'ok', reason: null, reason_text: null, model: 'glm',
    cutoff_at: null, started_at: null, finished_at: null, input_tokens: 1, output_tokens: 1 },
    legacy: false, version: null, review: null, steps: [], notes: [] } as any)
})
afterEach(() => { vi.useRealTimers(); cleanup(); vi.restoreAllMocks() })

describe('Discussion · page', () => {
  it('shows the plan context with links back, then each turn in order', async () => {
    render(Discussion, { id: 5 })
    const header = await screen.findByTestId('discussion-header')
    expect(api.getDiscussion).toHaveBeenCalledWith(5)
    expect(header).toHaveTextContent('NVDA')
    expect(header).toHaveTextContent('第 2 版')
    expect(header).toHaveTextContent('生成于 2026-10-27 21:00:00 北京')
    expect(header).toHaveTextContent('截止 2026-10-27 20:59:00 北京')
    expect(within(header).getByRole('link', { name: '回到计划页' })).toHaveAttribute('href', '#plan/p-agent')
    const turns = screen.getAllByTestId('turn')
    expect(turns).toHaveLength(2)
    expect(turns[0]).toHaveTextContent('这个止损怎么来的？')
    expect(turns[1]).toHaveTextContent('止损 = 参考价减 2 倍 ATR14。')
    expect(turns[1]).toHaveTextContent('截止 2026-10-28 18:00:00 北京')       // answers carry the cutoff they read under
  })

  it('a card discussion shows the end kind and links back to the card', async () => {
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([], {
      context_kind: 'card', plan_id: null, card_id: 12,
      context: { end_kind: 'position_closed', end_session: '2026-10-23' } }))
    render(Discussion, { id: 5 })
    const header = await screen.findByTestId('discussion-header')
    expect(header).toHaveTextContent('平仓')
    expect(header).toHaveTextContent('2026-10-23')
    expect(within(header).getByRole('link', { name: '回到复盘卡' })).toHaveAttribute('href', '#review/cards/12')
  })

  it('draft in answer links to review', async () => {
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([userTurn(), answerTurn({ knowledge_draft: knowledgeDraft() })]))
    render(Discussion, { id: 5 })
    const draft = await screen.findByRole('region', { name: '经验草稿' })
    expect(draft).toHaveTextContent('止损别拖')
    expect(draft).toHaveTextContent('触及止损次日就卖。')
    expect(draft).toHaveTextContent('持仓期')
    expect(draft).toHaveTextContent('财报前后除外')
    expect(within(draft).getByRole('link', { name: '去审定' })).toHaveAttribute('href', '#knowledge/mine/drafts')
  })

  it('a settled draft shows its outcome instead of the review link', async () => {
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([userTurn(), answerTurn({
      knowledge_draft: knowledgeDraft({ verdict: { action: 'approve', ref: 'know:31@1' } }) })]))
    render(Discussion, { id: 5 })
    const draft = await screen.findByRole('region', { name: '经验草稿' })
    expect(within(draft).getByRole('link', { name: 'know:31@1' })).toHaveAttribute('href', '#knowledge/mine/31@1')
    expect(within(draft).queryByRole('link', { name: '去审定' })).toBeNull()
  })

  it('notes a dropped draft', async () => {
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([userTurn(), answerTurn({ detail: { draft_dropped: 'lesson_invalid' } })]))
    render(Discussion, { id: 5 })
    expect(await screen.findByText('经验草稿未通过校验，已丢弃：教训草稿缺适用范围、反例或挂靠无效')).toBeInTheDocument()
  })

  it('rejected answer folded behind 仍要看原文（未通过校验）', async () => {
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([userTurn(), answerTurn({
      status: 'rejected', reason: 'invalid_citation', body: '被拒绝的原文', refs: [] })]))
    render(Discussion, { id: 5 })
    const turn = (await screen.findAllByTestId('turn'))[1]
    expect(turn).toHaveTextContent('这条回答没有通过校验：引用无效已作废')
    const summary = within(turn).getByText('仍要看原文（未通过校验）')
    const details = summary.closest('details')!
    expect(details).not.toHaveAttribute('open')
    expect(details).toContainElement(screen.getByText('被拒绝的原文'))
    // the folded text is not shown as the answer
    expect(turn.querySelector('[data-answer]')).toBeNull()
  })

  it('error and skipped answers show their reason, not a body', async () => {
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([userTurn(), answerTurn({
      status: 'error', reason: 'quota_exhausted', body: '', refs: [] })]))
    render(Discussion, { id: 5 })
    expect(await screen.findByText('这一轮没有得到回答：额度用尽')).toBeInTheDocument()
  })

  it('看这次回答读了什么 opens the reasoning view of the answer run, lazily', async () => {
    render(Discussion, { id: 5 })
    const button = await screen.findByRole('button', { name: '看这次回答读了什么' })
    expect(api.getReasoning).not.toHaveBeenCalled()
    await fireEvent.click(button)
    await waitFor(() => expect(api.getReasoning).toHaveBeenCalledWith('run-answer'))
  })

  it('answer refs are clickable by kind', async () => {
    render(Discussion, { id: 5 })
    const turn = (await screen.findAllByTestId('turn'))[1]
    expect(within(turn).getByRole('button', { name: 'call:1' })).toBeInTheDocument()
    expect(await within(turn).findByRole('button', { name: '概念：plan.stop' })).toBeInTheDocument()
  })

  it('load failure is shown', async () => {
    vi.mocked(api.getDiscussion).mockRejectedValue(new WorkbenchError('迁移 027 未执行', 503))
    render(Discussion, { id: 5 })
    expect(await screen.findByText(/讨论加载失败.*迁移 027 未执行/)).toBeInTheDocument()
  })
})

describe('Discussion · unmounted while a read is in flight', () => {
  it('a read that resolves after unmount arms no timer', async () => {
    vi.useFakeTimers()
    let resolve!: (d: ReturnType<typeof pending>) => void
    vi.mocked(api.getDiscussion).mockReturnValueOnce(new Promise(r => { resolve = r }))
    const view = render(Discussion, { id: 5 })
    await vi.advanceTimersByTimeAsync(0)
    expect(calls()).toBe(1)
    view.unmount()
    resolve(pending())
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(calls()).toBe(1)
  })

  it('a poll tick that resolves after unmount does not schedule the next one', async () => {
    vi.useFakeTimers()
    let resolve!: (d: ReturnType<typeof pending>) => void
    vi.mocked(api.getDiscussion).mockResolvedValueOnce(pending())
      .mockReturnValueOnce(new Promise(r => { resolve = r })).mockResolvedValue(pending())
    const view = render(Discussion, { id: 5 })
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(2000)
    expect(calls()).toBe(2)                         // the tick's read is in flight
    view.unmount()
    resolve(pending())
    await vi.advanceTimersByTimeAsync(10_000)
    expect(calls()).toBe(2)
  })

  it('the read after asking, resolving after unmount, arms no timer', async () => {
    vi.useFakeTimers()
    let resolve!: (d: ReturnType<typeof pending>) => void
    vi.spyOn(api, 'postDiscussionTurn').mockResolvedValue({ status: 'created' } as any)
    vi.mocked(api.getDiscussion).mockResolvedValueOnce(discussion())
      .mockReturnValueOnce(new Promise(r => { resolve = r })).mockResolvedValue(pending())
    const view = render(Discussion, { id: 5 })
    await vi.advanceTimersByTimeAsync(0)
    await ask('再问一个')
    await vi.advanceTimersByTimeAsync(0)
    expect(calls()).toBe(2)
    view.unmount()
    resolve(pending())
    await vi.advanceTimersByTimeAsync(10_000)
    expect(calls()).toBe(2)
  })
})

describe('Discussion · asking and polling', () => {
  it('polls every 2s until reply', async () => {
    vi.useFakeTimers()
    vi.mocked(api.getDiscussion).mockResolvedValueOnce(pending()).mockResolvedValueOnce(pending())
      .mockResolvedValue(discussion())
    render(Discussion, { id: 5 })
    await vi.advanceTimersByTimeAsync(0)
    expect(calls()).toBe(1)
    expect(screen.getByText('回答中…')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(1999)
    expect(calls()).toBe(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(calls()).toBe(2)
    expect(screen.getByText('回答中…')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(2000)
    expect(calls()).toBe(3)
    expect(screen.getByText(/止损 = 参考价减 2 倍 ATR14/)).toBeInTheDocument()
    expect(screen.queryByText('回答中…')).toBeNull()
    await vi.advanceTimersByTimeAsync(30_000)                 // answered: it stops
    expect(calls()).toBe(3)
  })

  it('timeout text 回答仍在后台生成，稍后刷新查看', async () => {
    vi.useFakeTimers()
    vi.mocked(api.getDiscussion).mockResolvedValue(pending())
    render(Discussion, { id: 5 })
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(DISCUSS_POLL_MS - 4000)
    expect(screen.queryByText('回答仍在后台生成，稍后刷新查看')).toBeNull()
    await vi.advanceTimersByTimeAsync(6000)
    expect(screen.getByText('回答仍在后台生成，稍后刷新查看')).toBeInTheDocument()
    const n = calls()
    expect(n).toBeGreaterThan(250)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(calls()).toBe(n)                                    // timed out: it stops
  })

  it('interrupted text', async () => {
    vi.useFakeTimers()
    vi.mocked(api.getDiscussion).mockResolvedValueOnce(pending())
      .mockResolvedValue(discussion([userTurn({ state: 'interrupted' })]))
    render(Discussion, { id: 5 })
    await vi.advanceTimersByTimeAsync(0)
    expect(screen.queryByText('没有收到回答（服务可能重启过），可以再问一次')).toBeNull()
    await vi.advanceTimersByTimeAsync(2000)
    expect(screen.getByText('没有收到回答（服务可能重启过），可以再问一次')).toBeInTheDocument()
    expect(screen.queryByText('回答中…')).toBeNull()
    const n = calls()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(calls()).toBe(n)                                    // interrupted: it stops
  })

  it('an interrupted turn on load does not start polling and does not block asking again', async () => {
    vi.useFakeTimers()
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([userTurn({ state: 'interrupted' })]))
    render(Discussion, { id: 5 })
    await vi.advanceTimersByTimeAsync(0)
    expect(screen.getByText('没有收到回答（服务可能重启过），可以再问一次')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(calls()).toBe(1)
    expect(screen.getByRole('button', { name: '提问' })).toBeInTheDocument()
  })

  it('a replayed answer (202 status replayed) is handled like a fresh submit: reload and poll', async () => {
    vi.useFakeTimers()
    const post = vi.spyOn(api, 'postDiscussionTurn').mockResolvedValue({ turn_id: 9, run_id: 'r1', status: 'replayed' })
    vi.mocked(api.getDiscussion).mockResolvedValueOnce(discussion([]))
      .mockResolvedValueOnce(discussion([userTurn({ state: 'pending' })]))
      .mockResolvedValue(discussion())
    render(Discussion, { id: 5 })
    await vi.advanceTimersByTimeAsync(0)
    await ask('这个止损怎么来的？')
    await vi.advanceTimersByTimeAsync(0)
    expect(post).toHaveBeenCalledTimes(1)
    expect(calls()).toBe(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(screen.getByText(/止损 = 参考价减 2 倍 ATR14/)).toBeInTheDocument()
  })

  it('asking posts request_id and body, then reloads and polls', async () => {
    vi.useFakeTimers()
    const post = vi.spyOn(api, 'postDiscussionTurn').mockResolvedValue({ turn_id: 9, run_id: 'r1', status: 'pending' })
    vi.mocked(api.getDiscussion).mockResolvedValueOnce(discussion([]))
      .mockResolvedValueOnce(discussion([userTurn({ state: 'pending' })]))
      .mockResolvedValue(discussion())
    render(Discussion, { id: 5 })
    await vi.advanceTimersByTimeAsync(0)
    await ask('  这个止损怎么来的？  ')
    await vi.advanceTimersByTimeAsync(0)
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][0]).toBe(5)
    expect(post.mock.calls[0][1]).toEqual({ request_id: expect.stringMatching(/^[0-9a-f-]{36}$/), body: '这个止损怎么来的？' })
    expect(calls()).toBe(2)                                     // reloaded right away to show the turn
    expect((screen.getByLabelText('你的问题') as HTMLTextAreaElement).value).toBe('')
    await vi.advanceTimersByTimeAsync(2000)
    expect(screen.getByText(/止损 = 参考价减 2 倍 ATR14/)).toBeInTheDocument()
  })

  it('409 discussion_busy message', async () => {
    vi.spyOn(api, 'postDiscussionTurn').mockRejectedValue(new WorkbenchError('discussion_busy', 409))
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([]))
    render(Discussion, { id: 5 })
    await screen.findByLabelText('你的问题')
    await ask('再问一个')
    expect(await screen.findByRole('alert')).toHaveTextContent('上一个问题还在回答')
    expect((screen.getByLabelText('你的问题') as HTMLTextAreaElement).value).toBe('再问一个')   // input kept
    expect(calls()).toBe(1)                                                                   // nothing to poll
  })

  it('other refusals read in Chinese, and a retry keeps the request id', async () => {
    const post = vi.spyOn(api, 'postDiscussionTurn')
      .mockRejectedValueOnce(new WorkbenchError('agent_unavailable: quota_exhausted', 409))
      .mockRejectedValueOnce(new WorkbenchError('token_budget', 409))
      .mockResolvedValue({ turn_id: 9, run_id: 'r1', status: 'pending' })
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([]))
    render(Discussion, { id: 5 })
    await screen.findByLabelText('你的问题')
    await ask('问题')
    expect(await screen.findByRole('alert')).toHaveTextContent('Agent 不可用：额度用尽')
    await fireEvent.click(screen.getByRole('button', { name: '提问' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('超出 token 上限'))
    await fireEvent.click(screen.getByRole('button', { name: '提问' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(3))
    expect(new Set(post.mock.calls.map(c => c[1].request_id)).size).toBe(1)
  })

  it('does not accept an empty or over-long question', async () => {
    const post = vi.spyOn(api, 'postDiscussionTurn')
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([]))
    render(Discussion, { id: 5 })
    await screen.findByLabelText('你的问题')
    await fireEvent.click(screen.getByRole('button', { name: '提问' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('问题不能为空')
    await ask('x'.repeat(4001))
    expect(await screen.findByRole('alert')).toHaveTextContent('问题最多 4000 字')
    expect(post).not.toHaveBeenCalled()
  })

  it('save as user input posts derived request_id', async () => {
    const post = vi.spyOn(api, 'postUserInput').mockResolvedValue({ status: 'created', record: { id: 12 } } as any)
    render(Discussion, { id: 5 })
    const turn = (await screen.findAllByTestId('turn'))[0]
    await fireEvent.click(within(turn).getByRole('button', { name: '存为补充信息' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0]).toEqual({
      request_id: VECTOR.user_input_request_id, ticker: 'NVDA', signal_date: '2026-10-22', kind: 'judgment',
      body: '这个止损怎么来的？' })
    expect(await within(turn).findByText('user:12')).toBeInTheDocument()
    expect(within(turn).queryByRole('button', { name: '存为补充信息' })).toBeNull()
  })

  it('the saved kind can be chosen, and a turn already saved shows its user:<id>', async () => {
    const post = vi.spyOn(api, 'postUserInput').mockResolvedValue({ status: 'replayed', record: { id: 12 } } as any)
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([userTurn(), answerTurn(),
      userTurn({ id: 10, seq: 3, body: '第二问', request_id: 'aaaaaaaa-0000-4000-8000-000000000002', user_input_id: 7 })]))
    render(Discussion, { id: 5 })
    const turns = await screen.findAllByTestId('turn')
    expect(turns[2]).toHaveTextContent('user:7')
    expect(within(turns[2]).queryByRole('button', { name: '存为补充信息' })).toBeNull()
    await fireEvent.change(within(turns[0]).getByLabelText('补充信息类型'), { target: { value: 'research' } })
    await fireEvent.click(within(turns[0]).getByRole('button', { name: '存为补充信息' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0]).toMatchObject({ kind: 'research', request_id: VECTOR.user_input_request_id })
  })

  it('a failed save says why and can be retried', async () => {
    vi.spyOn(api, 'postUserInput').mockRejectedValueOnce(new WorkbenchError('迁移 026 未执行', 503))
      .mockResolvedValue({ status: 'created', record: { id: 13 } } as any)
    render(Discussion, { id: 5 })
    const turn = (await screen.findAllByTestId('turn'))[0]
    await fireEvent.click(within(turn).getByRole('button', { name: '存为补充信息' }))
    expect(await within(turn).findByRole('alert')).toHaveTextContent('迁移 026 未执行')
    await fireEvent.click(within(turn).getByRole('button', { name: '存为补充信息' }))
    expect(await within(turn).findByText('user:13')).toBeInTheDocument()
  })

  it('rewrite attachment picker', async () => {
    vi.spyOn(api, 'getMyKnowledge').mockResolvedValue({ items: [entry()] })
    vi.spyOn(api, 'getKnowledgeDrafts').mockResolvedValue({ drafts: [knowledgeDraft()] })
    const post = vi.spyOn(api, 'postDiscussionTurn').mockResolvedValue({ turn_id: 9, run_id: 'r1', status: 'pending' })
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([]))
    render(Discussion, { id: 5 })
    await screen.findByLabelText('你的问题')
    await fireEvent.click(screen.getByRole('button', { name: '就这条改写' }))
    const picker = await screen.findByRole('region', { name: '选一条作为附件' })
    expect(api.getMyKnowledge).toHaveBeenCalledWith({ status: 'active' })
    expect(api.getKnowledgeDrafts).toHaveBeenCalledWith('open')
    await fireEvent.click(within(picker).getByRole('button', { name: '回踩别追（第 2 版）' }))
    expect(screen.queryByRole('region', { name: '选一条作为附件' })).toBeNull()
    expect(screen.getByText('附件：回踩别追（第 2 版）')).toBeInTheDocument()
    await ask('把适用范围写窄一点')
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][1]).toMatchObject({ body: '把适用范围写窄一点', attachment: { kind: 'knowledge', id: 3, version: 2 } })
  })

  it('a draft can be the attachment too, and the attachment can be removed', async () => {
    vi.spyOn(api, 'getMyKnowledge').mockResolvedValue({ items: [] })
    vi.spyOn(api, 'getKnowledgeDrafts').mockResolvedValue({ drafts: [knowledgeDraft()] })
    const post = vi.spyOn(api, 'postDiscussionTurn').mockResolvedValue({ turn_id: 9, run_id: 'r1', status: 'pending' })
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([]))
    render(Discussion, { id: 5 })
    await screen.findByLabelText('你的问题')
    await fireEvent.click(screen.getByRole('button', { name: '就这条改写' }))
    await fireEvent.click(await screen.findByRole('button', { name: '草稿：止损别拖' }))
    expect(screen.getByText('附件：草稿 止损别拖')).toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: '移除附件' }))
    expect(screen.queryByText(/附件：/)).toBeNull()
    await fireEvent.click(screen.getByRole('button', { name: '就这条改写' }))
    await fireEvent.click(await screen.findByRole('button', { name: '草稿：止损别拖' }))
    await ask('改写')
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][1].attachment).toEqual({ kind: 'draft', id: 201 })
  })

  it('shows the attachment on the turn that carried it', async () => {
    vi.mocked(api.getDiscussion).mockResolvedValue(discussion([userTurn({
      attachment: { kind: 'knowledge', id: 3, version: 2, title: '回踩别追' } }), answerTurn()]))
    render(Discussion, { id: 5 })
    const turn = (await screen.findAllByTestId('turn'))[0]
    expect(turn).toHaveTextContent('附件：回踩别追（第 2 版）')
  })
})
