<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import { fmtTime } from '../lib/format'
  import StatusRibbon from '../lib/components/StatusRibbon.svelte'
  import DotMatrix from '../lib/components/DotMatrix.svelte'
  import RatioBar from '../lib/components/RatioBar.svelte'
  import Gauge from '../lib/components/Gauge.svelte'
  import { buildDayCells, countStatuses } from '../lib/signals'

  let { sub }: { sub?: string } = $props()

  // Map legacy 'overview' → 'signals'; unknown subs default to 'signals'
  type Tab = 'signals' | 'trend' | 'tickers' | 'filings'
  let tab = $derived<Tab>(
    sub === 'trend' ? 'trend'
    : sub === 'tickers' ? 'tickers'
    : sub === 'filings' ? 'filings'
    : 'signals'
  )

  let signals = $state<any[]>([])
  let trend = $state<any>(null)
  let tickers = $state<any[]>([])
  let loading = $state(true)

  // 财报 Tab 状态
  let filings = $state<any[]>([])
  let filingTickers = $state<string[]>([])
  let fTicker = $state('')
  let fForm = $state('')
  let fFrom = $state('')
  let fTo = $state('')

  const cols = [
    { key: 'signal_date', label: '日期' },
    { key: 'market_status', label: '状态' },
    { key: 'spy_close', label: 'SPY' },
    { key: 'vix_close', label: 'VIX' },
  ]

  const tkCols = [
    { key: 'ticker', label: 'Ticker' },
    { key: 'trend_state', label: '趋势' },
    { key: 'attention_level', label: '关注度' },
  ]

  async function loadFilings() {
    const r = await api.getFilingRecords({
      ticker: fTicker || undefined,
      form: fForm || undefined,
      from: fFrom || undefined,
      to: fTo || undefined,
    })
    filings = r.records
    filingTickers = r.tickers
  }

  async function load() {
    loading = true
    try {
      ;[signals, trend, tickers] = await Promise.all([
        api.getMarketSignals(30).then((r: any) => r.rows ?? []),
        api.getMarketSignalsTrend(),
        api.getTickerTrends().then((r: any) => r.rows ?? []),
      ])
      await loadFilings()
    } finally { loading = false }
  }

  onMount(load)

  let cells = $derived(buildDayCells(signals as any, 30))
  let counts = $derived(countStatuses(signals as any))
  const judgeLabel: Record<string, string> = { risk_on: '偏积极', neutral: '中性', risk_off: '偏空' }
  let vixHigh = $derived(((signals as any)[0]?.vix_close ?? 0) >= 20)
  let spyAbove200 = $derived(!!(signals as any)[0]?.spy_above_200ma)
  let recentYellowRed = $derived(
    (signals as any).slice(0, 5).filter((r: any) => ['yellow', 'red'].includes(String(r.market_status).toLowerCase())).length
  )
</script>

<div>
  <div class="flex items-center gap-4 mb-4">
    <h2 class="text-lg font-semibold">数据</h2>
    <div class="flex gap-1">
      {#each (['signals', 'trend', 'tickers', 'filings'] as const) as k}
        <a
          href="#data/{k}"
          class="px-3 py-1 text-sm rounded {tab === k ? 'bg-accent text-white' : 'bg-surface-2 text-muted hover:bg-surface'}"
        >{{ signals: '信号总览', trend: '趋势分析', tickers: '技术面趋势', filings: '财报' }[k]}</a>
      {/each}
    </div>
  </div>

  {#if loading}
    <Skeleton rows={4} />
  {:else if tab === 'filings'}
    <div class="space-y-3">
      <div class="flex flex-wrap items-center gap-2">
        <select bind:value={fTicker} onchange={loadFilings} class="text-sm border border-border rounded px-2 py-1 bg-surface">
          <option value="">全部标的</option>
          {#each filingTickers as t}<option value={t}>{t}</option>{/each}
        </select>
        <select bind:value={fForm} onchange={loadFilings} class="text-sm border border-border rounded px-2 py-1 bg-surface">
          <option value="">全部类型</option><option value="10-Q">10-Q</option><option value="10-K">10-K</option>
        </select>
        <input type="date" bind:value={fFrom} onchange={loadFilings} class="text-sm border border-border rounded px-2 py-1 bg-surface" />
        <span class="text-xs text-muted">至</span>
        <input type="date" bind:value={fTo} onchange={loadFilings} class="text-sm border border-border rounded px-2 py-1 bg-surface" />
      </div>
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-muted text-left">
              <th class="px-3 py-2">标的</th><th>类型</th><th>财报日期</th><th>下载时间</th><th></th>
            </tr>
          </thead>
          <tbody>
            {#each filings as f}
              <tr class="border-t border-border">
                <td class="px-3 py-2 font-medium">{f.ticker}</td>
                <td>{f.form}</td>
                <td>{f.filing_date}</td>
                <td>{fmtTime(f.downloaded_at)}</td>
                <td class="text-right pr-3">
                  <a class="text-accent text-xs" href={api.filingDownloadUrl(f.id)} download>下载 htm</a>
                </td>
              </tr>
            {:else}
              <tr><td colspan="5" class="px-3 py-4 text-muted text-sm">暂无财报记录（可在「工具 · 任务中心」对 filings 按日期回补）</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {:else if tab === 'tickers'}
    <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
      <DataTable rows={tickers} columns={tkCols} />
    </div>
  {:else if tab === 'trend'}
    {#if trend}
      <div class="bg-surface rounded-lg p-5 shadow-elev-1 space-y-4">
        <div class="flex items-center gap-5">
          <Gauge judgement={(trend as any).judgement ?? 'neutral'} />
          <div>
            <div class="text-2xl font-bold" style="color:#4ade80">{(trend as any).judgement ?? '—'}</div>
            <div class="mt-2"><RatioBar counts={(trend as any).status_counts ?? counts} /></div>
          </div>
        </div>
        <p class="text-sm text-muted">{(trend as any).summary ?? ''}</p>
        <div class="flex flex-wrap gap-2">
          <span class="text-xs px-2.5 py-1 rounded-full border {spyAbove200 ? 'border-green-500/40 text-green-400' : 'border-red-500/40 text-red-400'}">
            {spyAbove200 ? '✓ SPY 站上 200 日线' : '✗ SPY 跌破 200 日线'}
          </span>
          <span class="text-xs px-2.5 py-1 rounded-full border {vixHigh ? 'border-red-500/40 text-red-400' : 'border-green-500/40 text-green-400'}">
            VIX {(signals as any)[0]?.vix_close ?? '—'} {vixHigh ? '高波动' : '低波动'}
          </span>
          <span class="text-xs px-2.5 py-1 rounded-full border border-border text-muted">近 5 日 {recentYellowRed} 个 yellow/red</span>
        </div>
      </div>
    {:else}
      <p class="text-sm text-muted">暂无趋势数据</p>
    {/if}
  {:else}
    <div class="space-y-4">
      <div>
        <div class="text-xs text-muted mb-1">近 30 天状态演变</div>
        <StatusRibbon cells={cells} />
      </div>
      <div class="flex gap-4 text-sm">
        <span style="color:#22c55e"><b class="text-lg">{counts.green}</b> 天 green</span>
        <span style="color:#eab308"><b class="text-lg">{counts.yellow}</b> 天 yellow</span>
        <span style="color:#ef4444"><b class="text-lg">{counts.red}</b> 天 red</span>
      </div>
      <DotMatrix cells={cells} />
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <DataTable rows={signals} columns={cols} />
      </div>
    </div>
  {/if}
</div>
