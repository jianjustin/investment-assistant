import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act, cleanup, within } from '@testing-library/svelte'
import Tools from './Tools.svelte'
import * as api from '../lib/api'
import { fmtBeijing } from '../lib/format'

const runningScheduler: api.SchedulerStatus = {
  status: 'up', detail: '调度线程正常',
  meta: { enabled: true, last_tick_at: '2026-10-16T00:00:00+00:00' },
}

function scheduledJobs(scheduler = runningScheduler) {
  return {
    jobs: [{ name: 'metrics', time_local: '08:00', weekday_mask: '1-5', timezone: 'America/New_York', enabled: true, next_run_at: null, last_run_at: null }],
    degraded: false,
    scheduler,
  }
}

// the backend appends manual-only registry jobs to the scheduled list (Task 2, services/jobs.scheduled_jobs)
const MANUAL_ONLY_BACKFILL = {
  name: 'sec_backfill', manual_only: true, enabled: false, next_run_at: null, last_run_at: null,
  time_local: null, weekday_mask: null, timezone: null,
  description: { title: 'SEC 回补', goal: '按日期回补观察名单的 SEC 申报（只手动运行）。', details: ['日期范围上限 92 天。'], manual_note: '必须指定日期或日期范围。' },
}

const scheduledReport = {
  task: 'metrics', status: 'success', trigger_source: 'scheduled', run_id: 'scheduled-1',
  started_at: '2026-10-16T00:00:00+00:00', finished_at: '2026-10-16T00:00:12+00:00',
  summary: { tickers: 3 },
}

