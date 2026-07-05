import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import Tools from './Tools.svelte'
import * as api from '../lib/api'
import { fmtTime, todayLocalISO } from '../lib/format'

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

  it('manual market fetch via modal defaults to today', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({ jobs: [], degraded: false })
    const spy = vi.spyOn(api, 'fetchMarketSignals').mockResolvedValue({ rows: [{}], failures: [] })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByText('手动抓取市场信号'))
    // 弹窗默认「今日」，直接确认
    await fireEvent.click(await screen.findByText('确认'))
    expect(spy).toHaveBeenCalledWith({ date: todayLocalISO() })
  })

  it('market fetch modal supports single-date mode', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({ jobs: [], degraded: false })
    const spy = vi.spyOn(api, 'fetchMarketSignals').mockResolvedValue({ rows: [], failures: [] })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByText('手动抓取市场信号'))
    await fireEvent.click(await screen.findByText('指定单日'))
    const input = document.querySelector('#fetch-single-date') as HTMLInputElement
    await fireEvent.input(input, { target: { value: '2026-06-15' } })
    await fireEvent.click(await screen.findByText('确认'))
    expect(spy).toHaveBeenCalledWith({ date: '2026-06-15' })
  })

  it('market fetch modal rejects ranges over 30 days', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({ jobs: [], degraded: false })
    const spy = vi.spyOn(api, 'fetchMarketSignals').mockResolvedValue({ rows: [], failures: [] })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByText('手动抓取市场信号'))
    await fireEvent.click(await screen.findByText('日期范围'))
    await fireEvent.input(document.querySelector('#fetch-range-from') as HTMLInputElement, { target: { value: '2026-01-01' } })
    await fireEvent.input(document.querySelector('#fetch-range-to') as HTMLInputElement, { target: { value: '2026-03-01' } })
    expect(await screen.findByText('超出上限：一次最多拉取 30 天')).toBeTruthy()
    const confirmBtn = screen.getByText('确认') as HTMLButtonElement
    expect(confirmBtn.disabled).toBe(true)
    await fireEvent.click(confirmBtn)
    expect(spy).not.toHaveBeenCalled()
  })

  it('filings backfill via modal passes date range', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'filings', time_local: '09:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    const spy = vi.spyOn(api, 'runJob').mockResolvedValue({ run_id: 'r1', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await fireEvent.click(await screen.findByText('按日期拉取'))
    await fireEvent.click(await screen.findByText('日期范围'))
    await fireEvent.input(document.querySelector('#fetch-range-from') as HTMLInputElement, { target: { value: '2026-06-01' } })
    await fireEvent.input(document.querySelector('#fetch-range-to') as HTMLInputElement, { target: { value: '2026-06-30' } })
    await fireEvent.click(await screen.findByText('确认'))
    expect(spy).toHaveBeenCalledWith('filings', { from: '2026-06-01', to: '2026-06-30' })
  })
})
