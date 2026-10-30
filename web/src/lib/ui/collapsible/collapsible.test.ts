import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/svelte'
import Fixture from './collapsible-fixture.svelte'

afterEach(() => cleanup())

const contentOf = async () => (await screen.findByText('内容', { selector: 'p' })).closest('[data-slot="collapsible-content"]')!

describe('Collapsible', () => {
  it('content visible when mounted with open=true', async () => {
    render(Fixture, { open: true })
    const content = await contentOf()
    expect(content).toHaveAttribute('data-state', 'open')
    expect(content).not.toHaveAttribute('hidden')
    expect(screen.getByRole('paragraph')).toBeInTheDocument()
  })

  it('closed content is hidden', async () => {
    render(Fixture, { open: false })
    expect(await contentOf()).toHaveAttribute('hidden')
  })

  it('a root that opens later shows its content', async () => {
    const view = render(Fixture, { open: false, gated: true })
    await view.rerender({ open: true, gated: true })
    expect(await contentOf()).not.toHaveAttribute('hidden')
  })

  // SideNav (tools group, mounted open by an effect) showed `hidden` on an open CollapsibleContent in jsdom and did not
  // reduce to a smaller case here; forceMount with an {#if open} around it is the pattern the pages use (design-system.md 6.1).
  it('forceMount never hides the content; the {#if} around it is the switch', async () => {
    render(Fixture, { open: true, gated: true, force: true })
    expect(await contentOf()).not.toHaveAttribute('hidden')
  })
})
