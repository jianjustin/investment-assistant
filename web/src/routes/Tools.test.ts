import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Tools from './Tools.svelte'
import * as api from '../lib/api'

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
})
