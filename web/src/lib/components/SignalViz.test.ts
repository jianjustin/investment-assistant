import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import StatusRibbon from './StatusRibbon.svelte'
import DotMatrix from './DotMatrix.svelte'
import RatioBar from './RatioBar.svelte'

const cells = [
  { date: '2026-07-01', status: 'green' as const },
  { date: '2026-07-02', status: 'red' as const },
]

describe('signal viz components', () => {
  it('DotMatrix renders one dot per cell', () => {
    render(DotMatrix, { props: { cells } })
    expect(screen.getAllByTestId('dot').length).toBe(2)
  })

  it('StatusRibbon renders one segment per cell', () => {
    render(StatusRibbon, { props: { cells } })
    expect(screen.getAllByTestId('ribbon-seg').length).toBe(2)
  })

  it('RatioBar renders three segments', () => {
    render(RatioBar, { props: { counts: { green: 6, yellow: 3, red: 1 } } })
    expect(screen.getAllByTestId('ratio-seg').length).toBe(3)
  })
})
