import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import Gauge from './Gauge.svelte'
import StatCard from './StatCard.svelte'
import VolumeBars from './VolumeBars.svelte'

describe('trend/tech viz components', () => {
  it('Gauge shows Chinese label for judgement', () => {
    render(Gauge, { props: { judgement: 'risk_on' } })
    expect(screen.getByTestId('gauge')).toBeTruthy()
    expect(screen.getByText('偏积极')).toBeTruthy()
  })

  it('StatCard renders label and value', () => {
    render(StatCard, { props: { label: '收盘', value: '228.50' } })
    const card = screen.getByTestId('stat-card')
    expect(card.textContent).toContain('收盘')
    expect(card.textContent).toContain('228.50')
  })

  it('VolumeBars renders one bar per day', () => {
    const bars = Array.from({ length: 5 }, (_, i) => ({
      date: `2026-06-0${i + 1}`, open: 1, high: 1, low: 1, close: 1, volume: 1000,
    }))
    render(VolumeBars, { props: { bars } })
    expect(screen.getAllByTestId('vol-bar').length).toBe(5)
  })
})
