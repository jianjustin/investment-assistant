import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import Tools from './Tools.svelte'
import * as api from '../lib/api'
import { fmtTime } from '../lib/format'

describe('Tools 任务中心', () => {
  it('renders scheduled jobs and run button', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'metrics', time_local: '08:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    expect(await screen.findByText('metrics')).toBeTruthy()
    expect(await screen.findByText('立即运行')).toBeTruthy()
  })

  it('shows Chinese help tooltip per job', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'filings', time_local: '09:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    render(Tools, { props: { sub: 'tasks' } })
    await screen.findByText('filings')
    const hint = document.querySelector('[title*="SEC EDGAR"]')
    expect(hint).toBeTruthy()
    expect(hint!.textContent).toBe('?')
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

  it('manual market fetch sends from/to dates', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({ jobs: [], degraded: false })
    const spy = vi.spyOn(api, 'fetchMarketSignals').mockResolvedValue({ rows: [{}], failures: [] })
    render(Tools, { props: { sub: 'tasks' } })
    const btn = await screen.findByText('手动抓取市场信号')
    await fireEvent.click(btn)
    expect(spy).toHaveBeenCalledTimes(1)
    const body = spy.mock.calls[0][0] as any
    expect(body.from).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(body.to).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('filings run passes selected date', async () => {
    vi.spyOn(api, 'getScheduledJobs').mockResolvedValue({
      jobs: [{ name: 'filings', time_local: '09:00', enabled: true, next_run_at: null, last_run_at: null }],
      degraded: false,
    })
    const spy = vi.spyOn(api, 'runJob').mockResolvedValue({ run_id: 'r1', status: 'pending' })
    render(Tools, { props: { sub: 'tasks' } })
    await screen.findByText('filings')
    const dateInputs = document.querySelectorAll('input[type="date"]')
    // 前两个是市场信号的 from/to，后两个属于 filings 行
    const filingsFrom = dateInputs[dateInputs.length - 2] as HTMLInputElement
    await fireEvent.input(filingsFrom, { target: { value: '2026-06-15' } })
    await fireEvent.click(await screen.findByText('立即运行'))
    expect(spy).toHaveBeenCalledWith('filings', { date: '2026-06-15' })
  })
})
