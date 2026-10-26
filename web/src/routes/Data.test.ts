import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import Data from './Data.svelte'
import * as api from '../lib/api'
import { fmtBeijing } from '../lib/format'
import type { DataOverview, FamilyCard, FamilyDetail, FamilyId, FamilyJob, FetchRun } from '../lib/data-families'

const EVIDENCE = '这里只展示采集事实。所有规则都未经验证（Phase 0 Gate HOLD）：数据完整不代表信号有效。'
const TITLES: Record<FamilyId, string> = {
  bars: '日线', sec_filings: 'SEC 申报', news: '资讯', atr: 'ATR', fred: 'FRED 利差', universe: '纳指 100 范围',
}

const job = (overrides: Partial<FamilyJob> = {}): FamilyJob => ({
  name: 'workbench', enabled: true, next_run_at: '2026-10-23T06:30:00+00:00', ...overrides,
})

const card = (id: FamilyId, overrides: Partial<FamilyCard> = {}): FamilyCard => ({
  id, title: TITLES[id], purpose: `用途-${id}`,
  kind: id === 'atr' ? 'derived' : id === 'universe' ? 'manual' : 'fetched',
  fetch_via: id === 'atr' ? 'bars' : null,
  per_ticker: ['bars', 'sec_filings', 'news'].includes(id),
  job: job(), coverage: { targets: 10, covered: 10, lagging: [] },
  latest_at: '2026-10-22', last_run: null, last_success_at: null,
  evidence: id === 'atr' ? EVIDENCE + ' `plan-1` 的计算输入，规则 `gate_hold`' : EVIDENCE, notes: [],
  ...overrides,
})

const six = (overrides: Partial<Record<FamilyId, Partial<FamilyCard>>> = {}) =>
  (Object.keys(TITLES) as FamilyId[]).map(id => card(id, overrides[id] ?? {}))