describe('Tools 任务中心', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue(scheduledJobs())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders scheduled jobs and run button', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'metrics', time_local: '08:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    expect(await screen.findByText('metrics')).toBeTruthy()
    expect(await screen.findByText('立即运行')).toBeTruthy()
  })

  it('clicking ? opens a modal with Chinese task description', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{
        name: 'filings', time_local: '09:00', enabled: true, next_run_at: null, last_run_at: null,
        description: {
          title: 'SEC 监控', goal: '自动跟踪关注列表公司的 SEC 信息披露。',
          details: ['从 SEC EDGAR 下载 10-Q / 10-K 等财报文件，按「标的 / 表单类型」归档到本地，并写入财报索引。'],
          manual_note: '定时运行默认拉取昨日（T-1）披露；也可点「按日期运行」回补历史。',
        },
      }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    await screen.findByText('filings')
    await fireEvent.click(screen.getByLabelText('filings 说明'))
    // 弹窗解释任务目的与回补方式
    expect(await screen.findByText(/SEC EDGAR/)).toBeTruthy()
    expect(screen.getByRole('heading', { name: /filings · 任务说明/ })).toBeTruthy()
    expect(screen.getByText(/回补历史/)).toBeTruthy()
  })

  it('every job shows ? from its backend description', async () => {
    const described = (name: string, extra: Record<string, unknown> = {}) => ({
      name, enabled: true, next_run_at: null, last_run_at: null, timezone: 'Asia/Shanghai',
      description: { title: name, goal: `goal-${name}`, details: [`detail-${name}`], manual_note: `note-${name}` },
      ...extra,
    })
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [
        described('workbench', { time_local: '06:30', weekday_mask: '2-6' }),
        described('workbench_review', { time_local: '08:00', weekday_mask: '1-7' }),
        described('filings', { time_local: '09:30', weekday_mask: '1-5' }),
        { name: 'ghost', time_local: '09:00', weekday_mask: '1-5', timezone: 'America/New_York', enabled: true, next_run_at: null, last_run_at: null, description: null },
      ],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    await screen.findByText('workbench')
    expect(screen.getAllByLabelText(/ 说明$/)).toHaveLength(3)
    expect(screen.queryByLabelText('ghost 说明')).toBeNull()
    await fireEvent.click(screen.getByLabelText('workbench 说明'))
    expect(await screen.findByText('goal-workbench')).toBeTruthy()
    expect(screen.getByText('detail-workbench')).toBeTruthy()
    expect(screen.getByText(/note-workbench/)).toBeTruthy()
    expect(screen.getByText('06:30 北京 · 周二至周六')).toBeTruthy()
    expect(screen.getByText(/America\/New_York/)).toBeTruthy()
    expect(screen.getByText(/非北京时区/)).toBeTruthy()
  })

  it('formats job times down to seconds in Beijing time', async () => {
    const iso = '2026-07-04T08:00:00.123456+00:00'
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'metrics', time_local: '08:00', enabled: true, next_run_at: iso, last_run_at: null }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    expect(await screen.findByText(fmtBeijing(iso))).toBeTruthy()
    expect(document.body.textContent).not.toContain('123456')
  })

  it('dated run via modal passes date range to runJob', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [MANUAL_ONLY_BACKFILL],
      degraded: false,
    })
    const spy = vi.spyOn(api, 'runJob').mockResolvedValue({ run_id: 'r1', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByText('按日期运行'))
    await fireEvent.click(await screen.findByText('日期范围'))
    await fireEvent.input(document.querySelector('#fetch-range-from') as HTMLInputElement, { target: { value: '2026-06-01' } })
    await fireEvent.input(document.querySelector('#fetch-range-to') as HTMLInputElement, { target: { value: '2026-06-30' } })
    await fireEvent.click(await screen.findByText('确认'))
    expect(spy).toHaveBeenCalledWith('sec_backfill', { from: '2026-06-01', to: '2026-06-30' })
  })

  it('fetch-date dialog keeps titles', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({ jobs: [MANUAL_ONLY_BACKFILL], degraded: false })
    vi.spyOn(api, 'runJob').mockResolvedValue({ run_id: 'r1', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByRole('button', { name: '按日期运行' }))
    const dialog = await screen.findByRole('dialog')
    // title, description and button texts are the old modal's, now in a Dialog rendered in a portal
    expect(dialog).toHaveAccessibleName('sec_backfill · 按日期运行')
    expect(dialog).toHaveTextContent('按日期回补观察名单的 SEC 申报，与每日工作流的 SEC 监控同一套扫描、归档与去重。')
    for (const name of ['昨日（T-1）', '指定单日', '日期范围', '取消', '确认']) {
      expect(within(dialog).getByRole('button', { name })).toBeTruthy()
    }
    expect(within(dialog).getByRole('button', { name: '昨日（T-1）' })).toHaveAttribute('aria-pressed', 'true')
    await fireEvent.click(within(dialog).getByRole('button', { name: '指定单日' }))
    expect(within(dialog).getByLabelText('日期')).toBeTruthy()
    await fireEvent.keyDown(document.activeElement ?? dialog, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(api.runJob).not.toHaveBeenCalled()
  })

  it('dated run modal rejects ranges over 92 days', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [MANUAL_ONLY_BACKFILL],
      degraded: false,
    })
    const spy = vi.spyOn(api, 'runJob').mockResolvedValue({ run_id: 'r1', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByText('按日期运行'))
    await fireEvent.click(await screen.findByText('日期范围'))
    await fireEvent.input(document.querySelector('#fetch-range-from') as HTMLInputElement, { target: { value: '2026-01-01' } })
    await fireEvent.input(document.querySelector('#fetch-range-to') as HTMLInputElement, { target: { value: '2026-06-30' } })
    expect(await screen.findByText('超出上限：一次最多拉取 92 天')).toBeTruthy()
    expect((screen.getByText('确认') as HTMLButtonElement).disabled).toBe(true)
    expect(spy).not.toHaveBeenCalled()
  })

  it('runs table shows target dates and trigger source', async () => {
    vi.spyOn(api, 'getJobReports').mockResolvedValue({
      reports: [{
        task: 'sec_backfill', status: 'success', trigger_source: 'manual', run_id: 'sec_backfill-20260704090000-0a1b2c3d',
        started_at: '2026-07-04T09:00:00+00:00', finished_at: '2026-07-04T09:00:12+00:00',
        target_start_date: '2026-06-01', target_end_date: '2026-06-30',
        summary: { downloaded_count: 3 },
      }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'runs' } })
    expect(await screen.findByText('2026-06-01 ~ 2026-06-30')).toBeTruthy()
    expect(screen.getByText('手动')).toBeTruthy()
  })

  it('runs row links to #tools/runs/<id>', async () => {
    const id = 'daily-20261030033000-1a2b3c4d'
    vi.spyOn(api, 'getJobReports').mockResolvedValue({
      reports: [
        { ...scheduledReport, task: 'daily', run_id: id },
        { ...scheduledReport, task: 'workbench', run_id: 'scheduled-1' },       // an id the detail page cannot take
      ],
      degraded: false,
    })
    render(Tools, { props: { sub: 'runs' } })
    const link = await screen.findByRole('link', { name: '详情' })
    expect(link.getAttribute('href')).toBe(`#tools/runs/${id}`)
    expect(screen.getAllByRole('link', { name: '详情' })).toHaveLength(1)
  })

  it('no JSON modal', async () => {
    vi.spyOn(api, 'getJobReports').mockResolvedValue({
      reports: [{ ...scheduledReport, task: 'daily', run_id: 'daily-20261030033000-1a2b3c4d' }], degraded: false,
    })
    render(Tools, { props: { sub: 'runs' } })
    await fireEvent.click(await screen.findByRole('link', { name: '详情' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.querySelector('pre')).toBeNull()
    expect(document.body.textContent).not.toContain('"tickers"')
  })

  it('task filter has daily, sec_backfill and old names with （v2.7 及以前）', async () => {
    vi.spyOn(api, 'getJobReports').mockResolvedValue({ reports: [], degraded: false })
    render(Tools, { props: { sub: 'runs' } })
    const select = await screen.findByRole('combobox', { name: '筛选任务' })
    const options = [...select.querySelectorAll('option')].map(o => [o.getAttribute('value'), o.textContent])
    expect(options).toEqual([
      ['', '全部'], ['daily', 'daily'], ['sec_backfill', 'sec_backfill'], ['us-research', '美股研究'],
      ['filings', 'filings（v2.7 及以前）'], ['workbench', 'workbench（v2.7 及以前）'],
      ['workbench_review', 'workbench_review（v2.7 及以前）'],
    ])
  })

  it('only sec_backfill has run-by-date', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [
        { name: 'daily', time_local: '11:30', weekday_mask: '2-6', timezone: 'Asia/Shanghai', enabled: true, next_run_at: null, last_run_at: null },
        MANUAL_ONLY_BACKFILL,
      ],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    await screen.findByText('daily')
    expect(screen.getAllByRole('button', { name: '按日期运行' })).toHaveLength(1)
    const backfillRow = screen.getByText('sec_backfill').closest('tr')!
    expect(within(backfillRow).getByRole('button', { name: '按日期运行' })).toBeTruthy()
    expect(within(backfillRow).queryByRole('button', { name: '立即运行' })).toBeNull()     // 必须指定日期
    const dailyRow = screen.getByText('daily').closest('tr')!
    expect(within(dailyRow).queryByRole('button', { name: '按日期运行' })).toBeNull()
    expect(within(dailyRow).getByRole('button', { name: '立即运行' })).toBeTruthy()
  })

  it('manual_only rows show 只手动, no schedule and no 立即运行', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [
        { name: 'daily', time_local: '11:30', weekday_mask: '2-6', timezone: 'Asia/Shanghai', enabled: true, next_run_at: null, last_run_at: null },
        MANUAL_ONLY_BACKFILL,
      ],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    await screen.findByText('11:30 北京 · 周二至周六')
    const row = screen.getByText('sec_backfill').closest('tr')!
    expect(within(row).getAllByText('只手动')).toHaveLength(2)          // 计划列、状态列
    expect(row.textContent).not.toContain('时区未配置')
    expect(within(row).queryByText('任务停用')).toBeNull()
    expect(within(row).queryByRole('button', { name: '立即运行' })).toBeNull()
    expect(within(row).getByRole('button', { name: '按日期运行' })).toBeTruthy()
    expect(within(screen.getByText('daily').closest('tr')!).getByText('任务启用')).toBeTruthy()
  })

  it('daily run-now keeps its request_id for a retry after a failure', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'daily', time_local: '11:30', weekday_mask: '2-6', timezone: 'Asia/Shanghai', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    const run = vi.spyOn(api, 'runDaily').mockRejectedValueOnce(new Error('HTTP 503'))
      .mockResolvedValue({ run_id: 'r1', daily_run_id: 'daily-20261030033000-1a2b3c4d', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByRole('button', { name: '立即运行' }))
    await screen.findByText(/提交失败/)
    await fireEvent.click(screen.getByRole('button', { name: '立即运行' }))
    await screen.findByText(/daily 已提交/)
    expect(run.mock.calls[1][0]).toBe(run.mock.calls[0][0])
  })

  it('daily run-now goes through runDaily and links to the new run', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'daily', time_local: '11:30', weekday_mask: '2-6', timezone: 'Asia/Shanghai', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    const run = vi.spyOn(api, 'runDaily').mockResolvedValue({ run_id: 'r1', daily_run_id: 'daily-20261030033000-1a2b3c4d', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByRole('button', { name: '立即运行' }))
    expect(run).toHaveBeenCalledTimes(1)
    expect(await screen.findByText(/daily 已提交（daily-20261030033000-1a2b3c4d）/)).toBeTruthy()
    expect(screen.getByRole('link', { name: '运行详情' }).getAttribute('href')).toBe('#tools/runs/daily-20261030033000-1a2b3c4d')
    // 409 daily_running -> Chinese text
    run.mockRejectedValue(new api.ApiError('daily_running', 409, 'daily_running'))
    await fireEvent.click(screen.getByRole('button', { name: '立即运行' }))
    expect(await screen.findByText('daily 提交失败：每日工作流正在运行')).toBeTruthy()
  })

  it('renders the run detail page for #tools/runs/<run_id> and nothing of the task center', async () => {
    const detail = vi.spyOn(api, 'getRunDetail').mockResolvedValue({
      run_id: 'daily-20261030033000-1a2b3c4d', task: 'daily', kind: 'daily', graph_version: 'daily-1', stages_version: 'stages-4',
      session: '2026-10-29', cutoff_at: '2026-10-30T03:30:00Z', trigger: 'scheduled', status: 'success', headline: '详情页的一句话',
      executions: [], resume: null, nodes: [], raw_summary: {},
    })
    render(Tools, { props: { sub: 'runs/daily-20261030033000-1a2b3c4d' } })
    expect(await screen.findByText('详情页的一句话')).toBeTruthy()
    expect(detail).toHaveBeenCalledWith('daily-20261030033000-1a2b3c4d')
    expect(api.getScheduledJobs).not.toHaveBeenCalled()
    // an id of another shape shows the run list instead
    cleanup()
    vi.spyOn(api, 'getJobReports').mockResolvedValue({ reports: [], degraded: false })
    render(Tools, { props: { sub: 'runs/abc' } })
    expect(await screen.findByRole('combobox', { name: '筛选任务' })).toBeTruthy()
  })

  it.each(['tasks', 'runs'])('shows a disabled scheduler above the %s view', async (sub) => {
    vi.mocked(api.getScheduledJobs).mockResolvedValue(scheduledJobs({
      status: 'degraded', detail: '已通过总开关关闭', meta: { enabled: false, last_tick_at: null },
    }))
    vi.spyOn(api, 'getJobReports').mockResolvedValue({ reports: [], degraded: false })
    render(Tools, { props: { sub } })
    expect(await screen.findByText('自动调度已关闭')).toBeTruthy()
    expect(screen.getByText('总开关关闭时，已启用的任务也不会自动运行。')).toBeTruthy()
    expect(screen.getByText('已通过总开关关闭')).toBeTruthy()
    if (sub === 'tasks') {
      expect(screen.getByText('任务启用')).toBeTruthy()
      expect(screen.getByText(/America\/New_York/)).toBeTruthy()
    }
  })

  it.each([
    [{ status: 'degraded', detail: '已启用但尚未完成首个 tick', meta: { enabled: true, last_tick_at: null } }, '自动调度等待首次检查'],
    [{ status: 'down', detail: '心跳超时：上次检查在 240 秒前', meta: { enabled: true, last_tick_at: '2026-10-16T00:00:00+00:00' } }, '自动调度异常'],
    [{ status: 'up', detail: '首轮正在执行', meta: { enabled: true, last_tick_at: null, tick_in_progress: true, tick_started_at: '2026-10-16T00:00:00+00:00' } }, '自动调度正在执行'],
    [{ status: 'degraded', detail: '本轮任务耗时较长', meta: { enabled: true, last_tick_at: null, tick_in_progress: true } }, '本轮调度仍在执行'],
    [{ status: 'degraded', detail: '上轮失败，正在重试', meta: { enabled: true, last_tick_at: null, tick_in_progress: true, last_tick_failed: true } }, '自动调度重试中'],
  ] satisfies [api.SchedulerStatus, string][])('explains the current scheduler activity', async (scheduler: api.SchedulerStatus, label: string) => {
    vi.mocked(api.getScheduledJobs).mockResolvedValue(scheduledJobs(scheduler))
    render(Tools, { props: { sub: 'tasks' } })
    expect(await screen.findByText(label)).toBeTruthy()
    expect(screen.getByText(scheduler.detail)).toBeTruthy()
    if (scheduler.meta.tick_started_at) {
      expect(screen.getByText(`本轮开始：${fmtBeijing(scheduler.meta.tick_started_at)}`)).toBeTruthy()
    }
  })

  it('provides task-center refresh and preserves the previous state if its request fails', async () => {
    const jobs = vi.mocked(api.getScheduledJobs)
    render(Tools, { props: { sub: 'tasks' } })
    expect(await screen.findByText('自动调度运行中')).toBeTruthy()
    jobs.mockRejectedValueOnce(new Error('HTTP 503'))
    await fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('调度状态读取失败：HTTP 503')
    expect(screen.getByText('自动调度运行中')).toBeTruthy()
    expect(screen.getByText('metrics')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(jobs).toHaveBeenCalledTimes(3)
  })

  it('refreshes runs every 15 seconds without hiding rows, and stops on unmount', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const reports = vi.spyOn(api, 'getJobReports')
      .mockResolvedValue({ reports: [scheduledReport, { ...scheduledReport, task: 'filings', run_id: 'scheduled-2' }], degraded: false })
      .mockResolvedValueOnce({ reports: [scheduledReport], degraded: false })
    const { unmount } = render(Tools, { props: { sub: 'runs' } })
    expect(await screen.findByText('定时')).toBeTruthy()
    await act(() => vi.advanceTimersByTimeAsync(15_000))
    expect(reports).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('cell', { name: 'filings' })).toBeTruthy()
    await unmount()
    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(reports).toHaveBeenCalledTimes(2)
  })

  it('keeps the previous rows and shows a failed manual refresh, then allows retry', async () => {
    const reports = vi.spyOn(api, 'getJobReports').mockResolvedValue({ reports: [scheduledReport], degraded: false })
    render(Tools, { props: { sub: 'runs' } })
    expect(await screen.findByText('定时')).toBeTruthy()
    reports.mockRejectedValueOnce(new Error('HTTP 503'))
    await fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('运行记录读取失败：HTTP 503')
    expect(screen.getByText('定时')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(reports).toHaveBeenCalledTimes(3)
  })

  it('requests the selected task immediately when the run filter changes', async () => {
    const reports = vi.spyOn(api, 'getJobReports').mockResolvedValue({ reports: [scheduledReport], degraded: false })
    render(Tools, { props: { sub: 'runs' } })
    expect(await screen.findByText('定时')).toBeTruthy()
    await fireEvent.change(screen.getByRole('combobox', { name: '筛选任务' }), { target: { value: 'filings' } })
    expect(reports).toHaveBeenCalledTimes(2)
    expect(reports).toHaveBeenLastCalledWith('filings', 50)
  })

  it('does not overlap polling requests while a refresh is pending', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const reports = vi.spyOn(api, 'getJobReports').mockResolvedValue({ reports: [scheduledReport], degraded: false })
    render(Tools, { props: { sub: 'runs' } })
    expect(await screen.findByText('定时')).toBeTruthy()
    let resolveRefresh!: (value: { reports: typeof scheduledReport[]; degraded: boolean }) => void
    reports.mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve }))
    await act(() => vi.advanceTimersByTimeAsync(15_000))
    expect(reports).toHaveBeenCalledTimes(2)
    expect(screen.getByText('定时')).toBeTruthy()
    expect(screen.getByRole('button', { name: '刷新中…' })).toBeDisabled()
    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(reports).toHaveBeenCalledTimes(2)
    await act(async () => resolveRefresh({ reports: [scheduledReport], degraded: false }))
    expect(screen.getByRole('button', { name: '刷新' })).toBeEnabled()
  })
})

