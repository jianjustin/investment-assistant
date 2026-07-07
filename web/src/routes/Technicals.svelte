<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import type { OhlcvResponse } from '../lib/api'
  import CandleChart from '../lib/charts/CandleChart.svelte'
  import StatCard from '../lib/components/StatCard.svelte'
  import VolumeBars from '../lib/components/VolumeBars.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import { deriveCards, toLineData } from '../lib/technicals'

  let { sub }: { sub?: string } = $props()

  let snapshots = $state<any[]>([])
  let ohlcv = $state<OhlcvResponse | null>(null)
  let loading = $state(true)
  let active = $derived(sub || snapshots[0]?.ticker || '')

  async function loadList() {
    const r: any = await api.getTickerTrends()
    snapshots = r.rows ?? []
  }

  async function loadOhlcv(ticker: string) {
    if (!ticker) return
    ohlcv = null
    try {
      ohlcv = await api.getTickerOhlcv(ticker, 250)
    } catch {
      ohlcv = null
    }
  }

  onMount(async () => {
    await loadList()
    loading = false
  })

  // active 变化时拉行情
  let lastLoaded = ''
  $effect(() => {
    if (active && active !== lastLoaded) {
      lastLoaded = active
      loadOhlcv(active)
    }
  })

  let snapshot = $derived(snapshots.find((s) => s.ticker === active))
  let cards = $derived(ohlcv ? deriveCards(ohlcv.bars, ohlcv.ma200, snapshot) : [])
  let candles = $derived(
    ohlcv
      ? ohlcv.bars.map((b) => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close }))
      : [],
  )
  let overlays = $derived(
    ohlcv
      ? [
          { color: '#22c55e', data: toLineData(ohlcv.bars, ohlcv.ma20) },
          { color: '#60a5fa', data: toLineData(ohlcv.bars, ohlcv.ma50) },
          { color: '#f59e0b', data: toLineData(ohlcv.bars, ohlcv.ma200) },
        ]
      : [],
  )
</script>

<div>
  <h2 class="text-lg font-semibold mb-4">技术面趋势</h2>

  {#if loading}
    <Skeleton rows={4} />
  {:else if snapshots.length === 0}
    <p class="text-sm text-muted">暂无个股快照（可在「工具 · 任务中心」运行 ticker-trends 任务）。</p>
  {:else}
    <div class="flex gap-1 flex-wrap mb-4" role="tablist">
      {#each snapshots as s}
        <a
          role="tab"
          href="#technicals/{s.ticker}"
          aria-selected={s.ticker === active}
          class="px-3 py-1 text-sm rounded {s.ticker === active ? 'bg-accent text-white' : 'bg-surface-2 text-muted hover:bg-surface'}"
        >{s.ticker}</a>
      {/each}
    </div>

    <div class="flex items-center gap-3 mb-3">
      <span class="text-xl font-bold">{active}</span>
      {#if snapshot}
        <span class="text-xs px-2 py-0.5 rounded-full border border-green-500/40 text-green-400">
          {snapshot.trend_state} · {snapshot.attention_level}
        </span>
      {/if}
    </div>

    {#if ohlcv}
      <div class="grid grid-cols-2 md:grid-cols-6 gap-2 mb-4">
        {#each cards as c}
          <StatCard label={c.label} value={c.value} tone={c.tone} />
        {/each}
      </div>
      <div class="bg-surface rounded-lg p-3 shadow-elev-1">
        <div class="flex gap-3 text-xs mb-2">
          <span style="color:#22c55e">— MA20</span>
          <span style="color:#60a5fa">— MA50</span>
          <span style="color:#f59e0b">— MA200</span>
        </div>
        <CandleChart data={candles} overlays={overlays} />
        <div class="text-xs text-muted mt-3 mb-1">量价（放量高亮）</div>
        <VolumeBars bars={ohlcv.bars} />
      </div>
    {:else}
      <Skeleton rows={3} />
    {/if}
  {/if}
</div>