const overview = (families: FamilyCard[], extra: Partial<DataOverview> = {}): DataOverview => ({
  session: '2026-10-22', evidence: EVIDENCE, fetch_runs_ready: true, families, ...extra,
})

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getDataFamilies').mockResolvedValue(overview(six()))
  vi.spyOn(api, 'getDataFamily').mockResolvedValue(detail())
  vi.spyOn(api, 'browseData').mockResolvedValue({ family: 'bars', key: 'MU', has_data: false, rows: [] })
  vi.spyOn(api, 'fetchDataFamily').mockResolvedValue({ run_id: 'r1', status: 'pending' })
  vi.spyOn(api, 'pollRun').mockResolvedValue({ run_id: 'r1', status: 'done', result: { status: 'success' } })
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('Data 总览', () => {
  it('renders six cards with evidence banner', async () => {
    render(Data)
    expect(await screen.findByLabelText('证据说明')).toHaveTextContent(EVIDENCE)
    expect(screen.getAllByRole('article')).toHaveLength(6)
    for (const title of Object.values(TITLES)) expect(screen.getByText(title)).toBeTruthy()
    expect(screen.getByRole('button', { name: '拉取日线' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '重新加载' })).toBeTruthy()
    expect(screen.getAllByRole('button', { name: '拉取' })).toHaveLength(4)
    expect(screen.getByText('派生')).toBeTruthy()
    expect(screen.getByText('手动维护')).toBeTruthy()
    expect(screen.getAllByText('采集')).toHaveLength(4)
  })

  it('highlights lagging coverage', async () => {
    vi.mocked(api.getDataFamilies).mockResolvedValue(
      overview(six({ bars: { coverage: { targets: 10, covered: 8, lagging: ['MU', 'NVDA'] } } })))
    render(Data)
    const lagging = await screen.findByText('8 / 10')
    expect(lagging.className).toContain('text-warn')
    expect(screen.getAllByText('10 / 10')[0].className).not.toContain('text-warn')
  })

  it('shows failure reasons of the last run', async () => {
    vi.mocked(api.getDataFamilies).mockResolvedValue(overview(six({
      news: {
        last_run: {
          status: 'partial', trigger: 'manual_batch', scope: 'family', ticker: null,
          finished_at: '2026-10-22T08:00:00+00:00', ok_count: 3, target_count: 5,
          failures: [{ target: 'MU', reason: '日线超时' }, { target: 'NVDA', reason: '网络错误' }],
        },
      },
    })))
    render(Data)
    expect(await screen.findByText(/日线超时/)).toBeTruthy()
    expect(screen.getByText(/网络错误/)).toBeTruthy()
    expect(screen.getByText(fmtBeijing('2026-10-22T08:00:00+00:00'))).toBeTruthy()
    expect(screen.getByText('手动批处理')).toBeTruthy()
    expect(screen.getByText('3/5')).toBeTruthy()
  })

  it('shows migration notice', async () => {
    vi.mocked(api.getDataFamilies).mockResolvedValue(overview(six(), { fetch_runs_ready: false }))
    render(Data)
    expect(await screen.findByText('迁移 024 未执行')).toBeTruthy()
    expect(screen.getAllByText('10 / 10')).toHaveLength(6)
  })

  it('ATR fetch calls bars', async () => {
    render(Data)
    await screen.findByText('ATR')
    await fireEvent.click(screen.getByRole('button', { name: '拉取日线' }))
    await waitFor(() => expect(api.fetchDataFamily).toHaveBeenCalledWith('bars', undefined))
  })

  it('busy fetch shows message', async () => {
    vi.mocked(api.fetchDataFamily).mockRejectedValue(new Error('该族正在采集'))
    render(Data)
    await screen.findByText('日线')
    await fireEvent.click(screen.getAllByRole('button', { name: '拉取' })[0])
    expect(await screen.findByText('该族正在采集')).toBeTruthy()
    expect((screen.getAllByRole('button', { name: '拉取' })[0] as HTMLButtonElement).disabled).toBe(false)
  })

  it('refreshes card after run completes', async () => {
    vi.mocked(api.getDataFamilies).mockResolvedValueOnce(overview(six()))
      .mockResolvedValue(overview(six({ bars: { coverage: { targets: 10, covered: 9, lagging: ['MU'] } } })))
    render(Data)
    await screen.findByText('日线')
    await fireEvent.click(screen.getAllByRole('button', { name: '拉取' })[0])
    await waitFor(() => expect(api.getDataFamilies).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('9 / 10')).toBeTruthy()
  })

  it('shows still-running on poll timeout', async () => {
    vi.mocked(api.pollRun).mockRejectedValue(new Error('run timeout'))
    render(Data)
    await screen.findByText('日线')
    await fireEvent.click(screen.getAllByRole('button', { name: '拉取' })[0])
    const message = await screen.findByText('仍在后台运行，稍后刷新')
    expect(message).toBeTruthy()
    expect(message).toHaveClass('text-muted')
    expect(message.className).not.toMatch(/text-(?:red|danger)/)
    expect(screen.getAllByRole('button', { name: '拉取' })[0]).toBeEnabled()
    expect(api.pollRun).toHaveBeenCalledWith('r1', { timeoutMs: 900_000 })
  })

  it('shows backend 503 text', async () => {
    vi.mocked(api.getDataFamilies).mockRejectedValue(new Error('需执行迁移 024'))
    render(Data)
    expect(await screen.findByRole('alert')).toHaveTextContent('需执行迁移 024')
  })

  it('job link', async () => {
    vi.mocked(api.getDataFamilies).mockResolvedValue(
      overview(six({ fred: { job: job({ enabled: false, next_run_at: null }) } })))
    render(Data)
    await screen.findByText('日线')
    const barsJob = within(screen.getByRole('article', { name: '日线' })).getByRole('link', { name: /workbench/ })
    expect(barsJob).toHaveAttribute('href', '#tools/tasks')
    expect(barsJob).toHaveTextContent('开')
    expect(barsJob).toHaveTextContent(fmtBeijing('2026-10-23T06:30:00+00:00'))
    const fredJob = within(screen.getByRole('article', { name: 'FRED 利差' })).getByRole('link', { name: /workbench/ })
    expect(fredJob).toHaveTextContent('关')
    expect(fredJob).toHaveTextContent('下次 —')
  })
})

// Boundary regressions from self-review: a finished runner may be error or may
// have lost the lock after the API's probe. Neither is an unqualified success.
describe('Data 拉取结果', () => {
  it('keeps fetch-record write errors visible after a successful overview refresh', async () => {
    vi.mocked(api.pollRun).mockResolvedValue({
      run_id: 'r1', status: 'done', result: {
        status: 'success',
        data_status: { written: 0, error: 'permission denied for table data_fetch_runs' },
      },
    })
    vi.mocked(api.getDataFamilies).mockResolvedValueOnce(overview(six()))
      .mockResolvedValue(overview(six({ bars: { coverage: { targets: 10, covered: 9, lagging: ['MU'] } } })))
    render(Data)
    const bars = within(await screen.findByRole('article', { name: '日线' }))
    await fireEvent.click(bars.getByRole('button', { name: '拉取' }))
    expect(await bars.findByText('9 / 10')).toBeTruthy()
    expect(api.getDataFamilies).toHaveBeenCalledTimes(2)
    expect(bars.getByText('采集记录写入失败：permission denied for table data_fetch_runs')).toHaveClass('text-red-600')
    expect(bars.getByRole('button', { name: '拉取' })).toBeEnabled()
  })

  it('shows runner error and refreshes the overview after completion', async () => {
    vi.mocked(api.pollRun).mockResolvedValue({ run_id: 'r1', status: 'error', error: '采集服务不可达' })
    render(Data)
    await fireEvent.click(await screen.findByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('采集服务不可达')).toHaveClass('text-red-600')
    expect(api.getDataFamilies).toHaveBeenCalledTimes(2)
    await waitFor(() => expect(screen.getByRole('button', { name: '重新加载' })).toBeEnabled())
  })

  it('shows busy result when the background task loses the lock', async () => {
    vi.mocked(api.pollRun).mockResolvedValue({ run_id: 'r1', status: 'done', result: { status: 'busy' } })
    render(Data)
    await fireEvent.click(await screen.findByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('该族正在采集')).toBeTruthy()
    await waitFor(() => expect(screen.getByRole('button', { name: '重新加载' })).toBeEnabled())
  })
})

