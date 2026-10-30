import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/svelte'
import { createRawSnippet } from 'svelte'
import Field from './Field.svelte'

afterEach(() => cleanup())

const input = createRawSnippet((ctx: () => { id: string; describedby: string | undefined; invalid: boolean }) => ({
  render: () => {
    const { id, describedby, invalid } = ctx()
    return `<input id="${id}" ${describedby ? `aria-describedby="${describedby}"` : ''} ${invalid ? 'aria-invalid="true"' : ''} />`
  },
}))

describe('Field', () => {
  it('label above, error below with aria-describedby and role=alert', () => {
    render(Field, { label: '成交价', id: 'price', error: '必须大于 0', hint: '含手续费前', children: input })
    const field = screen.getByLabelText('成交价')
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('必须大于 0')
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(field.getAttribute('aria-describedby')!.split(' ')).toContain(alert.id)
    expect(field.getAttribute('aria-describedby')!.split(' ')).toContain(screen.getByText('含手续费前').id)
    const label = screen.getByText('成交价')
    // DOM order: label, control, then the message below
    expect(label.compareDocumentPosition(field) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(field.compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('no error means no alert and no describedby', () => {
    render(Field, { label: '成交价', id: 'price', children: input })
    expect(screen.queryByRole('alert')).toBeNull()
    const field = screen.getByLabelText('成交价')
    expect(field).not.toHaveAttribute('aria-describedby')
    expect(field).not.toHaveAttribute('aria-invalid')
  })

  it('required marker', () => {
    render(Field, { label: '数量', id: 'qty', required: true, children: input })
    const marker = screen.getByText('*')
    expect(marker).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByLabelText('数量')).toBeInTheDocument()
  })
})
