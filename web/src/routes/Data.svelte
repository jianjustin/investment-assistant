<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import { fmtTime } from '../lib/format'

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
        api.getMarketSignals(60).then((r: any) => r.rows ?? []),
        api.getMarketSignalsTrend(),
        api.getTickerTrends().then((r: any) => r.rows ?? []),
      ])
      await loadFilings()
    } finally { loading = false }
  }

  onMount(load)
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