describe('Data API wrappers', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })))
  })

  it('sends fetch requests with optional ticker, and browse filters in the URL', async () => {
    await api.fetchDataFamily('bars', 'MU')
    expect(fetch).toHaveBeenLastCalledWith('/api/data/families/bars/fetch', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ ticker: 'MU' }),
    }))
    await api.fetchDataFamily('universe')
    expect(fetch).toHaveBeenLastCalledWith('/api/data/families/universe/fetch', expect.objectContaining({
      method: 'POST', body: '{}',
    }))
    await api.browseData('bars', { ticker: 'MU' })
    expect(fetch).toHaveBeenLastCalledWith('/api/data/browse/bars?ticker=MU', expect.anything())
    await api.browseData('fred', { series: 'T10Y2Y' })
    expect(fetch).toHaveBeenLastCalledWith('/api/data/browse/fred?series=T10Y2Y', expect.anything())
  })

  it('preserves backend 503 details for all three GET wrappers', async () => {
    vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify({ error: '需执行迁移 024' }), { status: 503 }))
    await expect(api.getDataFamilies()).rejects.toThrow('需执行迁移 024')
    await expect(api.getDataFamily('bars')).rejects.toThrow('需执行迁移 024')
    await expect(api.browseData('bars', { ticker: 'MU' })).rejects.toThrow('需执行迁移 024')
  })
})


const run = (overrides: Partial<FetchRun> = {}): FetchRun => ({
  id: 11, created_at: '2026-10-22T08:00:00+00:00', family: 'bars', job: 'workbench',
  trigger: 'manual_family', run_id: 'r1', scope: 'family', ticker: null, session: '2026-10-22',
  status: 'partial', target_count: 2, ok_count: 1,
  failures: [{ target: 'NVDA', reason: '源超时' }], detail: {},
  started_at: '2026-10-22T07:00:00+00:00', finished_at: '2026-10-22T08:00:00+00:00',
  ...overrides,
})
const detail = (extra: Partial<FamilyDetail> = {}): FamilyDetail => ({
  card: card('bars'), runs: [run()], rows: [
    { target: 'MU', latest_at: '2026-10-22', lagging: false, last_failure: '整族连接失败' },
    { target: 'NVDA', latest_at: '2026-10-20', lagging: true, last_failure: '源超时' },
  ], ...extra,
})

