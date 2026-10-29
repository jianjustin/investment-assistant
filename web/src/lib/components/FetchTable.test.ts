import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte'
import FetchTable from './FetchTable.svelte'
import type { FetchFamily, FetchTarget } from '../runs'

const target = (name: string, over: Partial<FetchTarget> = {}): FetchTarget => ({
  target: name, ok: true, attempts: 1, error_kind: null, http_status: 200, reason: null, rows: 2, latest: '2026-10-29',
  elapsed_ms: 812, ...over,
})
const failed = (name: string, over: Partial<FetchTarget> = {}) => target(name, {
  ok: false, attempts: 3, error_kind: 'timeout', http_status: null, reason: 'timeout after 30s (3 attempts)',
  rows: null, latest: null, elapsed_ms: 100412, ...over,
})
const family = (over: Partial<FetchFamily> = {}): FetchFamily => ({
  family: 'bars', title: '日线', status: 'partial', target_count: 3, ok_count: 2,
  started_at: '2026-10-30T03:30:00Z', finished_at: '2026-10-30T03:35:12Z', scope: null,
  targets: [target('AAPL'), failed('NVDA'), target('MSFT')], failures: [{ target: 'NVDA', reason: 'timeout after 30s (3 attempts)' }],
  legacy: false, ...over,
})
afterEach(cleanup)

describe('FetchTable', () => {
  it('family header ok/target and status', () => {
    render(FetchTable, { families: [family(), family({ family: 'news', title: '资讯', status: 'success', target_count: 4, ok_count: 4, targets: [], failures: [] })] })
    const bars = screen.getByRole('region', { name: '拉取 日线' })
    expect(within(bars).getByRole('heading', { name: '日线' })).toBeInTheDocument()
    expect(bars).toHaveTextContent('部分成功')
    expect(bars).toHaveTextContent('2 / 3')
    expect(bars).toHaveTextContent('2026-10-30 11:30:00 北京 至 2026-10-30 11:35:12 北京')
    const news = screen.getByRole('region', { name: '拉取 资讯' })
    expect(news).toHaveTextContent('成功')
    expect(news).toHaveTextContent('4 / 4')
  })

  it('target columns', async () => {
    render(FetchTable, { families: [family()] })
    const headers = screen.getAllByRole('columnheader').map(h => h.textContent)
    expect(headers).toEqual(['目标', '结果', '尝试次数', '失败原因', '行数', '最新时点'])
    // 默认只展开失败目标
    let rows = screen.getAllByRole('row').slice(1)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('NVDA')
    expect(rows[0]).toHaveTextContent('3')
    // 显示全部 n 个目标：失败的排在前面，成功的带行数与最新时点
    await fireEvent.click(screen.getByRole('button', { name: '显示全部 3 个目标' }))
    rows = screen.getAllByRole('row').slice(1)
    expect(rows.map(r => within(r).getAllByRole('cell')[0].textContent)).toEqual(['NVDA', 'AAPL', 'MSFT'])
    expect(rows[1]).toHaveTextContent('成功')
    expect(rows[1]).toHaveTextContent('2026-10-29')
    await fireEvent.click(screen.getByRole('button', { name: '只看失败目标' }))
    expect(screen.getAllByRole('row').slice(1)).toHaveLength(1)
  })

  it('error_kind and reason shown verbatim', () => {
    const reason = '<b>HTTP 503</b> from https://example.test/a?x=1&y=2 after 3 attempts'
    render(FetchTable, { families: [family({
      targets: [failed('NVDA', { error_kind: 'http_5xx', http_status: 503, reason })],
      failures: [], target_count: 1, ok_count: 0, status: 'failed',
    })] })
    const row = screen.getAllByRole('row')[1]
    expect(row).toHaveTextContent('失败（http_5xx） HTTP 503')
    expect(within(row).getByText(reason)).toBeInTheDocument()     // 原文纯文本，不当 HTML
    expect(row.querySelector('b')).toBeNull()
  })

  it('all targets ok: says so and offers the full list', async () => {
    render(FetchTable, { families: [family({ status: 'success', ok_count: 2, target_count: 2, targets: [target('A'), target('B')], failures: [] })] })
    expect(screen.getByText('没有失败的目标')).toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: '显示全部 2 个目标' }))
    expect(screen.getAllByRole('row').slice(1)).toHaveLength(2)
  })

  it('duplicate target names in a legacy row do not break the list', () => {
    render(FetchTable, { families: [family({
      legacy: true, targets: undefined, target_count: 5, ok_count: 3,
      failures: [{ target: 'NVDA', reason: 'first' }, { target: 'NVDA', reason: 'second' }],
    })] })
    expect(screen.getAllByRole('row').slice(1)).toHaveLength(2)
  })

  it('says when the target list is cut short', () => {
    render(FetchTable, { families: [family({ target_count: 700, ok_count: 699 })] })
    expect(screen.getByText('共 700 个目标，明细只记录了前 3 个')).toBeInTheDocument()
  })

  it('legacy family lists failures only, with the note', () => {
    render(FetchTable, { families: [family({
      legacy: true, targets: undefined, failures: [{ target: 'NVDA', reason: 'old failure text' }], target_count: 131, ok_count: 130,
    })] })
    expect(screen.getByText('这次运行早于目标级明细（v2.8），只记录了失败的目标')).toBeInTheDocument()
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('NVDA')
    expect(rows[0]).toHaveTextContent('old failure text')
    expect(rows[0]).toHaveTextContent('失败')
    expect(screen.getByRole('region')).toHaveTextContent('130 / 131')
    expect(screen.queryByRole('button', { name: /显示全部/ })).toBeNull()
  })
})