it('offers no ashares task', async () => {
  vi.spyOn(api, 'getScheduledJobs').mockResolvedValue(scheduledJobs() as any)
  vi.spyOn(api, 'getJobReports').mockResolvedValue({ reports: [] } as any)
  const tasks = render(Tools, { sub: 'tasks' })
  await screen.findAllByText('metrics')
  expect(tasks.container.textContent).not.toContain('A 股')
  tasks.unmount()
  const { container } = render(Tools, { sub: 'runs' })
  await screen.findByRole('combobox', { name: '筛选任务' })
  expect(container.querySelector('option[value="ashares"]')).toBeNull()
  expect(container.textContent).not.toContain('A 股')
})

describe('Tools · SEC 文件', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue(scheduledJobs())
  })

  const record = {
    id: 1, ticker: 'MU', form: '10-Q', filing_date: '2026-09-30',
    file_path: 'MU-10-Q.htm', downloaded_at: '2026-10-01T10:00:00Z', created_at: '2026-10-01T10:00:00Z',
  }

  it('opens the SEC filings tab', async () => {
    const get = vi.spyOn(api, 'getFilingRecords').mockResolvedValue({ records: [record], tickers: ['MU'] } as any)
    render(Tools, { props: { sub: 'filings' } })
    expect(await screen.findByRole('cell', { name: 'MU' })).toBeTruthy()
    expect(get).toHaveBeenCalledWith({})
    expect(screen.getByRole('columnheader', { name: '类型' })).toBeTruthy()
  })

  it('filters by ticker', async () => {
    const get = vi.spyOn(api, 'getFilingRecords').mockResolvedValue({ records: [record], tickers: ['MU', 'NVDA'] } as any)
    render(Tools, { props: { sub: 'filings' } })
    await waitFor(() => expect(get).toHaveBeenCalled())
    await fireEvent.change(screen.getByLabelText('按标的筛选'), { target: { value: 'NVDA' } })
    await waitFor(() => expect(get).toHaveBeenCalledWith({ ticker: 'NVDA' }))
  })
})
