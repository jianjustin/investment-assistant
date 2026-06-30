import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import Settings from './Settings.svelte'
import * as api from '../lib/api'

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
