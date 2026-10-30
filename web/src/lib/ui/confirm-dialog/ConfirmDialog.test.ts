import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/svelte'
import ConfirmDialog from './ConfirmDialog.svelte'

const base = {
  open: true,
  title: '从此节点继续？',
  consequence: '将重新运行该节点及之后的全部节点。',
  actionLabel: '从此节点继续',
  onConfirm: () => {},
}

afterEach(() => { cleanup(); document.body.innerHTML = '' })

describe('ConfirmDialog', () => {
  it('shows title, consequence and a cancel button', async () => {
    render(ConfirmDialog, base)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAccessibleName('从此节点继续？')
    expect(dialog).toHaveTextContent('将重新运行该节点及之后的全部节点。')
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
  })

  it('focus moves into the dialog on open', async () => {
    const opener = document.createElement('button')
    opener.textContent = '续跑'
    document.body.appendChild(opener)
    opener.focus()
    const { rerender } = render(ConfirmDialog, { ...base, open: false })
    await rerender({ ...base, open: true })
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))
  })

  it('Esc closes and focus returns to the opener', async () => {
    const onCancel = vi.fn()
    const opener = document.createElement('button')
    opener.textContent = '续跑'
    document.body.appendChild(opener)
    opener.focus()
    const { rerender } = render(ConfirmDialog, { ...base, open: false, onCancel })
    await rerender({ ...base, open: true, onCancel })
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))
    await fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(onCancel).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(document.activeElement).toBe(opener))
  })

  it('cancel button closes without confirming', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(ConfirmDialog, { ...base, onConfirm, onCancel })
    await fireEvent.click(await screen.findByRole('button', { name: '取消' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('action button carries the action name and calls onConfirm', async () => {
    const onConfirm = vi.fn()
    render(ConfirmDialog, { ...base, onConfirm })
    const action = await screen.findByRole('button', { name: '从此节点继续' })
    expect(screen.queryByRole('button', { name: '确定' })).toBeNull()
    await fireEvent.click(action)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('destructive action uses the destructive style', async () => {
    render(ConfirmDialog, { ...base, destructive: true, actionLabel: '确认作废' })
    const action = await screen.findByRole('button', { name: '确认作废' })
    expect(action.className).toMatch(/bg-destructive/)
  })

  it('busy disables both buttons', async () => {
    render(ConfirmDialog, { ...base, busy: true })
    const action = await screen.findByRole('button', { name: '从此节点继续' })
    expect(action).toBeDisabled()
    expect(action).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByRole('button', { name: '取消' })).toBeDisabled()
  })
})
