<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  let { sub }: { sub?: string } = $props()
  import Drawer from '../lib/components/Drawer.svelte'

  let watchlist = $state<any[]>([])
  let tickers = $state<any[]>([])
  let loading = $state(true)
  let drawerOpen = $state(false)
  let addForm = $state({ ticker: '', status: 'active', thesis: '' })
  let saving = $state(false)

  const wlCols = [
    { key: 'ticker', label: 'Ticker' },
    { key: 'status', label: '状态' },
    { key: 'thesis', label: '论点' },
  ]
  const tkCols = [
    { key: 'ticker', label: 'Ticker' },
    { key: 'trend_state', label: '趋势' },
    { key: 'attention_level', label: '关注度' },
  ]

  async function load() {
    loading = true
    try {
      ;[watchlist, tickers] = await Promise.all([
        api.getWatchlist().then((r: any) => r.rows ?? []),
        api.getTickerTrends().then((r: any) => r.rows ?? []),
      ])
    } finally { loading = false }
  }

  async function addItem() {
    saving = true
    try { await api.addWatchlistItem(addForm); await load() }
    finally { saving = false; drawerOpen = false }
  }

  async function removeItem(ticker: string) {
    await api.deleteWatchlistItem(ticker)
    await load()
  }

  onMount(load)
</script>

<div>
  <div class="flex justify-between items-center mb-4">
    <h2 class="text-lg font-semibold">关注 & 技术面</h2>
    <button onclick={() => drawerOpen = true} class="px-3 py-1 bg-accent text-white rounded text-sm">+ 添加</button>
  </div>
  {#if loading}
    <Skeleton rows={4} />
  {:else}
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <div class="px-4 py-2 border-b border-border text-sm font-medium">关注列表</div>
        <DataTable rows={watchlist} columns={wlCols} />
      </div>
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <div class="px-4 py-2 border-b border-border text-sm font-medium">技术面趋势</div>
        <DataTable rows={tickers} columns={tkCols} />
      </div>
    </div>
  {/if}
</div>

<Drawer open={drawerOpen} onclose={() => drawerOpen = false}>
  <h3 class="font-semibold mb-3">添加关注</h3>
  <div class="flex flex-col gap-2">
    <input bind:value={addForm.ticker} placeholder="Ticker (如 NVDA)" class="border border-border rounded px-2 py-1 text-sm bg-bg" />
    <input bind:value={addForm.thesis} placeholder="论点" class="border border-border rounded px-2 py-1 text-sm bg-bg" />
    <button onclick={addItem} disabled={saving} class="px-3 py-1 bg-accent text-white rounded text-sm disabled:opacity-50">
      {saving ? '保存中…' : '保存'}
    </button>
  </div>
</Drawer>