describe('Data 详情', () => {
  it('detail shows runs and coverage rows', async () => {
    render(Data, { sub: 'bars' })
    const runs = within(await screen.findByRole('table', { name: '最近拉取' }))
    expect(runs.getByText('手动拉取')).toBeTruthy()
    expect(runs.getByText('partial')).toBeTruthy()
    expect(runs.getByText('1/2')).toBeTruthy()
    expect(runs.getByText(fmtBeijing('2026-10-22T08:00:00+00:00'))).toBeTruthy()
    expect(runs.getByText(/NVDA.*源超时/)).toBeTruthy()
    expect(screen.getByRole('link', { name: '运行记录' })).toHaveAttribute('href', '#tools/runs')
    const coverage = within(screen.getByRole('table', { name: '逐目标覆盖' }))
    expect(coverage.getByText('MU')).toBeTruthy()
    expect(coverage.getByText('整族连接失败')).toBeTruthy()
    expect(coverage.getByText('NVDA')).toBeTruthy()
    expect(coverage.getByText('2026-10-20')).toBeTruthy()
    expect(await screen.findByLabelText('证据说明')).toHaveTextContent(EVIDENCE)
    const calls = vi.mocked(api.getDataFamily).mock.calls.length
    await fireEvent.click(screen.getByRole('checkbox', { name: '仅看滞后' }))
    expect(coverage.queryByText('MU')).toBeNull()
    expect(coverage.getByText('NVDA')).toBeTruthy()
    expect(api.getDataFamily).toHaveBeenCalledTimes(calls)
    expect(api.browseData).toHaveBeenCalledWith('bars', { ticker: 'MU' })
  })

  it('unknown sub falls back to overview', async () => {
    render(Data, { sub: 'signals' })
    expect(await screen.findByRole('heading', { name: '数据' })).toBeTruthy()
    expect(screen.getAllByRole('article')).toHaveLength(6)
    expect(api.getDataFamily).not.toHaveBeenCalled()
  })

  it('keeps the card refresh wired to detail, runs, coverage and raw values', async () => {
    vi.mocked(api.getDataFamily).mockResolvedValueOnce(detail()).mockResolvedValue(detail({
      card: card('bars', { coverage: { targets: 2, covered: 1, lagging: ['NVDA'] } }),
      runs: [run({ id: 12, status: 'success', ok_count: 2, failures: [] })],
      rows: [{ target: 'MU', latest_at: '2026-10-23', lagging: false, last_failure: null }],
    }))
    render(Data, { sub: 'bars' })
    await screen.findByRole('table', { name: '逐目标覆盖' })
    await waitFor(() => expect(api.browseData).toHaveBeenCalledTimes(1))
    await fireEvent.click(within(screen.getByRole('article', { name: '日线' })).getByRole('button', { name: '拉取' }))
    expect(await screen.findByText('1 / 2')).toBeTruthy()
    expect(within(screen.getByRole('table', { name: '最近拉取' })).getByText('success')).toBeTruthy()
    expect(within(screen.getByRole('table', { name: '逐目标覆盖' })).getByText('2026-10-23')).toBeTruthy()
    expect(api.getDataFamilies).toHaveBeenCalledTimes(2)
    expect(api.getDataFamily).toHaveBeenCalledTimes(2)
    await waitFor(() => expect(api.browseData).toHaveBeenCalledTimes(2))
  })

  it('single fetch refreshes detail without resetting the selected ticker', async () => {
    render(Data, { sub: 'bars' })
    const input = await screen.findByRole('combobox', { name: '标的' })
    await fireEvent.input(input, { target: { value: 'nvda' } })
    await fireEvent.submit(input.closest('form')!)
    await waitFor(() => expect(api.browseData).toHaveBeenLastCalledWith('bars', { ticker: 'NVDA' }))
    await fireEvent.click(screen.getByRole('button', { name: '只拉这一只' }))
    await waitFor(() => expect(api.getDataFamily).toHaveBeenCalledTimes(2))
    expect(api.fetchDataFamily).toHaveBeenCalledWith('bars', 'NVDA')
    expect(input).toHaveValue('NVDA')
    expect(api.browseData).toHaveBeenLastCalledWith('bars', { ticker: 'NVDA' })
  })

  it('shows detail backend errors instead of a placeholder', async () => {
    vi.mocked(api.getDataFamily).mockRejectedValue(new Error('数据库不可达'))
    render(Data, { sub: 'news' })
    expect(await screen.findByRole('alert')).toHaveTextContent('数据库不可达')
    expect(screen.queryByText(/建设中/)).toBeNull()
  })

  it('reacts to known sub changes and ignores stale detail responses', async () => {
    let finish!: (v: FamilyDetail) => void
    vi.mocked(api.getDataFamily).mockImplementation(id => id === 'bars'
      ? new Promise(resolve => { finish = resolve })
      : Promise.resolve(detail({ card: card('fred'), rows: [], runs: [] })))
    const view = render(Data, { sub: 'bars' })
    await waitFor(() => expect(api.getDataFamily).toHaveBeenCalledWith('bars'))
    await view.rerender({ sub: 'fred' })
    expect(await screen.findByRole('article', { name: 'FRED 利差' })).toBeTruthy()
    finish(detail())
    await waitFor(() => expect(screen.queryByRole('article', { name: '日线' })).toBeNull())
    expect(screen.getByRole('combobox', { name: 'FRED 序列' })).toBeTruthy()
  })

  it('shows migration notice and empty detail tables', async () => {
    vi.mocked(api.getDataFamilies).mockResolvedValue(overview(six(), { fetch_runs_ready: false }))
    vi.mocked(api.getDataFamily).mockResolvedValue(detail({ runs: [], rows: [] }))
    render(Data, { sub: 'bars' })
    expect(await screen.findByText('迁移 024 未执行')).toBeTruthy()
    expect(screen.getByRole('table', { name: '最近拉取' })).toHaveTextContent('无记录')
    expect(screen.getByRole('table', { name: '逐目标覆盖' })).toHaveTextContent('无目标')
  })
})
