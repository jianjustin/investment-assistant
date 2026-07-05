import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import Settings from './Settings.svelte'
import * as api from '../lib/api'

describe('Settings · Watchlist', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders a single table with delete action column', async () => {
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({
      rows: [{ ticker: 'NVDA', status: 'active', thesis: null }],
    } as any)

    render(Settings, { props: { sub: 'watchlist' } })

    await screen.findByText('NVDA')
    // 只应有一个表格，删除按钮在表格行内（不再有独立裸列表）
    expect(document.querySelectorAll('table').length).toBe(1)
    const del = await screen.findByText('删除')
    expect(del.closest('table')).toBeTruthy()
    expect(document.querySelectorAll('ul li').length).toBe(0)
  })
})

describe('Settings · Discord', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('verify button calls testNotifyChannel', async () => {
    vi.spyOn(api, 'getNotifySettings').mockResolvedValue({
      discord_enabled: true,
      task_channels: { metrics: 'daily' },
      task_enabled: { metrics: true },
      webhooks: { daily: { configured: true } },
      degraded: false,
    } as any)
    const spy = vi.spyOn(api, 'testNotifyChannel').mockResolvedValue({ ok: true })

    render(Settings, { props: { sub: 'discord' } })

    const btn = await screen.findByText('验证 daily')
    await fireEvent.click(btn)

    expect(spy).toHaveBeenCalled()
  })

  it('webhook inputs are password type — plaintext never visible', async () => {
    vi.spyOn(api, 'getNotifySettings').mockResolvedValue({
      discord_enabled: true,
      task_channels: {},
      task_enabled: {},
      webhooks: { earnings: { configured: false }, signals: { configured: false }, daily: { configured: false } },
      degraded: false,
    } as any)
    vi.spyOn(api, 'testNotifyChannel').mockResolvedValue({ ok: true })

    render(Settings, { props: { sub: 'discord' } })

    await screen.findByText('验证 daily')

    const inputs = document.querySelectorAll('input[type="password"]')
    expect(inputs.length).toBeGreaterThanOrEqual(3)
  })
})
