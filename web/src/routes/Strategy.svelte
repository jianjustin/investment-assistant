<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  import EChart from '../lib/charts/EChart.svelte'

  let scores = $state<any[]>([])
  let loading = $state(true)
  let running = $state(false)
  let runId = $state<string | null>(null)

  const cols = [
    { key: 'ticker', label: 'Ticker' },
    { key: 'strategy', label: '策略' },
    { key: 'score', label: '分数' },
  ]

  function buildScoreOption(rows: any[]) {
    const bins = [0, 0, 0]
    for (const r of rows) {
      if (r.score < 40) bins[0]++
      else if (r.score < 70) bins[1]++
      else bins[2]++
    }
    return {
      xAxis: { data: ['0-40', '40-70', '70-100'] },
      yAxis: {},
      series: [{ type: 'bar' as const, data: bins, itemStyle: { color: 'var(--accent)' } }],
    }
  }

  async function load() {
    loading = true
    try { scores = await api.getStrategyScores().then((r: any) => r.rows ?? []) }
    finally { loading = false }
  }

  async function doRun() {
    running = true
    runId = null
    try {
      const pending = await api.runStrategyScores({}) as any
      const rec = await api.pollRun(pending.run_id)
      if (rec.status === 'done') await load()
    } finally { running = false }
  }

  onMount(load)
</script>

<div>
  <div class="flex justify-between items-center mb-4">
    <h2 class="text-lg font-semibold">策略评分</h2>
    <button onclick={doRun} disabled={running} class="px-3 py-1 bg-accent text-white rounded text-sm disabled:opacity-50">
      {running ? '运行中…' : '运行评分'}
    </button>
  </div>
  {#if loading}
    <Skeleton rows={3} />
  {:else}
    <div class="bg-surface rounded-lg shadow-elev-1 p-3 mb-4">
      <EChart option={buildScoreOption(scores)} />
    </div>
    <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
      <DataTable rows={scores} columns={cols} />
    </div>
  {/if}
</div>
