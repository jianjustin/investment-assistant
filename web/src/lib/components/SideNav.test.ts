import { cleanup, render, screen } from '@testing-library/svelte'
import { afterEach, describe, expect, it } from 'vitest'
import SideNav from './SideNav.svelte'

afterEach(cleanup)

describe('SideNav', () => {
  it('highlights 运行记录 for the list and for a run detail (#tools/runs/<id>)', async () => {
    render(SideNav, { current: 'tools', sub: 'runs/daily-20261030033000-1a2b3c4d' })
    const runs = await screen.findByRole('link', { name: '运行记录' })
    expect(runs.className).toContain('text-primary')
    expect(screen.getByRole('link', { name: '任务中心' }).className).not.toContain('text-primary')
    cleanup()
    render(SideNav, { current: 'tools', sub: 'runs' })
    expect((await screen.findByRole('link', { name: '运行记录' })).className).toContain('text-primary')
    cleanup()
    render(SideNav, { current: 'tools', sub: 'tasks' })
    expect((await screen.findByRole('link', { name: '运行记录' })).className).not.toContain('text-primary')
  })
})
