import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/svelte'
import { createRawSnippet } from 'svelte'
import DataTable from './DataTable.svelte'
import type { Column, RowGroup } from './types'

type Row = { id: number; name: string; qty: number; done?: boolean }

const rows: Row[] = [
  { id: 1, name: 'AAPL', qty: 10 },
  { id: 2, name: 'MSFT', qty: 20, done: true },
  { id: 3, name: 'NVDA', qty: 30 },
]
const columns: Column<Row>[] = [
  { key: 'name', header: '标的' },
  { key: 'qty', header: '股数', align: 'num', title: '建议股数', value: (r) => r.qty },
]
const rowKey = (r: Row) => r.id

beforeEach(() => { vi.stubGlobal('matchMedia', undefined) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('DataTable names', () => {
  it('ariaLabel names the table without a visible caption', () => {
    render(DataTable<Row>, { columns, rows, rowKey, ariaLabel: '入场期计划' })
    expect(screen.getByRole('table', { name: '入场期计划' })).toBeInTheDocument()
    expect(document.querySelector('caption')).toBeNull()
  })

  it('ariaLabel names the card list too', () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: true, media: q, addEventListener: () => {}, removeEventListener: () => {} }))
    render(DataTable<Row>, { columns, rows, rowKey, cards: 'narrow', ariaLabel: '入场期计划' })
    expect(screen.getByRole('list', { name: '入场期计划' })).toBeInTheDocument()
  })

  it('grouped card lists are named by their group, the ungrouped one keeps ariaLabel', () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: true, media: q, addEventListener: () => {}, removeEventListener: () => {} }))
    const groups: RowGroup<Row>[] = [
      { key: 'a', label: '进行中', rows: [rows[0]] },
      { key: 'b', label: '已结束', rows: [rows[1]] },
    ]
    render(DataTable<Row>, { columns, groups, rowKey, cards: 'narrow', ariaLabel: '计划' })
    expect(screen.getByRole('list', { name: '进行中' })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: '已结束' })).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '计划' })).toBeNull()
  })

  it('the table scroll container keeps overflow-x-auto inside a Card at lg too', () => {
    render(DataTable<Row>, { columns, rows, rowKey })
    const box = document.querySelector('[data-slot="table-container"]')!
    expect(box.className).toContain('lg:overflow-visible')
    expect(box.className).toContain('lg:in-data-[slot=card]:overflow-x-auto')
  })

  it('expandLabel names each row button by its state; the default stays 展开详情', async () => {
    const expandable = createRawSnippet((row: () => Row) => ({ render: () => `<span>详情 ${row().name}</span>` }))
    const expandLabel = (row: Row, open: boolean) => `${open ? '收起' : '展开'} ${row.name}`
    render(DataTable<Row>, { columns, rows, rowKey, expandable, expandLabel })
    await fireEvent.click(screen.getByRole('button', { name: '展开 MSFT' }))
    expect(screen.getByRole('button', { name: '收起 MSFT' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: '展开 AAPL' })).toHaveAttribute('aria-expanded', 'false')
    cleanup()
    render(DataTable<Row>, { columns, rows, rowKey, expandable })
    expect(screen.getAllByRole('button', { name: '展开详情' })).toHaveLength(3)
  })
})

