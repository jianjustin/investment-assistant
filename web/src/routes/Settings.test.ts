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
      channel: 'discord',
      discord_enabled: true,
      task_channels: { workbench: 'signals' },
      task_enabled: { workbench: true },
      webhooks: { signals: { configured: true } },
      email: { from_addr: '', to_addr: '' },
      degraded: false,
    } as any)
    vi.spyOn(api, 'getEnvStatus').mockResolvedValue({ SMTP_PASSWORD: false } as any)
    const spy = vi.spyOn(api, 'testNotifyChannel').mockResolvedValue({ ok: true })

    render(Settings, { props: { sub: 'discord' } })

    const btn = await screen.findByText('验证 signals')
    await fireEvent.click(btn)

    expect(spy).toHaveBeenCalled()
  })

  it('shows only earnings and signals webhooks', async () => {
    vi.spyOn(api, 'getNotifySettings').mockResolvedValue({
      channel: 'discord',
      discord_enabled: true,
      task_channels: {},
      task_enabled: {},
      webhooks: { earnings: { configured: true }, signals: { configured: false } },
      email: { from_addr: '', to_addr: '' },
      degraded: false,
    } as any)
    vi.spyOn(api, 'getEnvStatus').mockResolvedValue({ SMTP_PASSWORD: false } as any)
    vi.spyOn(api, 'testNotifyChannel').mockResolvedValue({ ok: true })

    render(Settings, { props: { sub: 'discord' } })

    await screen.findByText('验证 earnings')
    expect(screen.getByText('验证 signals')).toBeTruthy()
    expect(screen.queryByText('验证 daily')).toBeNull()
  })

  it('webhook inputs are password type — plaintext never visible', async () => {
    vi.spyOn(api, 'getNotifySettings').mockResolvedValue({
      channel: 'discord',
      discord_enabled: true,
      task_channels: {},
      task_enabled: {},
      webhooks: { earnings: { configured: false }, signals: { configured: false } },
      email: { from_addr: '', to_addr: '' },
      degraded: false,
    } as any)
    vi.spyOn(api, 'getEnvStatus').mockResolvedValue({ SMTP_PASSWORD: false } as any)
    vi.spyOn(api, 'testNotifyChannel').mockResolvedValue({ ok: true })

    render(Settings, { props: { sub: 'discord' } })

    await screen.findByText('验证 signals')

    const inputs = document.querySelectorAll('input[type="password"]')
    expect(inputs.length).toBeGreaterThanOrEqual(2)
  })
})

describe('Settings · 通知渠道（Discord/邮件）', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('switching to 邮件 hides Discord fields and shows the email form', async () => {
    vi.spyOn(api, 'getNotifySettings').mockResolvedValue({
      channel: 'discord',
      discord_enabled: true,
      task_channels: {},
      task_enabled: {},
      webhooks: { earnings: { configured: false }, signals: { configured: false } },
      email: { from_addr: '', to_addr: '' },
      degraded: false,
    } as any)
    vi.spyOn(api, 'getEnvStatus').mockResolvedValue({ SMTP_PASSWORD: true } as any)

    render(Settings, { props: { sub: 'discord' } })

    await screen.findByText('验证 signals')
    const emailRadio = screen.getByLabelText('邮件') as HTMLInputElement
    await fireEvent.click(emailRadio)

    expect(screen.queryByText('验证 signals')).toBeNull()
    await screen.findByPlaceholderText('you@gmail.com')
    await screen.findByText(/SMTP_PASSWORD.*已配置/)
  })

  it('发送测试邮件 calls testNotifyChannel with the email channel', async () => {
    vi.spyOn(api, 'getNotifySettings').mockResolvedValue({
      channel: 'email',
      discord_enabled: true,
      task_channels: {},
      task_enabled: {},
      webhooks: {},
      email: { from_addr: 'a@gmail.com', to_addr: 'b@outlook.com' },
      degraded: false,
    } as any)
    vi.spyOn(api, 'getEnvStatus').mockResolvedValue({ SMTP_PASSWORD: false } as any)
    const spy = vi.spyOn(api, 'testNotifyChannel').mockResolvedValue({ ok: true })

    render(Settings, { props: { sub: 'discord' } })

    const btn = await screen.findByText('发送测试邮件')
    await fireEvent.click(btn)

    expect(spy).toHaveBeenCalledWith({
      channel: 'email',
      email: { from_addr: 'a@gmail.com', to_addr: 'b@outlook.com' },
    })
    await screen.findByText('✅ 成功')
  })
})
