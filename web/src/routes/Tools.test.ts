import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/svelte'
import Tools from './Tools.svelte'
import * as api from '../lib/api'
import { fmtTime } from '../lib/format'

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
      jobs: [{ name: 'scores', time_local: '18:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    await screen.findByText('scores')
    await fireEvent.click(screen.getByLabelText('scores 说明'))
    // 弹窗解释评分构成（例如上升趋势 +30）
    expect(await screen.findByText(/满分 100/)).toBeTruthy()
    expect(screen.getByText(/不构成交易指令/)).toBeTruthy()
  })

  it('formats job times down to seconds', async () => {
    const iso = '2026-07-04T08:00:00.123456+00:00'
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'metrics', time_local: '08:00', enabled: true, next_run_at: iso, last_run_at: null }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    expect(await screen.findByText(fmtTime(iso))).toBeTruthy()
    expect(document.body.textContent).not.toContain('123456')
  })

  it('dated run via modal passes date range to runJob', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'metrics', time_local: '08:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    const spy = vi.spyOn(api, 'runJob').mockResolvedValue({ run_id: 'r1', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByText('按日期运行'))
    await fireEvent.click(await screen.findByText('日期范围'))
    await fireEvent.input(document.querySelector('#fetch-range-from') as HTMLInputElement, { target: { value: '2026-06-01' } })
    await fireEvent.input(document.querySelector('#fetch-range-to') as HTMLInputElement, { target: { value: '2026-06-30' } })
    await fireEvent.click(await screen.findByText('确认'))
    expect(spy).toHaveBeenCalledWith('metrics', { from: '2026-06-01', to: '2026-06-30' })
  })

  it('dated run modal rejects ranges over 92 days', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'filings', time_local: '09:00', enabled: true, next_run_at: null, last_run_at: null }],
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

  it('runs table shows target dates, trigger source and detail modal', async () => {
    vi.spyOn(api, 'getJobReports').mockResolvedValue({
      reports: [{
        task: 'filings', status: 'success', trigger_source: 'manual', run_id: 'r9',
        started_at: '2026-07-04T09:00:00+00:00', finished_at: '2026-07-04T09:00:12+00:00',
        target_start_date: '2026-06-01', target_end_date: '2026-06-30',
        summary: { downloaded_count: 3 },
      }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'runs' } })
    expect(await screen.findByText('2026-06-01 ~ 2026-06-30')).toBeTruthy()
    expect(screen.getByText('手动')).toBeTruthy()
    await fireEvent.click(screen.getByText('详情'))
    expect(await screen.findByText(/downloaded_count/)).toBeTruthy()
    expect(screen.getByText(/r9/)).toBeTruthy()
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
      expect(screen.getByText(`本轮开始：${fmtTime(scheduler.meta.tick_started_at)}`)).toBeTruthy()
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

  it('refreshes runs every 15 seconds without hiding rows or losing the open detail, and stops on unmount', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const reports = vi.spyOn(api, 'getJobReports')
      .mockResolvedValue({ reports: [scheduledReport, { ...scheduledReport, task: 'filings', run_id: 'scheduled-2' }], degraded: false })
      .mockResolvedValueOnce({ reports: [scheduledReport], degraded: false })
    const { unmount } = render(Tools, { props: { sub: 'runs' } })
    expect(await screen.findByText('定时')).toBeTruthy()
    await fireEvent.click(screen.getByText('详情'))
    expect(screen.getByText(/scheduled-1/)).toBeTruthy()
    await act(() => vi.advanceTimersByTimeAsync(15_000))
    expect(reports).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('cell', { name: 'filings' })).toBeTruthy()
    expect(screen.getByText(/scheduled-1/)).toBeTruthy()
    expect(screen.getByText(/"tickers": 3/)).toBeTruthy()
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