describe('DataTable', () => {
  it('renders a semantic table with header and body rows', () => {
    render(DataTable<Row>, { columns, rows, rowKey, caption: '计划' })
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '标的' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '股数' })).toHaveAttribute('title', '建议股数')
    expect(screen.getAllByRole('row')).toHaveLength(4)
    expect(screen.getByText('计划')).toBeInTheDocument()
  })

  it('num columns are right-aligned tabular', () => {
    render(DataTable<Row>, { columns, rows, rowKey })
    const head = screen.getByRole('columnheader', { name: '股数' })
    const cell = screen.getByRole('cell', { name: '20' })
    for (const el of [head, cell]) {
      expect(el.className).toMatch(/\btext-right\b/)
      expect(el.className).toMatch(/\btabular-nums\b/)
    }
    expect(screen.getByRole('cell', { name: 'MSFT' }).className).not.toMatch(/text-right/)
  })

  it('header groups span', () => {
    render(DataTable<Row>, { columns, rows, rowKey, headerGroups: [{ label: '计划', span: 1 }, { label: '数量', span: 1 }] })
    const group = screen.getByRole('columnheader', { name: '数量' })
    expect(group).toHaveAttribute('colspan', '1')
    const all = screen.getAllByRole('row')
    expect(all).toHaveLength(5)
    expect(within(all[0]).getByRole('columnheader', { name: '计划' })).toBeInTheDocument()
  })

  it('expand by click and by Enter toggles aria-expanded', async () => {
    const expandable = createRawSnippet((row: () => Row) => ({ render: () => `<span>详情 ${row().name}</span>` }))
    render(DataTable<Row>, { columns, rows, rowKey, expandable })
    const buttons = screen.getAllByRole('button', { name: /展开/ })
    expect(buttons).toHaveLength(3)
    expect(buttons[0]).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('详情 AAPL')).toBeNull()

    await fireEvent.click(buttons[0])
    expect(buttons[0]).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('详情 AAPL')).toBeInTheDocument()
    const panelId = buttons[0].getAttribute('aria-controls')!
    expect(document.getElementById(panelId)).toContainElement(screen.getByText('详情 AAPL'))

    await fireEvent.keyDown(buttons[0], { key: 'Enter' })
    expect(buttons[0]).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('详情 AAPL')).toBeNull()

    await fireEvent.keyDown(buttons[1], { key: 'Enter' })
    expect(buttons[1]).toHaveAttribute('aria-expanded', 'true')
  })

  it('muted rows', () => {
    render(DataTable<Row>, { columns, rows, rowKey, muted: (r) => !!r.done })
    const mutedRow = screen.getByRole('cell', { name: 'MSFT' }).closest('tr')!
    const normalRow = screen.getByRole('cell', { name: 'AAPL' }).closest('tr')!
    expect(mutedRow).toHaveAttribute('data-muted', 'true')
    expect(mutedRow.className).toMatch(/text-muted-foreground/)
    expect(normalRow).not.toHaveAttribute('data-muted')
  })

  it('collapsible group calls onToggle', async () => {
    const onToggle = vi.fn()
    const groups: RowGroup<Row>[] = [
      { key: 'open', label: '进行中', rows: [rows[0]] },
      { key: 'ended', label: '已结束', rows: [rows[1]], muted: true, collapsible: true, open: false, onToggle },
    ]
    render(DataTable<Row>, { columns, groups, rowKey })
    expect(screen.getByText('AAPL')).toBeInTheDocument()
    expect(screen.queryByText('MSFT')).toBeNull()
    const toggle = screen.getByRole('button', { name: /已结束/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await fireEvent.click(toggle)
    expect(onToggle).toHaveBeenCalledWith(true)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const mutedRow = screen.getByText('MSFT').closest('tr')!
    expect(mutedRow).toHaveAttribute('data-muted', 'true')
    await fireEvent.click(toggle)
    expect(onToggle).toHaveBeenLastCalledWith(false)
  })

  it('shows 50 rows then 显示更多（还有 n 行）', async () => {
    const many: Row[] = Array.from({ length: 120 }, (_, i) => ({ id: i + 1, name: `T${i + 1}`, qty: i }))
    render(DataTable<Row>, { columns, rows: many, rowKey })
    expect(screen.getAllByRole('row')).toHaveLength(51)
    const more = screen.getByRole('button', { name: '显示更多（还有 70 行）' })
    await fireEvent.click(more)
    expect(screen.getAllByRole('row')).toHaveLength(101)
    await fireEvent.click(screen.getByRole('button', { name: '显示更多（还有 20 行）' }))
    expect(screen.getAllByRole('row')).toHaveLength(121)
    expect(screen.queryByRole('button', { name: /显示更多/ })).toBeNull()
  })

  it('pageSize 0 shows everything', () => {
    const many: Row[] = Array.from({ length: 80 }, (_, i) => ({ id: i + 1, name: `T${i + 1}`, qty: i }))
    render(DataTable<Row>, { columns, rows: many, rowKey, pageSize: 0 })
    expect(screen.getAllByRole('row')).toHaveLength(81)
    expect(screen.queryByRole('button', { name: /显示更多/ })).toBeNull()
  })

  it('cards mode when narrow', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })))
    const cols: Column<Row>[] = [
      { key: 'name', header: '标的' },
      { key: 'qty', header: '股数', cardLabel: '建议股数', align: 'num' },
      { key: 'id', header: '编号', hideInCards: true },
    ]
    render(DataTable<Row>, { columns: cols, rows, rowKey, cards: 'narrow' })
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByRole('list')).toBeInTheDocument()
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(within(items[0]).getByText('标的')).toBeInTheDocument()
    expect(within(items[0]).getByText('建议股数')).toBeInTheDocument()
    expect(within(items[0]).queryByText('编号')).toBeNull()
    expect(within(items[0]).getByText('AAPL')).toBeInTheDocument()
  })

  it('desktop without matchMedia', () => {
    render(DataTable<Row>, { columns, rows, rowKey, cards: 'narrow' })
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.queryByRole('list')).toBeNull()
  })

  it('narrow with cards never keeps the table', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    render(DataTable<Row>, { columns, rows, rowKey })
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('custom cell snippets replace the value', () => {
    const cell = createRawSnippet((row: () => Row) => ({ render: () => `<b>#${row().id}</b>` }))
    render(DataTable<Row>, { columns: [{ key: 'id', header: '编号', cell }], rows, rowKey })
    expect(screen.getByText('#2')).toBeInTheDocument()
  })

  it('header groups with the same label all render', () => {
    render(DataTable<Row>, { columns, rows, rowKey, headerGroups: [{ label: '组', span: 1 }, { label: '组', span: 1 }] })
    expect(screen.getAllByRole('columnheader', { name: '组' })).toHaveLength(2)
  })

  it('show more resets when rows change', async () => {
    const make = (n: number, p: string): Row[] => Array.from({ length: n }, (_, i) => ({ id: i + 1, name: `${p}${i + 1}`, qty: i }))
    const { rerender } = render(DataTable<Row>, { columns, rows: make(120, 'A'), rowKey })
    await fireEvent.click(screen.getByRole('button', { name: '显示更多（还有 70 行）' }))
    expect(screen.getAllByRole('row')).toHaveLength(101)
    await rerender({ columns, rows: make(120, 'B'), rowKey })
    expect(screen.getAllByRole('row')).toHaveLength(51)
    expect(screen.getByRole('button', { name: '显示更多（还有 70 行）' })).toBeInTheDocument()
  })

  it('a group entirely beyond the page limit has no header yet, its rows count as hidden', async () => {
    const a: Row[] = Array.from({ length: 5 }, (_, i) => ({ id: i + 1, name: `A${i + 1}`, qty: i }))
    const b: Row[] = Array.from({ length: 4 }, (_, i) => ({ id: i + 100, name: `B${i + 1}`, qty: i }))
    const groups: RowGroup<Row>[] = [{ key: 'a', label: '甲组', rows: a }, { key: 'b', label: '乙组', rows: b }]
    render(DataTable<Row>, { columns, groups, rowKey, pageSize: 5 })
    expect(screen.getByText('甲组（5）')).toBeInTheDocument()
    expect(screen.queryByText('乙组（4）')).toBeNull()
    await fireEvent.click(screen.getByRole('button', { name: '显示更多（还有 4 行）' }))
    expect(screen.getByText('乙组（4）')).toBeInTheDocument()
    expect(screen.getByText('B4')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /显示更多/ })).toBeNull()
  })

  it('a collapsed group keeps its header even when the page is full', () => {
    const a: Row[] = Array.from({ length: 5 }, (_, i) => ({ id: i + 1, name: `A${i + 1}`, qty: i }))
    const groups: RowGroup<Row>[] = [
      { key: 'a', label: '甲组', rows: a },
      { key: 'b', label: '乙组', rows: [rows[0]], collapsible: true, open: false },
    ]
    render(DataTable<Row>, { columns, groups, rowKey, pageSize: 5 })
    expect(screen.getByRole('button', { name: /乙组/ })).toBeInTheDocument()
  })
})
