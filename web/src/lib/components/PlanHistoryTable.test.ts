import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/svelte'
import PlanHistoryTable from './PlanHistoryTable.svelte'
import type { HistoryChain, HistoryRow } from '../workbench'

const rows = (): HistoryRow[] => [
  { kind: 'chain_open', at: '2026-10-21T22:30:00Z', session: '2026-10-21', chain_signal_date: '2026-10-21',
    text: '新开链 MU·10-21：规则 趋势回踩修复；此前没有计划链' },
  { kind: 'version', at: '2026-10-21T22:31:00Z', session: '2026-10-21', chain_signal_date: '2026-10-21', version_no: 0,
    levels: { entry_low: '90.00', entry_high: '92.00', stop: '86.00', target1: '100.00' },
    validity: { valid_from: '2026-10-22', valid_until: '2026-10-26' }, diff: null, changes: null, text: '第 0 版：入场 90.00–92.00' },
  { kind: 'version', at: '2026-10-22T22:40:00Z', session: '2026-10-22', chain_signal_date: '2026-10-21', version_no: 1,
    levels: { entry_low: '90.00', entry_high: '92.00', stop: '87.00', target1: '100.00' },
    diff: [{ field: 'stop', before: '86.00', after: '87.00' }, { field: 'entry_type', before: 'zone_limit', after: 'next_open' }],
    changes: [{ field: 'stop', text: '止损上移到前低' }], signals_fired: ['t1_touched'], decided_by: 'agent', reason: 'T1 已触及',
    text: '第 1 版' },
  { kind: 'retrigger', at: '2026-10-23T22:30:00Z', session: '2026-10-23', chain_signal_date: '2026-10-21',
    text: '10-23 再次触发（趋势回踩修复），并入本链' },
  { kind: 'chain_end', at: '2026-10-24T22:30:00Z', session: '2026-10-24', chain_signal_date: '2026-10-21',
    end: { kind: 'expired' }, text: '已过期未执行（2026-10-24）' },
  { kind: 'chain_open', at: '2026-10-28T22:30:00Z', session: '2026-10-28', chain_signal_date: '2026-10-28',
    text: '新开链 MU·10-28：规则 放量突破；上一条链 MU·10-21 已于 10-24 过期未执行，间隔 2 个交易日' },
  { kind: 'version', at: '2026-10-28T22:31:00Z', session: '2026-10-28', chain_signal_date: '2026-10-28', version_no: 0,
    levels: { entry_low: '95.10', entry_high: '97.30', stop: '91.40', target1: '104.70' }, text: '第 0 版' },
  { kind: 'review', at: '2026-10-29T22:40:00Z', session: '2026-10-29', chain_signal_date: '2026-10-28',
    decided_by: 'host', reason: '无新信号', text: '10-29 维持（系统规则）：无新信号' },
]
const chains = (): HistoryChain[] => [
  { signal_date: '2026-10-21', state: 'expired', versions: 2, ended_at: '2026-10-24', end: { kind: 'expired' } },
  { signal_date: '2026-10-28', state: 'entry', versions: 1, ended_at: null, end: null },
]

afterEach(() => vi.restoreAllMocks())

