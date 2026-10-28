import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import DiscussButton from './DiscussButton.svelte'
import * as api from '../api'
import { WorkbenchError } from '../workbench'

beforeEach(() => { location.hash = '' })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('DiscussButton', () => {
  it('creates discussion then navigates to #discuss/<id>', async () => {
    const post = vi.spyOn(api, 'postDiscussion').mockResolvedValue({ id: 5 } as any)
    render(DiscussButton, { props: { context: { kind: 'plan', plan_id: 'p-agent' } } })
    await fireEvent.click(screen.getByRole('button', { name: '就此计划讨论' }))
    await waitFor(() => expect(location.hash).toBe('#discuss/5'))
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][0]).toMatchObject({ context: { kind: 'plan', plan_id: 'p-agent' } })
    expect(post.mock.calls[0][0].request_id).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('reads the discussion out of a {status, record} reply too', async () => {
    vi.spyOn(api, 'postDiscussion').mockResolvedValue({ status: 'replayed', record: { id: 6 } } as any)
    render(DiscussButton, { props: { context: { kind: 'card', card_id: 12 } } })
    await fireEvent.click(screen.getByRole('button', { name: '就此卡讨论' }))
    await waitFor(() => expect(location.hash).toBe('#discuss/6'))
  })

  it('takes a label', () => {
    render(DiscussButton, { props: { context: { kind: 'plan', plan_id: 'p' }, label: '问一问' } })
    expect(screen.getByRole('button', { name: '问一问' })).toBeInTheDocument()
  })

  it('a failure stays on the page, says why, and the retry keeps the request id', async () => {
    const post = vi.spyOn(api, 'postDiscussion').mockRejectedValueOnce(new WorkbenchError('迁移 027 未执行', 503))
      .mockResolvedValue({ id: 7 } as any)
    render(DiscussButton, { props: { context: { kind: 'plan', plan_id: 'p-agent' } } })
    await fireEvent.click(screen.getByRole('button', { name: '就此计划讨论' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('迁移 027 未执行')
    expect(location.hash).toBe('')
    await fireEvent.click(screen.getByRole('button', { name: '就此计划讨论' }))
    await waitFor(() => expect(location.hash).toBe('#discuss/7'))
    expect(post.mock.calls[1][0].request_id).toBe(post.mock.calls[0][0].request_id)
  })

  it('does not call crypto until it is clicked', () => {
    const uuid = vi.fn(() => 'u')
    vi.stubGlobal('crypto', { randomUUID: uuid })
    render(DiscussButton, { props: { context: { kind: 'plan', plan_id: 'p' } } })
    expect(uuid).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
