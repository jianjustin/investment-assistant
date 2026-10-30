import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/svelte'
import { createRawSnippet } from 'svelte'
import { Alert } from './index'

const text = createRawSnippet(() => ({ render: () => '<span>内容</span>' }))
afterEach(() => cleanup())

describe('Alert', () => {
  it('info is a polite status by default, warn and danger are alerts', () => {
    render(Alert, { children: text })
    expect(screen.getByRole('status')).toBeInTheDocument()
    cleanup()
    render(Alert, { variant: 'warn', children: text })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    cleanup()
    render(Alert, { variant: 'danger', children: text })
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('role can be overridden', () => {
    render(Alert, { variant: 'info', role: 'alert', children: text })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    cleanup()
    render(Alert, { variant: 'danger', role: 'status', children: text })
    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
