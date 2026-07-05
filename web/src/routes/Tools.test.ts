import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import Tools from './Tools.svelte'
import * as api from '../lib/api'
import { fmtTime } from '../lib/format'

describe('Tools 任务中心', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
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
})
