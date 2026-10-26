import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import Data from './Data.svelte'
import * as api from '../lib/api'
import { fmtBeijing } from '../lib/format'
import type { DataOverview, FamilyCard, FamilyId, FamilyJob } from '../lib/data-families'

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
    expect(screen.getByRole('button', { name: '重新加载' })).toBeEnabled()
  })

  it('shows busy result when the background task loses the lock', async () => {
    vi.mocked(api.pollRun).mockResolvedValue({ run_id: 'r1', status: 'done', result: { status: 'busy' } })
    render(Data)
    await fireEvent.click(await screen.findByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('该族正在采集')).toBeTruthy()
    expect(screen.getByRole('button', { name: '重新加载' })).toBeEnabled()
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
