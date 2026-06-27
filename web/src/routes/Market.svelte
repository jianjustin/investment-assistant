<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  let { sub }: { sub?: string } = $props()
  import StatusPill from '../lib/components/StatusPill.svelte'

  let signals = $state<any[]>([])
  let trend = $state<any>(null)
  let loading = $state(true)
  let fetchForm = $state({ mode: 'single', date: '', from: '', to: '' })
  let fetching = $state(false)

  const cols = [
    { key: 'signal_date', label: '日期' },
    { key: 'market_status', label: '状态' },
    { key: 'spy_close', label: 'SPY' },
    { key: 'vix_close', label: 'VIX' },
  ]

  async function load() {
    loading = true
    try {
      ;[signals, trend] = await Promise.all([
        api.getMarketSignals(60).then((r: any) => r.rows ?? []),
        api.getMarketSignalsTrend(),
      ])
    } finally { loading = false }
  }

  async function doFetch() {
    fetching = true
    try {
      const body = fetchForm.mode === 'single'
        ? { date: fetchForm.date }
        : { from: fetchForm.from, to: fetchForm.to }
      await api.fetchMarketSignals(body)
      await load()
    } finally { fetching = false }
  }

  onMount(load)
</script>

<div>
  <h2 class="text-lg font-semibold mb-4">市场</h2>
  {#if loading}
    <Skeleton rows={4} />
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
    <details class="mt-4">
      <summary class="cursor-pointer text-sm text-muted">手动抓取信号</summary>
      <div class="mt-2 flex gap-2 items-end flex-wrap">
        <select bind:value={fetchForm.mode} class="border border-border rounded px-2 py-1 text-sm bg-surface">
          <option value="single">单日</option>
          <option value="range">区间</option>
        </select>
        {#if fetchForm.mode === 'single'}
          <input bind:value={fetchForm.date} type="date" class="border border-border rounded px-2 py-1 text-sm bg-surface" />
        {:else}
          <input bind:value={fetchForm.from} type="date" class="border border-border rounded px-2 py-1 text-sm bg-surface" />
          <span class="text-muted">~</span>
          <input bind:value={fetchForm.to} type="date" class="border border-border rounded px-2 py-1 text-sm bg-surface" />
        {/if}
        <button onclick={doFetch} disabled={fetching} class="px-3 py-1 bg-accent text-white rounded text-sm disabled:opacity-50">
          {fetching ? '抓取中…' : '抓取'}
        </button>
      </div>
    </details>
  {/if}
</div>
