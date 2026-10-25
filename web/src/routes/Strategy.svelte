<script lang="ts">
  import { untrack } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  import Placeholder from './Placeholder.svelte'
  let { sub }: { sub?: string } = $props()
  import EChart from '../lib/charts/EChart.svelte'
  import USResearch from './USResearch.svelte'

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
  let esDefinitions = $state<NonNullable<api.EventStudyKinds['definitions']>>({})
  let esUnavailable = $state<Record<string, string>>({})
  let esKindsLoading = $state(true)
  let esKindsError = $state('')
  let esKind = $state('')
  let esResult = $state<Awaited<ReturnType<typeof api.getEventStudy>> | null>(null)
  let esLoading = $state(false)
  let esError = $state('')
  let esKindsRequest = 0
  let esRequest = 0
  const esCanRun = $derived(!esKindsLoading && !esKindsError && esKinds.includes(esKind))
  const esCols = [
    { key: 'horizon', label: '窗口(交易日)' },
    { key: 'n', label: '样本数' },
    { key: 'mean_excess', label: '平均超额' },
    { key: 'median', label: '中位超额' },
    { key: 'hit_rate', label: '胜率' },
    { key: 't_stat', label: 't统计量' },
  ]
  function clearEventStudy() {
    // A → B → A must invalidate A's first request, not just compare kind names.
    esRequest++
    esResult = null
    esError = ''
    esLoading = false
  }
  function selectEventStudyKind(kind: string) {
    esKind = kind
    clearEventStudy()
  }
  async function loadEventStudyKinds() {
    const request = ++esKindsRequest
    clearEventStudy()
    esKindsLoading = true
    esKindsError = ''
    esKinds = []
    esDefinitions = {}
    esUnavailable = {}
    try {
      const data = await api.getEventStudyKinds()
      if (request !== esKindsRequest) return
      esKinds = data.kinds
      esDefinitions = data.definitions ?? {}
      esUnavailable = data.unavailable ?? {}
      if (!esKinds.includes(esKind)) esKind = esKinds[0] ?? ''
    } catch (e) {
      if (request !== esKindsRequest) return
      esKinds = []
      esKind = ''
      esKindsError = e instanceof Error ? e.message : '请求失败'
    } finally {
      if (request === esKindsRequest) esKindsLoading = false
    }
  }
  async function runEventStudy() {
    if (!esCanRun || esLoading) return
    const request = ++esRequest
    const kind = esKind
    esResult = null
    esError = ''
    esLoading = true
    try {
      const data = await api.getEventStudy(kind)
      if (request !== esRequest) return
      if (data.result?.kind && data.result.kind !== kind) {
        throw new Error('返回的事件类型与当前选择不一致，请重新运行。')
      }
      esResult = data
    } catch (e) {
      if (request === esRequest) esError = e instanceof Error ? e.message : '请求失败'
    } finally {
      if (request === esRequest) esLoading = false
    }
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

  $effect(() => { const page = sub; if (page !== 'observation') untrack(() => { void load() }) })
  $effect(() => {
    if (sub !== 'event-study') return
    untrack(() => { void loadEventStudyKinds() })
    return () => { esKindsRequest++; esRequest++ }
  })
</script>

<div>
  {#if sub === 'observation'}
    <USResearch mode="card" />
  {:else if sub === 'event-study'}
    <div class="flex justify-between items-center mb-4">
      <h2 class="text-lg font-semibold">事件研究</h2>
      <div class="flex gap-2 items-center">
        <select aria-label="事件类型" value={esKind} onchange={(e) => selectEventStudyKind(e.currentTarget.value)} disabled={esKindsLoading || !!esKindsError || !esKinds.length} class="text-sm border rounded px-2 py-1 bg-surface">
          {#each esKinds as k}<option value={k}>{k}</option>{/each}
        </select>
        <button onclick={runEventStudy} disabled={!esCanRun || esLoading} class="px-3 py-1 bg-accent text-white rounded text-sm disabled:opacity-50">
          {esLoading ? '计算中…' : '运行'}
        </button>
      </div>
    </div>
    <p class="text-sm text-muted mb-3">统计某类信号事件后 N 个交易日的超额收益分布（A 层回测）。结果可能来自缓存（source=cache）。</p>
    {#if esKindsLoading}
      <p class="text-sm text-muted mb-3" role="status">正在加载事件定义…</p>
    {:else if esKindsError}
      <div class="bg-surface rounded p-3 mb-3 text-sm text-danger" role="alert">事件定义加载失败：{esKindsError}</div>
    {:else if !esKinds.length}
      <p class="text-sm text-muted mb-3" role="status">暂无可运行的事件定义，已禁用运行。</p>
    {/if}
    {#if esCanRun && esDefinitions[esKind]}
      <div class="bg-surface rounded p-3 mb-3 text-sm">
        <p>当前定义（后端）：{JSON.stringify(esDefinitions[esKind])}</p>
        {#if esDefinitions[esKind].definition === 'close_cross_above_sma20'}
          <p>收盘价上穿20日简单移动平均线（SMA20），不是21EMA。</p>
        {/if}
      </div>
    {/if}
    {#if Object.keys(esUnavailable).length}
      <div class="bg-surface rounded p-3 mb-3 text-sm">
        <h3 class="font-semibold">已挂起 / 未实现的事件定义</h3>
        <p class="text-muted">以下类型不可运行；原因来自后端，保留原文。</p>
        {#each Object.entries(esUnavailable) as [kind, reason]}
          <p><span>{kind}</span>：{reason}</p>
        {/each}
      </div>
    {/if}
    {#if esError}
      <div class="bg-surface rounded p-3 mb-3 text-sm text-danger" role="alert">运行失败：{esError}</div>
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
      <p class="text-xs text-muted mt-2">事件类型：{esKind} · source: {esResult.source}{esResult.degraded ? ' · degraded（无数据库）' : ''}</p>
    {:else if esCanRun && !esLoading}
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
