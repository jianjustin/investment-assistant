import { expect, it } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import VolumeBars from './VolumeBars.svelte'
import type { Bar } from '../api'

const bars = (volumes: number[]) => volumes.map((volume, i) => ({ date: `2026-10-${String(i + 1).padStart(2, '0')}`, volume })) as unknown as Bar[]

it('draws one bar per day over the window', () => {
  render(VolumeBars, { bars: bars(Array(30).fill(100)), days: 20 })
  expect(screen.getAllByTestId('vol-bar')).toHaveLength(20)
})

it('a spike of 1.5x the 20 day average is drawn with the chart token, the rest muted', () => {
  render(VolumeBars, { bars: bars([...Array(19).fill(100), 1000]), days: 20 })
  const rects = screen.getAllByTestId('vol-bar')
  expect(rects.at(-1)).toHaveClass('fill-chart-1')
  for (const rect of rects.slice(0, -1)) {
    expect(rect).toHaveClass('fill-muted-foreground/40')
    expect(rect).not.toHaveClass('fill-chart-1')
  }
  // colours live in classes (tokens), not in fill attributes
  expect(rects.every(r => !r.getAttribute('fill'))).toBe(true)
})

it('an empty window draws nothing', () => {
  render(VolumeBars, { bars: [], days: 20 })
  expect(screen.queryAllByTestId('vol-bar')).toHaveLength(0)
})
