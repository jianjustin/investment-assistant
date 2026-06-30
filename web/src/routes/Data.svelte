<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'

  let { sub }: { sub?: string } = $props()

  // Map legacy 'overview' → 'signals'; unknown subs default to 'signals'
  type Tab = 'signals' | 'trend' | 'tickers'
  let tab = $derived<Tab>(
    sub === 'trend' ? 'trend'
    : sub === 'tickers' ? 'tickers'
    : 'signals'
  )

  let signals = $state<any[]>([])
  let trend = $state<any>(null)
  let tickers = $state<any[]>([])
  let loading = $state(true)

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

  async function load() {
    loading = true
    try {
      ;[signals, trend, tickers] = await Promise.all([
        api.getMarketSignals(60).then((r: any) => r.rows ?? []),
        api.getMarketSignalsTrend(),
        api.getTickerTrends().then((r: any) => r.rows ?? []),
      ])
    } finally { loading = false }
  }

  onMount(load)
</script>

<div>
  <div class="flex items-center gap-4 mb-4">
    <h2 class="text-lg font-semibold">数据</h2>
    <div class="flex gap-1">
      {#each (['signals', 'trend', 'tickers'] as const) as k}
        <a
          href="#data/{k}"
          class="px-3 py-1 text-sm rounded {tab === k ? 'bg-accent text-white' : 'bg-surface-2 text-muted hover:bg-surface'}"
        >{{ signals: '信号总览', trend: '趋势分析', tickers: '技术面趋势' }[k]}</a>
      {/each}
    </div>
  </div>

  {#if loading}
    <Skeleton rows={4} />
  {:else if tab === 'tickers'}
    <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
      <DataTable rows={tickers} columns={tkCols} />
    </div>
  {:else if tab === 'trend'}
    {#if trend}
      <div class="bg-surface rounded-lg p-4 shadow-elev-1">
        <div class="flex gap-4 mb-3">
          <StatusPill status={(trend as any).latest_status ?? 'unknown'} />
          <span class="text-sm text-muted">近{(trend as any).window}日 · 判断: {(trend as any).judgement ?? '—'}</span>
        </div>
        <pre class="text-xs text-muted overflow-auto">{JSON.stringify(trend, null, 2)}</pre>
      </div>
    {:else}
      <p class="text-sm text-muted">暂无趋势数据</p>
    {/if}
  {:else}
    {#if trend}
      <div class="flex gap-4 mb-4">
        <StatusPill status={(trend as any).latest_status ?? 'unknown'} />
        <span class="text-sm text-muted">近{(trend as any).window}日 · 判断: {(trend as any).judgement ?? '—'}</span>
      </div>
    {/if}
    <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
      <DataTable rows={signals} columns={cols} />
    </div>
  {/if}
</div>
