<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  import Placeholder from './Placeholder.svelte'
  let { sub }: { sub?: string } = $props()
  import EChart from '../lib/charts/EChart.svelte'
  import AShares from './AShares.svelte'
  import USResearch from './USResearch.svelte'
  import { readResearchSelection } from '../lib/research-navigation'
  import { confirmResearchNavigation, guardHashNavigation } from '../lib/navigation-guard'
  let market = $state<'CN'|'US'>(readResearchSelection(location.hash)?.market ?? (new URLSearchParams(location.hash.split('?')[1] ?? '').get('market') === 'US' ? 'US' : 'CN'))
  let activeMarket = $derived.by(() => {
    if (sub !== 'observation') return market
    const requested = new URLSearchParams(location.hash.split('?')[1] ?? '').get('market')
    return readResearchSelection(location.hash)?.market ?? (requested === 'CN' || requested === 'US' ? requested : market)
  })
  function switchMarket(next:'CN'|'US') {
    if (next === activeMarket || !confirmResearchNavigation()) return
    history.replaceState(null, '', '#strategy/observation?market=' + next)
    market = next
  }

  let scores = $state<any[]>([])
  let loading = $state(true)
  let running = $state(false)
  let runId = $state<string | null>(null)

  const cols = [
    { key: 'ticker', label: 'Ticker' },
    { key: 'strategy', label: '策略' },
    { key: 'score', label: '分数' },
  ]

  let esKinds = $state<string[]>([])
  let esKind = $state('rs_strong')
  let esResult = $state<any>(null)
  let esLoading = $state(false)
  let esError = $state('')
  const esCols = [
    { key: 'horizon', label: '窗口(交易日)' },
    { key: 'n', label: '样本数' },
    { key: 'mean_excess', label: '平均超额' },
    { key: 'median', label: '中位超额' },
    { key: 'hit_rate', label: '胜率' },
    { key: 't_stat', label: 't统计量' },
  ]
  async function loadEventStudyKinds() {
    try {
      esKinds = (await api.getEventStudyKinds()).kinds
      if (esKinds.length && !esKinds.includes(esKind)) esKind = esKinds[0]
    } catch { esKinds = [] }
  }
  async function runEventStudy() {
    esError = ''
    esLoading = true
    try { esResult = await api.getEventStudy(esKind) }
    catch (e) { esError = e instanceof Error ? e.message : '请求失败' }
    finally { esLoading = false }
  }

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

  $effect(() => { const page = sub; if (page !== 'observation') untrack(() => { void load(); void loadEventStudyKinds() }) })
  $effect(() => {
    if (sub === 'observation') untrack(() => {
      const selected = readResearchSelection(location.hash)?.market
      const requested = new URLSearchParams(location.hash.split('?')[1] ?? '').get('market')
      if (selected) market = selected
      else if (requested === 'CN' || requested === 'US') market = requested
    })
  })
  onMount(() => {
    const changed = (event:HashChangeEvent) => {
      if (sub !== 'observation') return
      const next = readResearchSelection(location.hash)?.market
      if (next && next !== market && guardHashNavigation(event, '#strategy/observation?market=' + market)) market = next
    }
    window.addEventListener('hashchange', changed)
    return () => window.removeEventListener('hashchange', changed)
  })
</script>

<div>
  {#if sub === 'observation'}
    <div class="flex flex-wrap gap-2 mb-4" role="group" aria-label="研究市场">
      <button aria-pressed={activeMarket==='CN'} onclick={()=>switchMarket('CN')} class="px-3 py-1 rounded border border-border">A 股</button>
      <button aria-pressed={activeMarket==='US'} onclick={()=>switchMarket('US')} class="px-3 py-1 rounded border border-border">美股</button>
    </div>
    {#if activeMarket==='US'}<USResearch mode="card" />{:else}<AShares mode="card" />{/if}
  {:else if sub === 'event-study'}
    <div class="flex justify-between items-center mb-4">
      <h2 class="text-lg font-semibold">事件研究</h2>
      <div class="flex gap-2 items-center">
        <select bind:value={esKind} class="text-sm border rounded px-2 py-1 bg-surface">
          {#each esKinds as k}<option value={k}>{k}</option>{/each}
        </select>
        <button onclick={runEventStudy} disabled={esLoading} class="px-3 py-1 bg-accent text-white rounded text-sm disabled:opacity-50">
          {esLoading ? '计算中…' : '运行'}
        </button>
      </div>
    </div>
    <p class="text-sm text-muted mb-3">统计某类信号事件后 N 个交易日的超额收益分布（A 层回测）。结果可能来自缓存（source=cache）。</p>
    {#if esError}
      <div class="bg-surface rounded p-3 mb-3 text-sm text-danger">运行失败：{esError}</div>
    {/if}
    {#if esResult}
      {#if esResult.result?.caveats?.length}
        <div class="bg-surface rounded p-3 mb-3 text-sm text-warning">
          {#each esResult.result.caveats as c}<div>⚠ {c}</div>{/each}
        </div>
      {/if}
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <DataTable rows={Object.values(esResult.result?.horizons ?? {})} columns={esCols} />
      </div>
      <p class="text-xs text-muted mt-2">source: {esResult.source}{esResult.degraded ? ' · degraded（无数据库）' : ''}</p>
    {:else if !esLoading}
      <Placeholder title="事件研究" note="选择信号类型后点「运行」。" planned="" />
    {/if}
  {:else}
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
  {/if}
</div>
