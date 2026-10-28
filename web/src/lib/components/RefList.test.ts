import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import RefList from './RefList.svelte'
import * as api from '../api'
import * as wb from '../workbench'
import { resetConceptIndex } from '../knowledge'

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  vi.spyOn(wb, 'getAgentRun').mockResolvedValue({ tool_calls: [
    { seq: 2, phase: 'propose', tool: 'get_price_bars', args: { ticker: 'NVDA' }, result: { last_close: '93.80' },
      result_sha256: 'abcdef0123', called_at: '2026-10-23T22:30:00Z' },
  ] } as any)
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('RefList', () => {
  it('fact refs call back with the key', async () => {
    const onFact = vi.fn()
    render(RefList, { refs: ['fact:plans'], onFact })
    await fireEvent.click(screen.getByRole('button', { name: 'fact:plans' }))
    expect(onFact).toHaveBeenCalledWith('plans')
  })
  it('call refs expand the tool call of the run, once fetched', async () => {
    render(RefList, { refs: ['call:2', 'call:9'], runId: 'run-1' })
    await fireEvent.click(screen.getByRole('button', { name: 'call:2' }))
    const region = await screen.findByRole('region', { name: '工具调用 call:2' })
    expect(region).toHaveTextContent('get_price_bars')
    expect(region).toHaveTextContent('93.80')
    expect(wb.getAgentRun).toHaveBeenCalledWith('run-1')
    await fireEvent.click(screen.getByRole('button', { name: 'call:9' }))
    expect(await screen.findByText('未找到该编号的工具调用')).toBeInTheDocument()
    expect(wb.getAgentRun).toHaveBeenCalledTimes(1)
    await fireEvent.click(screen.getByRole('button', { name: 'call:2' }))   // toggles closed
    await waitFor(() => expect(screen.queryByRole('region', { name: '工具调用 call:2' })).toBeNull())
  })
  it('call refs without a run are plain text', () => {
    render(RefList, { refs: ['call:2'] })
    expect(screen.queryByRole('button', { name: 'call:2' })).toBeNull()
    expect(screen.getByText('call:2')).toBeInTheDocument()
  })
  it('know refs link to the version page; concept refs open the card in place; the rest is text', async () => {
    render(RefList, { refs: ['know:3@1', 'concept:plan.stop@1', 'user:12', 'fact:context'] })
    expect(screen.getByRole('link', { name: 'know:3@1' })).toHaveAttribute('href', '#knowledge/mine/3@1')
    expect(await screen.findByRole('button', { name: '概念：plan.stop' })).toBeInTheDocument()
    expect(screen.getByText('user:12')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'user:12' })).toBeNull()
  })
})
