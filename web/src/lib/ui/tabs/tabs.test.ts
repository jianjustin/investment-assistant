import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/svelte'
import TabsHost from './tabs-test-host.svelte'

afterEach(() => cleanup())

describe('Tabs', () => {
  it('arrow keys move between tabs', async () => {
    render(TabsHost)
    const [one, two, three] = screen.getAllByRole('tab')
    expect(one).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('内容一')
    one.focus()
    await fireEvent.keyDown(one, { key: 'ArrowRight' })
    expect(document.activeElement).toBe(two)
    await fireEvent.keyDown(two, { key: 'ArrowRight' })
    expect(document.activeElement).toBe(three)
    await fireEvent.keyDown(three, { key: 'ArrowRight' })
    expect(document.activeElement).toBe(one)
    await fireEvent.keyDown(one, { key: 'ArrowLeft' })
    expect(document.activeElement).toBe(three)
  })

  it('activating a tab shows its panel', async () => {
    render(TabsHost)
    const [, two] = screen.getAllByRole('tab')
    await fireEvent.mouseDown(two)
    await fireEvent.click(two)
    expect(two).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('内容二')
  })
})
