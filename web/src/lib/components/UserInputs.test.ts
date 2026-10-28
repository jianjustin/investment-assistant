import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import UserInputs from './UserInputs.svelte'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const input = (over: Record<string, unknown> = {}) => ({
  id: 7, request_id: 'r7', request_hash: 'h', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'research',
  body: '券商上调目标价到 130', source_url: 'https://research.example.com/7', supersedes_id: null,
  created_at: '2026-10-23T02:00:00Z', superseded_by: null, ref: 'user:7', status: 'active', ...over,
})

let calls: { url: string; init?: RequestInit }[]
let respond: (url: string, init?: RequestInit) => Promise<Response>
let ids: string[]
beforeEach(() => {
  calls = []
  ids = ['u-1', 'u-2', 'u-3', 'u-4', 'u-5']
  respond = async (_url, init) => init?.method === 'POST'
    ? json({ status: 'created', record: input({ id: 8 }) }) : json({ inputs: [input()] })
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init }); return respond(String(url), init)
  }))
  vi.stubGlobal('crypto', { randomUUID: vi.fn(() => ids.shift()) })
})
afterEach(() => vi.unstubAllGlobals())

const posts = () => calls.filter(c => c.init?.method === 'POST').map(c => JSON.parse(String(c.init!.body)))

describe('UserInputs', () => {
  it('submits kind, body, url', async () => {
    render(UserInputs, { ticker: 'NVDA', signalDate: '2026-10-22' })
    await screen.findByText(/^user:7 · /)
    expect(calls[0].url).toBe('/api/workbench/user-inputs?ticker=NVDA&signal_date=2026-10-22')
    await fireEvent.change(screen.getByLabelText('类型'), { target: { value: 'news' } })
    await fireEvent.input(screen.getByLabelText('正文'), { target: { value: '公司宣布回购' } })
    await fireEvent.input(screen.getByLabelText('链接'), { target: { value: 'https://news.example.com/1' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交补充' }))
    await waitFor(() => expect(posts()).toHaveLength(1))
    expect(posts()[0]).toEqual({ request_id: 'u-1', ticker: 'NVDA', signal_date: '2026-10-22', kind: 'news',
                                 body: '公司宣布回购', source_url: 'https://news.example.com/1' })
    expect(await screen.findByText(/已记录 user:8/)).toBeInTheDocument()
    expect((screen.getByLabelText('正文') as HTMLTextAreaElement).value).toBe('')
    await waitFor(() => expect(calls.filter(c => !c.init?.method).length).toBe(2))   // 列表重新读取
  })

  it('rejects empty and over-long body before submit', async () => {
    render(UserInputs, { ticker: 'NVDA' })
    await screen.findByText(/^user:7 · /)
    await fireEvent.click(screen.getByRole('button', { name: '提交补充' }))
    expect(screen.getByText('正文不能为空')).toBeInTheDocument()
    await fireEvent.input(screen.getByLabelText('正文'), { target: { value: 'x'.repeat(4001) } })
    await fireEvent.click(screen.getByRole('button', { name: '提交补充' }))
    expect(screen.getByText('正文最多 4000 字（现在 4001 字）')).toBeInTheDocument()
    await fireEvent.input(screen.getByLabelText('正文'), { target: { value: '正常' } })
    await fireEvent.input(screen.getByLabelText('链接'), { target: { value: 'ftp://x' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交补充' }))
    expect(screen.getByText('链接须以 http:// 或 https:// 开头，最多 500 字')).toBeInTheDocument()
    expect(posts()).toHaveLength(0)
  })

  it('counts body length by code point like the backend', async () => {
    render(UserInputs, { ticker: 'NVDA' })
    await screen.findByText(/^user:7 · /)
    await fireEvent.input(screen.getByLabelText('正文'), { target: { value: '😀'.repeat(4000) } })   // 8000 UTF-16 单元
    await fireEvent.click(screen.getByRole('button', { name: '提交补充' }))
    await waitFor(() => expect(posts()).toHaveLength(1))
    await screen.findByText(/已记录 user:8/)
    await waitFor(() => expect(screen.getByRole('button', { name: '提交补充' })).not.toBeDisabled())
    await fireEvent.input(screen.getByLabelText('正文'), { target: { value: '😀'.repeat(4001) } })
    await fireEvent.click(screen.getByRole('button', { name: '提交补充' }))
    expect(screen.getByText('正文最多 4000 字（现在 4001 字）')).toBeInTheDocument()
    expect(posts()).toHaveLength(1)
  })

  it('correct and retract post supersedes_id', async () => {
    render(UserInputs, { ticker: 'NVDA' })
    await screen.findByText(/^user:7 · /)
    await fireEvent.click(screen.getByRole('button', { name: '更正' }))
    expect(screen.getByText('正在更正 user:7')).toBeInTheDocument()
    expect((screen.getByLabelText('正文') as HTMLTextAreaElement).value).toBe('券商上调目标价到 130')
    await fireEvent.input(screen.getByLabelText('正文'), { target: { value: '券商上调目标价到 135' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交补充' }))
    await waitFor(() => expect(posts()).toHaveLength(1))
    expect(posts()[0]).toMatchObject({ ticker: 'NVDA', signal_date: '2026-10-22', kind: 'research',
                                       body: '券商上调目标价到 135', supersedes_id: 7 })
    await fireEvent.click(await screen.findByRole('button', { name: '撤回' }))
    await waitFor(() => expect(posts()).toHaveLength(2))
    expect(posts()[1]).toMatchObject({ ticker: 'NVDA', signal_date: '2026-10-22', kind: 'retract', supersedes_id: 7 })
    expect(posts()[1].body).toBeTruthy()
    expect(posts()[1].request_id).not.toBe(posts()[0].request_id)
  })

  it('shows user:<id> and time', async () => {
    respond = async () => json({ inputs: [
      input(), input({ id: 9, ref: 'user:9', status: 'corrected', superseded_by: 10, signal_date: null }),
      input({ id: 10, ref: 'user:10', kind: 'retract', body: '撤回', supersedes_id: 9, signal_date: null,
              source_url: null }),
    ] })
    render(UserInputs, { ticker: 'NVDA' })
    const list = await screen.findByRole('list', { name: '补充列表' })
    const rows = list.querySelectorAll(':scope > li')
    expect(rows[0]).toHaveTextContent('user:7 · 研报要点 · 2026-10-23 10:00:00 北京 · 信号日 2026-10-22')
    expect(rows[1]).toHaveTextContent('user:9')
    expect(rows[1]).toHaveTextContent('整个标的')
    expect(rows[1]).toHaveTextContent('已更正')
    expect(rows[2]).toHaveTextContent('user:10 · 撤回')
    expect(rows[2]).toHaveTextContent('指向 user:9')
    // 只有有效输入可以更正或撤回
    expect(screen.getAllByRole('button', { name: '更正' })).toHaveLength(1)
  })

  it('keeps draft and request id on failure', async () => {
    respond = async (_url, init) => init?.method === 'POST' ? json({ error: 'down' }, 500) : json({ inputs: [] })
    render(UserInputs, { ticker: 'NVDA', chains: [{ signal_date: '2026-10-22', label: '2026-10-22 · 第 1 版' }] })
    await screen.findByText('还没有补充')
    await fireEvent.change(screen.getByLabelText('作用于'), { target: { value: '2026-10-22' } })
    await fireEvent.input(screen.getByLabelText('正文'), { target: { value: '保留的草稿' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交补充' }))
    expect(await screen.findByText(/请求失败：down/)).toBeInTheDocument()
    expect((screen.getByLabelText('正文') as HTMLTextAreaElement).value).toBe('保留的草稿')
    await fireEvent.click(screen.getByRole('button', { name: '提交补充' }))
    await waitFor(() => expect(posts()).toHaveLength(2))
    expect(posts().map(p => p.request_id)).toEqual(['u-1', 'u-1'])
    expect(posts()[0].signal_date).toBe('2026-10-22')
  })
})
