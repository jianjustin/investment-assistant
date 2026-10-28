import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import ReviewCard from './ReviewCard.svelte'
import * as api from '../api'
import * as wb from '../workbench'
import { WorkbenchError } from '../workbench'
import { resetConceptIndex } from '../knowledge'
import { cardView, discipline, draftRow, facts } from '../growth-fixtures'

const load = (view = cardView()) => { vi.mocked(api.getReviewCard).mockResolvedValue(view) }

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  vi.spyOn(api, 'getReviewCard').mockResolvedValue(cardView())
  vi.spyOn(api, 'getReasoning').mockResolvedValue({ run: { id: 'run-draft', ticker: 'NVDA', signal_date: '2026-10-14',
    mode: 'retro', agent_version: 'agent-retro-1', status: 'ok', reason: null, reason_text: null, model: 'glm',
    cutoff_at: null, started_at: null, finished_at: null, input_tokens: 1, output_tokens: 1 },
    legacy: false, version: null, review: null, steps: [], notes: [] } as any)
  vi.spyOn(wb, 'getAgentRun').mockResolvedValue({ tool_calls: [
    { seq: 2, phase: 'propose', tool: 'get_price_bars', args: { ticker: 'NVDA' }, result: { last_close: '93.80' },
      result_sha256: 'abcdef0123', called_at: '2026-10-23T22:30:00Z' }] } as any)
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('ReviewCard', () => {
  it('loads the card by id and shows the header, with 证据：未验证 and the discuss button', async () => {
    render(ReviewCard, { id: 12 })
    expect(await screen.findByRole('heading', { name: /NVDA/ })).toBeInTheDocument()
    expect(api.getReviewCard).toHaveBeenCalledWith(12)
    const header = screen.getByTestId('card-header')
    expect(header).toHaveTextContent('平仓（按止损）')
    expect(header).toHaveTextContent('2026-10-23')
    expect(header).toHaveTextContent('待审定')
    expect(within(header).getByRole('link', { name: '标的页' })).toHaveAttribute('href', '#instrument/NVDA')
    expect(within(header).getByRole('link', { name: '参考计划' })).toHaveAttribute('href', '#plan/p-rule')
    expect(within(header).getByRole('button', { name: '就此卡讨论' })).toBeInTheDocument()
    expect(screen.getByText('证据：未验证')).toBeInTheDocument()
  })

  it('facts table before narrative', async () => {
    render(ReviewCard, { id: 12 })
    const table = await screen.findByRole('table', { name: '预期与实际' })
    const narrative = screen.getByRole('region', { name: '复盘叙述' })
    expect(table.compareDocumentPosition(narrative) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('参考计划')
    expect(rows[0]).toHaveTextContent('执行的计划')
    expect(rows[0]).toHaveTextContent('规则')
    expect(rows[0]).toHaveTextContent('98.50–101.50')
    expect(rows[0]).toHaveTextContent('止损 94.00')
    expect(rows[0]).toHaveTextContent('T1 112.00')
    expect(rows[0]).toHaveTextContent('2026-10-15 至 2026-10-19')
    expect(rows[0]).toHaveTextContent('已平仓')
    expect(rows[0]).toHaveTextContent('-1.00R')
    expect(rows[0]).toHaveTextContent('入场 2026-10-15')
    expect(rows[0]).toHaveTextContent('止损 2026-10-23')
    expect(rows[1]).toHaveTextContent('Agent 第 2 版')
    expect(rows[1]).toHaveTextContent('决定时看到')
    expect(rows[1]).toHaveTextContent('最新版')
    expect(rows[1]).toHaveTextContent('T1 2026-10-20')
    // the bar summary sits with the table
    expect(screen.getByText(/日线摘要/)).toHaveTextContent('2026-10-15 至 2026-10-23')
    expect(screen.getByText(/日线摘要/)).toHaveTextContent('最高 112.40')
    // narrative: headline, each sentence with its refs, the decision review
    expect(narrative).toHaveTextContent('回踩买入后触及止损，追高是主因')
    expect(narrative).toHaveTextContent('入场区间 98.50–101.50，10-15 当天触及并成交')
    expect(narrative).toHaveTextContent('决定照规则计划，买入价略高于入场上沿')
  })

  it('fact ref scrolls to its table row', async () => {
    const seen: Element[] = []
    Element.prototype.scrollIntoView = function (this: Element) { seen.push(this) }
    render(ReviewCard, { id: 12 })
    const narrative = await screen.findByRole('region', { name: '复盘叙述' })
    await fireEvent.click(within(narrative).getAllByRole('button', { name: 'fact:plans' })[0])
    expect(seen).toHaveLength(1)
    expect(seen[0].getAttribute('data-fact')!.split(' ')).toContain('plans')
    expect(seen[0].closest('table')).toBe(screen.getByRole('table', { name: '预期与实际' }))
    await fireEvent.click(within(narrative).getAllByRole('button', { name: 'fact:discipline' })[0])
    expect(seen[1].getAttribute('data-fact')!.split(' ')).toContain('discipline')
  })

  it('call ref opens tool call', async () => {
    render(ReviewCard, { id: 12 })
    const narrative = await screen.findByRole('region', { name: '复盘叙述' })
    await fireEvent.click(within(narrative).getByRole('button', { name: 'call:2' }))
    expect(wb.getAgentRun).toHaveBeenCalledWith('run-draft')
    const call = await screen.findByRole('region', { name: '工具调用 call:2' })
    expect(call).toHaveTextContent('get_price_bars')
    expect(call).toHaveTextContent('93.80')
  })

  it('know ref links to version page', async () => {
    render(ReviewCard, { id: 12 })
    const narrative = await screen.findByRole('region', { name: '复盘叙述' })
    expect(within(narrative).getByRole('link', { name: 'know:3@1' })).toHaveAttribute('href', '#knowledge/mine/3@1')
    expect(await within(narrative).findByRole('button', { name: '概念：plan.stop' })).toBeInTheDocument()
  })

  it('tracks three lines', async () => {
    render(ReviewCard, { id: 12 })
    const tracks = await screen.findByRole('region', { name: '三条轨道' })
    const lines = within(tracks).getAllByRole('listitem')
    expect(lines).toHaveLength(3)
    expect(lines[0]).toHaveTextContent('规则')
    expect(lines[0]).toHaveTextContent('已平仓')
    expect(lines[0]).toHaveTextContent('-1.00R')
    expect(lines[1]).toHaveTextContent('Agent 第 2 版')
    expect(lines[1]).toHaveTextContent('未平仓')
    expect(lines[1]).toHaveTextContent('—')
    expect(lines[2]).toHaveTextContent('实际')
    expect(lines[2]).toHaveTextContent('-0.80R')
    expect(lines[2]).toHaveTextContent('照规则计划')
  })

  it('shows the decision, the trades and the discipline of the frozen facts', async () => {
    render(ReviewCard, { id: 12 })
    const section = await screen.findByRole('region', { name: '你的决定与纪律' })
    expect(section).toHaveTextContent('采纳（照规则计划）')
    expect(section).toHaveTextContent('趋势回踩，按规则计划')
    expect(section).toHaveTextContent('买入 10 @ 101.00')
    expect(section).toHaveTextContent('卖出 10 @ 94.00')
    expect(section).toHaveTextContent('追高')
    expect(section).toHaveTextContent('过早止盈')
    expect(section).toHaveTextContent('待定（卖出后 20 个交易日才能判定）')
  })

  it('discipline detected vs now side by side when different', async () => {
    load(cardView({ discipline_now: discipline({
      trades: [{ trade_id: 't1', flags: ['chase', 'early_take'], immature: [] }],
      totals: { chase: 1, early_take: 1, held_loser: 0, unplanned: 0, pending: 0 }, as_of: '2026-11-25' }) }))
    render(ReviewCard, { id: 12 })
    const table = await screen.findByRole('table', { name: '纪律判定' })
    const head = within(table).getAllByRole('columnheader').map(h => h.textContent!.trim())
    expect(head).toEqual(['', '检测时', '现在'])
    const early = within(table).getByRole('row', { name: /过早止盈/ })
    expect(early).toHaveTextContent('待定')
    expect(early).toHaveTextContent('成立')
  })

  it('discipline shows a single column when nothing changed', async () => {
    render(ReviewCard, { id: 12 })
    const table = await screen.findByRole('table', { name: '纪律判定' })
    expect(within(table).queryByRole('columnheader', { name: '现在' })).toBeNull()
    expect(within(table).getByRole('columnheader', { name: '检测时' })).toBeInTheDocument()
  })

  it('not filled shows 未成交，纪律四项不适用', async () => {
    load(cardView({
      card: { ...cardView().card, end_kind: 'expired' },
      facts: facts({
        subject: { ...facts().subject, end_kind: 'expired', end_text: '过期未成交', exit_basis: null },
        trades: { trades: [], segments: [], actual_r: null },
        discipline: discipline({ trades: [], totals: { chase: 0, early_take: 0, held_loser: 0, unplanned: 0, pending: 0 } }),
        tracks: { rule: { status: 'expired', status_text: '到期未成交', r: null, plan_id: 'p-rule' },
                  actual: { status: 'not_executed', status_text: '未执行', r: null, plan_id: null } },
      }),
      discipline_now: discipline({ trades: [], totals: { chase: 0, early_take: 0, held_loser: 0, unplanned: 0, pending: 0 } }),
    }))
    render(ReviewCard, { id: 12 })
    const section = await screen.findByRole('region', { name: '你的决定与纪律' })
    expect(section).toHaveTextContent('未成交，纪律四项不适用')
    expect(within(section).queryByRole('table', { name: '纪律判定' })).toBeNull()
  })

  it('draft_failed shows reason and redraft', async () => {
    load(cardView({
      status: 'draft_failed', lesson_drafts: [],
      drafts: [draftRow({ id: 1, attempt: 1, status: 'rejected', reason: 'invalid_citation', output: null }),
               draftRow({ id: 2, attempt: 2, status: 'rejected', reason: 'retro_malformed', output: null }),
               draftRow({ id: 3, attempt: 3, status: 'error', reason: 'model_error', output: null })],
    }))
    vi.spyOn(api, 'redraftCard').mockResolvedValue({ run_id: 'r9', status: 'pending' })
    vi.spyOn(api, 'pollRun').mockResolvedValue({ run_id: 'r9', status: 'done' })
    render(ReviewCard, { id: 12 })
    const box = await screen.findByRole('region', { name: '起草状态' })
    expect(box).toHaveTextContent('起草失败（可手动审定或重新起草）')
    expect(box).toHaveTextContent('模型调用失败')       // the latest attempt's reason
    await fireEvent.click(within(box).getByRole('button', { name: '重新起草' }))
    await waitFor(() => expect(api.redraftCard).toHaveBeenCalledWith(12))
    await waitFor(() => expect(api.getReviewCard).toHaveBeenCalledTimes(2))     // reloaded after the run ended
    // the verdict form is still there so the card can be reviewed without a draft
    expect(screen.getByRole('button', { name: '提交审定' })).toBeInTheDocument()
  })

  it('redraft conflict is shown in Chinese', async () => {
    load(cardView({ status: 'draft_failed', lesson_drafts: [],
      drafts: [draftRow({ status: 'rejected', reason: 'retro_malformed', output: null })] }))
    vi.spyOn(api, 'redraftCard').mockRejectedValue(new WorkbenchError('draft_exists', 409))
    render(ReviewCard, { id: 12 })
    await fireEvent.click(await screen.findByRole('button', { name: '重新起草' }))
    expect(await screen.findByText('这张卡已有成功的草稿')).toBeInTheDocument()
  })

  it('drafting card says it is being drafted and has no redraft button yet', async () => {
    load(cardView({ status: 'drafting', drafts: [], lesson_drafts: [] }))
    render(ReviewCard, { id: 12 })
    expect(await screen.findByText('起草中')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新起草' })).toBeNull()
  })

  it('evidence 未验证 always visible', async () => {
    for (const view of [cardView(), cardView({ status: 'draft_failed', drafts: [], lesson_drafts: [] }),
                        cardView({ status: 'reviewed', verdict: { note: '', created_at: '2026-10-24T00:00:00Z', lessons: [] } })]) {
      load(view)
      const { unmount } = render(ReviewCard, { id: 12 })
      await screen.findByRole('heading', { name: /NVDA/ })
      expect(screen.getByText('证据：未验证')).toBeInTheDocument()
      unmount()
    }
  })

  it('看起草过程 opens the reasoning view of the draft run, lazily', async () => {
    render(ReviewCard, { id: 12 })
    const button = await screen.findByRole('button', { name: '看起草过程' })
    expect(api.getReasoning).not.toHaveBeenCalled()
    await fireEvent.click(button)
    await waitFor(() => expect(api.getReasoning).toHaveBeenCalledWith('run-draft'))
  })

  it('lists the discussions of the card', async () => {
    load(cardView({ discussions: [{ id: 5, created_at: '2026-10-24T10:00:00Z', turn_count: 3,
                                     first_question: '为什么这个止损放在这里而不是更靠下一点或者更靠上一点呢，我想了解整个推导过程用到的每一个输入，包括参考的是前低还是别的' }] }))
    render(ReviewCard, { id: 12 })
    const link = await screen.findByRole('link', { name: /为什么这个止损放在这里/ })
    expect(link).toHaveAttribute('href', '#discuss/5')
    expect(link).toHaveTextContent('3 轮')
    expect(link.textContent).not.toContain('包括参考的是前低')       // first 40 characters only
  })

  it('shows the load failure instead of an empty page', async () => {
    vi.mocked(api.getReviewCard).mockRejectedValue(new WorkbenchError('迁移 027 未执行', 503))
    render(ReviewCard, { id: 12 })
    expect(await screen.findByText('迁移 027 未执行')).toBeInTheDocument()
  })
})
