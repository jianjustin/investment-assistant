import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import PlanNotes from './PlanNotes.svelte'
import { notify } from '$lib/ui/toast'

vi.mock('$lib/ui/toast', () => ({ notify: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }))

afterEach(() => { cleanup(); vi.clearAllMocks() })

const notes = [{ id: 1, body: '等回踩', created_at: '2026-10-30T10:00:00Z' }]

describe('PlanNotes', () => {
  it('lists the notes, or says there are none', () => {
    render(PlanNotes, { notes, onNote: vi.fn() })
    expect(screen.getByRole('region', { name: '备注' })).toHaveTextContent('等回踩')
    cleanup()
    render(PlanNotes, { notes: [], onNote: vi.fn() })
    expect(screen.getByText('还没有备注')).toBeInTheDocument()
  })

  it('saving shows the busy button, then a success toast and an empty draft', async () => {
    let finish: () => void = () => {}
    const onNote = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
    render(PlanNotes, { notes: [], onNote })
    const box = screen.getByLabelText('备注正文') as HTMLTextAreaElement
    await fireEvent.input(box, { target: { value: '写给自己' } })
    await fireEvent.click(screen.getByRole('button', { name: '保存备注' }))
    expect(screen.getByRole('button', { name: '保存备注' })).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByRole('button', { name: '保存备注' })).toBeDisabled()
    finish()
    await waitFor(() => expect(notify.success).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(box.value).toBe(''))
  })

  it('a failure keeps the draft and shows the reason in the form', async () => {
    const onNote = vi.fn().mockRejectedValue(new Error('boom'))
    render(PlanNotes, { notes: [], onNote })
    const box = screen.getByLabelText('备注正文') as HTMLTextAreaElement
    await fireEvent.input(box, { target: { value: '写给自己' } })
    await fireEvent.click(screen.getByRole('button', { name: '保存备注' }))
    const alert = await screen.findByRole('alert')
    expect(alert.closest('form')).not.toBeNull()
    expect(box.value).toBe('写给自己')
    expect(notify.success).not.toHaveBeenCalled()
  })

  it('too long: the error sits under the field and is wired with aria-describedby', async () => {
    render(PlanNotes, { notes: [], onNote: vi.fn() })
    const box = screen.getByLabelText('备注正文')
    await fireEvent.input(box, { target: { value: '字'.repeat(1001) } })
    const alert = within(screen.getByRole('region', { name: '备注' })).getByRole('alert')
    expect(alert).toHaveTextContent('备注最多 1000 字（现在 1001 字）')
    expect(box.getAttribute('aria-describedby')!.split(' ')).toContain(alert.id)
    expect(screen.getByRole('button', { name: '保存备注' })).toBeDisabled()
  })
})
