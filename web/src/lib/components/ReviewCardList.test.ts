import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import ReviewCardList from './ReviewCardList.svelte'
import * as api from '../api'
import { WorkbenchError } from '../workbench'
import { resetConceptIndex } from '../knowledge'
import { cardRow } from '../growth-fixtures'

const COUNTS = { to_review: 2, reviewed: 1, drafting: 1, draft_failed: 0 }
const rows = () => [
  cardRow(),
  cardRow({ id: 13, ticker: 'MU', end_kind: 'expired', exit_basis: null, end_session: '2026-10-22',
            decision_text: '否决', actual_r: null, filled: false, rule_r: null, agent_r: 0.4, flags: [], immature: [],
            status: 'drafting', headline: null }),
  cardRow({ id: 14, ticker: 'AMD', end_kind: 'position_closed', exit_basis: 'other', end_session: '2026-10-21',
            decision_text: '否决', actual_r: null, filled: true, rule_r: null, agent_r: null, flags: ['unplanned'],
            immature: [], status: 'to_review', headline: null }),
]

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  vi.spyOn(api, 'getReviewCards').mockResolvedValue({ cards: rows(), counts: COUNTS })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('ReviewCardList', () => {
  it('rows show end, decision, R, flags and status', async () => {
    render(ReviewCardList)
    const first = (await screen.findByRole('link', { name: /NVDA/ })).closest('tr')!
    expect(within(first).getByRole('link', { name: /NVDA/ })).toHaveAttribute('href', '#review/cards/12')
    expect(first).toHaveTextContent('平仓（按止损）')
    expect(first).toHaveTextContent('2026-10-23')
    expect(first).toHaveTextContent('采纳（照规则计划）')
    expect(first).toHaveTextContent('-0.80R')           // actual
    expect(first).toHaveTextContent('-1.00R')           // rule track
    expect(first).toHaveTextContent('追高')
    expect(first).toHaveTextContent('待审定')
    expect(first).toHaveTextContent('回踩买入后触及止损，追高是主因')
    const second = screen.getByRole('link', { name: /MU/ }).closest('tr')!
    expect(second).toHaveTextContent('过期未成交')
    expect(second).toHaveTextContent('未成交')          // no fill: not a number
    expect(second).not.toHaveTextContent('无 R')
    // a live buy without an R (unplanned trade) is not 未成交
    const third = screen.getByRole('link', { name: /AMD/ }).closest('tr')!
    expect(third).toHaveTextContent('无 R（计划外）')
    expect(third).not.toHaveTextContent('未成交')
    expect(second).toHaveTextContent('+0.40R')          // agent track
    // a card without a draft shows its status text where the headline would be
    expect(second.querySelector('[data-headline]')).toHaveTextContent('起草中')
  })

  it('pending flags greyed', async () => {
    render(ReviewCardList)
    const first = (await screen.findByRole('link', { name: /NVDA/ })).closest('tr')!
    const settled = within(first).getByText('追高')
    const pending = within(first).getByText('过早止盈（待定）')
    expect(settled).not.toHaveAttribute('data-pending')
    expect(settled.className).not.toMatch(/text-muted-foreground/)
    expect(pending).toHaveAttribute('data-pending', 'true')
    expect(pending.className).toMatch(/text-muted-foreground/)
  })

  it('filters by status and ticker', async () => {
    render(ReviewCardList)
    await screen.findByRole('link', { name: /NVDA/ })
    expect(api.getReviewCards).toHaveBeenLastCalledWith({})
    await fireEvent.change(screen.getByLabelText('状态'), { target: { value: 'to_review' } })
    await waitFor(() => expect(api.getReviewCards).toHaveBeenLastCalledWith({ status: 'to_review' }))
    await fireEvent.change(screen.getByLabelText('标的'), { target: { value: ' nvda ' } })
    await waitFor(() => expect(api.getReviewCards).toHaveBeenLastCalledWith({ status: 'to_review', ticker: 'NVDA' }))
  })

  it('tab badge shows to_review count', async () => {
    const oncounts = vi.fn()
    render(ReviewCardList, { oncounts })
    await screen.findByRole('link', { name: /NVDA/ })
    expect(oncounts).toHaveBeenCalledWith(COUNTS)
    expect(screen.getByText(/待审定 2/)).toBeInTheDocument()
  })

  it('says so when migration 027 has not run', async () => {
    vi.mocked(api.getReviewCards).mockRejectedValue(new WorkbenchError('迁移 027 未执行', 503))
    render(ReviewCardList)
    expect(await screen.findByText('迁移 027 未执行')).toBeInTheDocument()
  })

  it('shows an empty state', async () => {
    vi.mocked(api.getReviewCards).mockResolvedValue({ cards: [], counts: {} })
    render(ReviewCardList)
    expect(await screen.findByText('还没有复盘卡')).toBeInTheDocument()
  })
})
