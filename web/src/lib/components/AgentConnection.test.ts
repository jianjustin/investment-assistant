import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import AgentConnection from './AgentConnection.svelte'
import * as api from '../api'
import { fmtBeijing } from '../format'
import type { AgentConnectionView } from '../runs'

const view = (over: Partial<AgentConnectionView> = {}): AgentConnectionView => ({
  status: 'connected', email_masked: 'a***@example.com', scopes_ok: true,
  access_expires_at: '2026-10-29T12:00:00Z', refresh_expires_at: '2026-11-28T03:30:00Z', last_refresh_at: '2026-10-29T03:30:05Z',
  last_error: null, model: 'gpt-x', model_display_name: 'GPT X', provider_setting: 'chatgpt', pending: null, ...over,
})
const models = { models: [{ slug: 'gpt-x', display_name: 'GPT X' }, { slug: 'gpt-y', display_name: 'GPT Y' }] }

beforeEach(() => {
  vi.spyOn(api, 'getAgentModels').mockResolvedValue(models)
})
afterEach(() => { vi.useRealTimers(); cleanup(); vi.restoreAllMocks() })

describe('AgentConnection', () => {
  it('five states (spec §8.9, verbatim)', async () => {
    const get = vi.spyOn(api, 'getAgentConnection')
    // 未连接
    get.mockResolvedValue(view({ status: 'disconnected', email_masked: null, model: null, model_display_name: null }))
    let r = render(AgentConnection)
    expect(await screen.findByText('未连接 ChatGPT')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '连接 ChatGPT' })).toBeInTheDocument()
    r.unmount()
    // 连接中
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    vi.setSystemTime(new Date('2026-10-29T03:30:00Z'))
    get.mockResolvedValue(view({ status: 'pending', pending: { expires_at: '2026-10-29T03:38:30Z' } }))
    r = render(AgentConnection)
    expect(await screen.findByText('等待你在浏览器里完成登录（9 分钟内有效）')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
    r.unmount()
    vi.useRealTimers()
    // 已连接
    get.mockResolvedValue(view())
    r = render(AgentConnection)
    expect(await screen.findByText(
      `已连接：a***@example.com · 登录有效至 2026-11-28（每次运行自动续期）· 上次续期 ${fmtBeijing('2026-10-29T03:30:05Z')}`,
    )).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '断开' })).toBeInTheDocument()
    r.unmount()
    // 需重新登录
    get.mockResolvedValue(view({ status: 'needs_login', last_error: 'refresh_token_reused' }))
    r = render(AgentConnection)
    expect(await screen.findByText('ChatGPT 连接已失效，请重新连接')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新连接' })).toBeInTheDocument()
    r.unmount()
    // 已登录但无共享
    get.mockResolvedValue(view({ status: 'no_sharing', scopes_ok: false }))
    r = render(AgentConnection)
    expect(await screen.findByText('已登录，但这个账号没有开启计划用量共享')).toBeInTheDocument()
    expect(screen.queryByLabelText('模型')).toBeNull()
  })

  it('connect opens authorize_url in new tab and polls', async () => {
    const get = vi.spyOn(api, 'getAgentConnection')
      .mockResolvedValueOnce(view({ status: 'disconnected', email_masked: null, model: null, model_display_name: null }))
      .mockResolvedValueOnce(view({ status: 'pending', pending: { expires_at: '2099-01-01T00:00:00Z' } }))
      .mockResolvedValue(view())
    const start = vi.spyOn(api, 'startAgentLogin').mockResolvedValue({
      authorize_url: 'https://auth.example.test/authorize?state=abc', expires_at: '2099-01-01T00:00:00Z',
    })
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    render(AgentConnection)
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await fireEvent.click(await screen.findByRole('button', { name: '连接 ChatGPT' }))
    expect(start).toHaveBeenCalledTimes(1)
    expect(open).toHaveBeenCalledWith('https://auth.example.test/authorize?state=abc', '_blank', 'noopener')
    expect(screen.getByText(/等待你在浏览器里完成登录/)).toBeInTheDocument()
    expect(get).toHaveBeenCalledTimes(1)
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(get).toHaveBeenCalledTimes(2)
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(get).toHaveBeenCalledTimes(3)       // 第三次读到 connected
    expect(await screen.findByText(/已连接：a\*\*\*@example.com/)).toBeInTheDocument()
    await act(() => vi.advanceTimersByTimeAsync(10_000))
    expect(get).toHaveBeenCalledTimes(3)       // 不再 pending，轮询停止
  })

  it('login poll stops after 10 minutes and when destroyed', async () => {
    const get = vi.spyOn(api, 'getAgentConnection')
      .mockResolvedValue(view({ status: 'pending', pending: { expires_at: '2099-01-01T00:00:00Z' } }))
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    const first = render(AgentConnection)
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(get).toHaveBeenCalledTimes(1)
    await act(() => vi.advanceTimersByTimeAsync(600_000))
    const total = get.mock.calls.length
    expect(total).toBeGreaterThan(250)
    expect(screen.getByText('等待登录超时，请重新连接')).toBeInTheDocument()
    await act(() => vi.advanceTimersByTimeAsync(60_000))
    expect(get).toHaveBeenCalledTimes(total)
    first.unmount()
    get.mockClear()
    const second = render(AgentConnection)
    await act(() => vi.advanceTimersByTimeAsync(0))
    await act(() => vi.advanceTimersByTimeAsync(4000))
    const before = get.mock.calls.length
    second.unmount()
    await act(() => vi.advanceTimersByTimeAsync(20_000))
    expect(get).toHaveBeenCalledTimes(before)
  })

  it('cancel', async () => {
    const get = vi.spyOn(api, 'getAgentConnection')
      .mockResolvedValueOnce(view({ status: 'pending', pending: { expires_at: '2099-01-01T00:00:00Z' } }))
      .mockResolvedValue(view({ status: 'disconnected', email_masked: null, model: null, model_display_name: null }))
    const cancel = vi.spyOn(api, 'cancelAgentLogin').mockResolvedValue({ cancelled: true })
    render(AgentConnection)
    await fireEvent.click(await screen.findByRole('button', { name: '取消' }))
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('未连接 ChatGPT')).toBeInTheDocument()
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('disconnect revoked true and false texts', async () => {
    const get = vi.spyOn(api, 'getAgentConnection').mockResolvedValue(view())
    const disconnect = vi.spyOn(api, 'disconnectAgent').mockResolvedValueOnce({ revoked: true })
    render(AgentConnection)
    get.mockResolvedValue(view({ status: 'disconnected', email_masked: null, model: null, model_display_name: null }))
    await fireEvent.click(await screen.findByRole('button', { name: '断开' }))
    expect(await screen.findByText('已断开 ChatGPT')).toBeInTheDocument()
    expect(await screen.findByText('未连接 ChatGPT')).toBeInTheDocument()
    cleanup()

    get.mockResolvedValue(view())
    disconnect.mockResolvedValueOnce({ revoked: false })
    render(AgentConnection)
    get.mockResolvedValue(view({ status: 'disconnected', email_masked: null, model: null, model_display_name: null }))
    await fireEvent.click(await screen.findByRole('button', { name: '断开' }))
    expect(await screen.findByText('本机凭据已删除，但远端断开未确认，请到 ChatGPT 设置里断开这个应用')).toBeInTheDocument()
  })

  it('model select and 已不在可用清单里', async () => {
    const get = vi.spyOn(api, 'getAgentConnection').mockResolvedValue(view())
    const set = vi.spyOn(api, 'setAgentModel').mockResolvedValue({ model: 'gpt-y', model_display_name: 'GPT Y' })
    render(AgentConnection)
    const select = (await screen.findByLabelText('模型')) as HTMLSelectElement
    await waitFor(() => expect(select.options).toHaveLength(2))
    expect([...select.options].map(o => o.textContent)).toEqual(['GPT X', 'GPT Y'])
    expect(select.value).toBe('gpt-x')
    await fireEvent.change(select, { target: { value: 'gpt-y' } })
    expect(set).toHaveBeenCalledWith('gpt-y')
    expect(await screen.findByText('已保存，下一次运行生效')).toBeInTheDocument()
    cleanup()

    get.mockResolvedValue(view({ model: 'gpt-old', model_display_name: 'GPT Old' }))
    render(AgentConnection)
    const stale = (await screen.findByLabelText('模型')) as HTMLSelectElement
    await waitFor(() => expect(stale.options.length).toBeGreaterThan(1))
    expect([...stale.options].map(o => o.textContent)).toContain('gpt-old（已不在可用清单里）')
    expect(stale.value).toBe('gpt-old')
    expect(screen.getByText('当前所选模型已不在可用清单里，请重新选择')).toBeInTheDocument()
  })

  it('provider off note', async () => {
    vi.spyOn(api, 'getAgentConnection').mockResolvedValue(view({
      status: 'disconnected', email_masked: null, model: null, model_display_name: null, provider_setting: 'off',
    }))
    render(AgentConnection)
    expect(await screen.findByText('Agent 已关闭（WORKBENCH_AGENT_PROVIDER=off）')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '连接 ChatGPT' })).toBeEnabled()    // 可以先连好
  })

  it('shows the Chinese reason when login cannot start', async () => {
    vi.spyOn(api, 'getAgentConnection').mockResolvedValue(view({ status: 'disconnected', email_masked: null, model: null, model_display_name: null }))
    vi.spyOn(api, 'startAgentLogin').mockRejectedValue(new api.ApiError('discovery_failed', 502, 'discovery_failed'))
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    render(AgentConnection)
    await fireEvent.click(await screen.findByRole('button', { name: '连接 ChatGPT' }))
    expect(await screen.findByText('无法连接 ChatGPT 授权服务，请稍后重试')).toBeInTheDocument()
    expect(open).not.toHaveBeenCalled()
  })

  it('never renders token-like fields', async () => {
    const secrets = ['test-access-secret-1', 'test-refresh-secret-2', 'test-id-token-3', 'client-id-4', 'host-id-5', 'subject-6', 'full.name@example.com']
    vi.spyOn(api, 'getAgentConnection').mockResolvedValue({
      ...view(),
      access_token: secrets[0], refresh_token: secrets[1], id_token: secrets[2], client_id: secrets[3], host_id: secrets[4],
      subject: secrets[5], email: secrets[6],
    } as any)
    vi.spyOn(api, 'getAgentModels').mockResolvedValue({ models: [{ slug: 'gpt-x', display_name: 'GPT X', access_token: secrets[0] } as any] })
    const { container } = render(AgentConnection)
    await screen.findByText(/已连接：/)
    await screen.findByLabelText('模型')
    for (const secret of secrets) expect(container.innerHTML).not.toContain(secret)
    expect(container.querySelector('input')).toBeNull()
  })
})
