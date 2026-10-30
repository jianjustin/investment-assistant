import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/svelte'
import { metricName } from '../us-research-format'

// the trend chart needs a canvas: the stub records the option it is handed
const charts = vi.hoisted(() => [] as any[])
vi.mock('../charts/EChart.svelte', async () => {
  // @ts-ignore – stub has no declaration file; only used in tests
  const Stub = (await import('../../routes/__stub__.svelte')).default
  const Recording = (anchor: unknown, props: unknown) => { charts.push(props); return (Stub as any)(anchor, props) }
  return { default: Recording }
})

import FinancialSeries from './FinancialSeries.svelte'

const metric = (value: number | null, unit = 'USD') => ({ value, unit, basis: 'us-gaap:consolidated', method: 'reported', input_ids: [1],
  sources: [], missing_reason: value === null ? 'Missing compatible calculation input' : null })
const quarter = (n: number, metrics: Record<string, unknown> = {}) => {
  const start = `20${20 + Math.floor(n / 4)}-${String((n % 4) * 3 + 1).padStart(2, '0')}-01`
  const end = `20${20 + Math.floor(n / 4)}-${String((n % 4) * 3 + 3).padStart(2, '0')}-28`
  return { period: `${start}/${end}`, start, end, days: 90, metrics: { revenue: metric(100 + n), cfo: metric(0), fcf: metric(null), ...metrics }, ttm: { revenue: metric(400 + n) }, warnings: [] }
}
const rows = (count = 14) => Array.from({ length: count }, (_, n) => quarter(n)) as any

beforeEach(() => { charts.length = 0 })

it('shows the latest twelve actual quarters as columns, oldest first', () => {
  render(FinancialSeries, { rows: rows(14) })
  const table = screen.getByRole('table')
  const heads = [...table.querySelectorAll('thead th')]
  expect(heads).toHaveLength(1 + 12)                                   // the metric column plus twelve periods
  expect(heads[1]).toHaveTextContent(quarter(2).end)
  expect(heads[12]).toHaveTextContent(quarter(13).end)
  expect(screen.getByText(/最近 12 个实际财季/)).toBeInTheDocument()
})

it('a real zero is shown as a value and a missing value says why', () => {
  render(FinancialSeries, { rows: rows(3) })
  expect(screen.getByRole('row', { name: new RegExp(metricName('cfo')) })).toHaveTextContent('0 USD')
  const fcf = screen.getByRole('row', { name: new RegExp(metricName('fcf')) })
  expect(fcf).toHaveTextContent('—')
  expect(within(fcf).getAllByText('缺少可比计算输入').length).toBeGreaterThan(0)
})

it('the period basis and the metric group are labelled controls that change the table', async () => {
  render(FinancialSeries, { rows: rows(3) })
  expect(screen.queryByRole('row', { name: /^回购|股份回购现金支出/ })).toBeNull()
  await fireEvent.change(screen.getByLabelText('指标分组'), { target: { value: 'cash' } })
  expect(screen.getByRole('row', { name: /股份回购现金支出/ })).toBeInTheDocument()
  await fireEvent.change(screen.getByLabelText('财务期间口径'), { target: { value: 'ttm' } })
  expect(screen.getByLabelText('财务期间口径')).toHaveValue('ttm')
})

it('draws the trend only when every value shares one unit', async () => {
  render(FinancialSeries, { rows: rows(3) })
  expect(charts).toHaveLength(1)
  expect(charts[0].option.series[0].data).toEqual([100, 101, 102])
  const mixed = rows(3); mixed[1].metrics.revenue = metric(5, 'EUR')
  render(FinancialSeries, { rows: mixed })
  expect(screen.getByText('币种或单位不一致，暂不连接成趋势线。')).toBeInTheDocument()
})

it('says so when there are no quarters yet', () => {
  render(FinancialSeries, { rows: [] })
  expect(screen.getByText('暂无可比趋势数据，请核对来源覆盖。')).toBeInTheDocument()
  expect(screen.getByText('尚无可展示财季；读取本地数据不会触发来源采集。')).toBeInTheDocument()
})