describe('PlanHistoryTable', () => {
  it('renders two chains separated, each opened by a chain_open row and closed by chain_end', () => {
    render(PlanHistoryTable, { rows: rows(), chains: chains(), ticker: 'MU' })
    const table = screen.getByRole('table', { name: '计划历史' })
    const bodies = table.querySelectorAll('tbody')
    expect(bodies).toHaveLength(2)
    expect(bodies[0].getAttribute('data-chain')).toBe('2026-10-21')
    expect(bodies[0].className).not.toContain('border-t-4')
    expect(bodies[1].className).toContain('border-t-4')              // the divider between chains
    const first = [...bodies[0].querySelectorAll('tr')]
    expect(first[0].getAttribute('data-kind')).toBe('chain_open')
    expect(first[0].className).toContain('bg-surface-2')             // grey
    expect(first.at(-1)!.getAttribute('data-kind')).toBe('chain_end')
    expect(first.at(-1)).toHaveTextContent('已过期未执行（2026-10-24）')
  })

  it('writes why the chain opened again', () => {
    render(PlanHistoryTable, { rows: rows(), chains: chains(), ticker: 'MU' })
    expect(screen.getByText(/新开链 MU·10-28：规则 放量突破；上一条链 MU·10-21 已于 10-24 过期未执行，间隔 2 个交易日/)).toBeInTheDocument()
  })

  it('shows levels, host diff item by item, the model change text and the fired signals', () => {
    render(PlanHistoryTable, { rows: rows(), chains: chains(), ticker: 'MU' })
    const v1 = screen.getByRole('table', { name: '计划历史' }).querySelectorAll('tbody')[0].querySelectorAll('tr')[2]
    expect(v1).toHaveTextContent('MU·10-21 第 1 版')
    expect(v1).toHaveTextContent('入场 90.00–92.00 · 止损 87.00 · T1 100.00')
    expect(v1).toHaveTextContent('止损 86.00 → 87.00')
    expect(v1).toHaveTextContent('入场类型 区间限价 → 次日开盘')
    expect(v1).toHaveTextContent('止损上移到前低')
    expect(v1).toHaveTextContent('触发：触及 T1')
    expect(v1).toHaveTextContent('Agent：T1 已触及')
    const v0 = screen.getByRole('table', { name: '计划历史' }).querySelectorAll('tbody')[0].querySelectorAll('tr')[1]
    expect(v0).toHaveTextContent('有效期 2026-10-22 至 2026-10-26')
  })

  it('keeps a merged unit as a row inside its chain', () => {
    render(PlanHistoryTable, { rows: rows(), chains: chains(), ticker: 'MU' })
    const body = screen.getByRole('table', { name: '计划历史' }).querySelectorAll('tbody')[0]
    expect(body.querySelector('tr[data-kind="retrigger"]')).toHaveTextContent('10-23 再次触发（趋势回踩修复），并入本链')
  })

  it('shows review rows (switch on) with the system or Agent verdict', () => {
    render(PlanHistoryTable, { rows: rows(), chains: chains(), ticker: 'MU', includeReviews: true })
    expect(screen.getByRole('checkbox', { name: '显示每日维持的复查' })).toBeChecked()
    expect(screen.getByRole('table', { name: '计划历史' }).querySelector('tr[data-kind="review"]')).toHaveTextContent('系统规则：无新信号')
  })

  it('both switches are requests: toggling calls back with the full state', async () => {
    const onToggle = vi.fn()
    render(PlanHistoryTable, { rows: rows(), chains: chains(), ticker: 'MU', onToggle })
    const reviews = screen.getByRole('checkbox', { name: '显示每日维持的复查' })
    const baselines = screen.getByRole('checkbox', { name: '显示规则基线' })
    expect(reviews).not.toBeChecked()
    expect(baselines).not.toBeChecked()
    await fireEvent.click(reviews)
    expect(onToggle).toHaveBeenLastCalledWith({ include_reviews: true, include_baselines: false })
    await fireEvent.click(baselines)
    expect(onToggle).toHaveBeenLastCalledWith({ include_reviews: true, include_baselines: true })
  })

  it('says so when there is no history', () => {
    render(PlanHistoryTable, { rows: [], chains: [], ticker: 'MU' })
    expect(screen.getByText('该标的还没有计划历史')).toBeInTheDocument()
    expect(within(document.body).queryByRole('table', { name: '计划历史' })).toBeNull()
  })

  it('survives identical diff or change texts in one row (keyed by position)', () => {
    const dup = { kind: 'version', at: '2026-10-22T22:40:00Z', session: '2026-10-22', chain_signal_date: '2026-10-21', version_no: 1,
      diff: [{ field: 'stop', before: '86.00', after: '87.00' }, { field: 'stop', before: '86.00', after: '87.00' }],
      changes: ['止损上移', '止损上移'], text: '第 1 版' } as HistoryRow
    render(PlanHistoryTable, { rows: [dup], chains: [], ticker: 'MU' })
    expect(screen.getAllByText('止损 86.00 → 87.00')).toHaveLength(2)
    expect(screen.getAllByText('止损上移')).toHaveLength(2)
  })

  it('keeps rows without a chain at their place in time (baselines between two chains)', () => {
    const base = rows()
    const baseline = { kind: 'version', at: '2026-10-25T22:40:00Z', session: '2026-10-25', chain_signal_date: null,
      version_no: null, levels: { entry_low: '88.00', entry_high: '90.00', stop: '84.00', target1: '96.00' }, text: '规则基线 plan-2' } as HistoryRow
    const ordered = [...base.slice(0, 5), baseline, ...base.slice(5)]
    render(PlanHistoryTable, { rows: ordered, chains: chains(), ticker: 'MU', includeBaselines: true })
    const bodies = [...screen.getByRole('table', { name: '计划历史' }).querySelectorAll('tbody')]
    expect(bodies.map(b => b.getAttribute('data-chain'))).toEqual(['2026-10-21', '', '2026-10-28'])
    expect(bodies[1]).toHaveTextContent('88.00–90.00')
    expect(bodies[0]).not.toHaveTextContent('88.00–90.00')
    expect(bodies[2]).not.toHaveTextContent('88.00–90.00')
  })
})

