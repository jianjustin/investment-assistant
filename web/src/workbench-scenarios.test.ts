import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import App from './app.svelte'

// In-memory stand-in for the workbench API; SYNTH and all numbers are synthetic.
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const unit = {
  ticker: 'SYNTH', signal_date: '2026-09-01', proposed_action: 'buy', labels: [], candidate_ids: ['c1'],
  rule_ids: ['trend_reclaim'], entry_passed: false, market_status: null, holding: false, position: null,
  candidates: [{ id: 'c1', signal_date: '2026-09-01', action: 'buy', rule_id: 'trend_reclaim', inputs: { values: {} } }],
  brief: { id: 'b1', status: 'fallback', error: 'DEEPSEEK_API_KEY not configured',
           output: { summary: '规则候选：trend_reclaim(buy)', support: [], contra: [], conflicts: [] } },
  filings: [], news: [],
}

let decisions: any[]
beforeEach(() => {
  decisions = []
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
  vi.stubGlobal('crypto', { randomUUID: () => 'req-scenario' })
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    url = String(url)
    if (url === '/api/workbench/today') return json({ session: '2026-09-01', units: decisions.length ? [] : [unit] })
    if (url === '/api/workbench/decisions') {
      const body = JSON.parse(String(init!.body))
      decisions.push({ id: 'd1', ...body, decided_at: '2026-09-02T01:00:00Z', supersedes_id: null })
      return json({ status: 'created', record: decisions[0] })
    }
    if (url.startsWith('/api/workbench/review/shadow')) return json({ session: '2026-09-22', since: '2026-06-24', calc_version: 'review-1',
      units: decisions.map(d => ({ ...d, rule_ids: ['trend_reclaim'], outcome: { status: 'entered', entry_price: 100, windows: {
        '5': { status: 'mature', return: 0.02, spy_return: 0, excess: 0.02 }, '10': { status: 'immature' }, '20': { status: 'immature' } } } })) })
    return json({})
  }))
})
afterEach(() => vi.unstubAllGlobals())

it('decides a signal on today and finds it in the shadow review', async () => {
  history.replaceState(null, '', '#today')
  render(App)
  expect(await screen.findByRole('heading', { name: /SYNTH/ })).toBeInTheDocument()
  expect(screen.getByText(/LLM 未参与/)).toBeInTheDocument()
  await fireEvent.click(screen.getByLabelText('否决'))
  await fireEvent.input(screen.getByLabelText('理由'), { target: { value: '合成理由' } })
  await fireEvent.click(screen.getByRole('button', { name: '提交决定' }))
  expect(await screen.findByText('今日没有待处理的信号')).toBeInTheDocument()
  expect(decisions[0]).toMatchObject({ decision: 'reject', final_action: 'ignore', request_id: 'req-scenario' })

  window.location.hash = '#review/shadow'
  window.dispatchEvent(new HashChangeEvent('hashchange'))
  expect(await screen.findByText('+2.00%')).toBeInTheDocument()
  await waitFor(() => expect(screen.getAllByText('未成熟')).toHaveLength(2))
})
