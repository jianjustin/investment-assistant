<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import LineChart from '../lib/charts/LineChart.svelte'

  let { sub = 'tasks' }: { sub?: string } = $props()

  let jobs = $state<any[]>([])
  let reports = $state<any[]>([])
  let metrics = $state<any[]>([])
  let results = $state<any[]>([])
  let loading = $state(true)
  let runningName = $state<string | null>(null)
  let filterTask = $state<string>('')

  async function loadTasks() { jobs = (await api.getScheduledJobs()).jobs }
  async function loadRuns() { reports = (await api.getJobReports(filterTask || undefined, 50)).reports }
  async function loadOps() { metrics = (await api.getJobMetrics(undefined, 7)).metrics }
  async function loadResults() {
    const names = ['metrics', 'filings', 'scores']
    const latest = await Promise.all(names.map((n) => api.getJobReports(n, 1)))
    results = latest.map((r, i) => ({ task: names[i], summary: r.reports[0]?.summary ?? null }))
  }

  async function load() {
    loading = true
    try {
      if (sub === 'tasks') await loadTasks()
      else if (sub === 'runs') await loadRuns()
      else if (sub === 'ops') await loadOps()
      else await loadResults()
    } finally { loading = false }
  }

  async function runNow(name: string) {
    runningName = name
    try { await api.runJob(name) } finally { runningName = null; await loadTasks() }
  }

  async function fetchMarket() { await api.fetchMarketSignals({ mode: 'single' }) }

  $effect(() => { sub; load() })
  onMount(load)
</script>

{#if loading}
  <Skeleton />
{:else if sub === 'tasks'}
  <div class="space-y-4">
    <div class="flex gap-2">
      <button class="px-3 py-1.5 rounded bg-accent/10 text-accent text-sm" onclick={fetchMarket}>手动抓取市场信号</button>
    </div>
    <table class="w-full text-sm">
      <thead><tr class="text-muted text-left"><th>任务</th><th>计划</th><th>下次</th><th>上次</th><th>状态</th><th></th></tr></thead>
      <tbody>
        {#each jobs as j}
          <tr class="border-t border-border">
            <td class="py-2">{j.name}</td>
            <td>{j.time_local} · {j.weekday_mask}</td>
            <td>{j.next_run_at ?? '—'}</td>
            <td>{j.last_run_at ?? '—'}</td>
            <td>{j.enabled ? '启用' : '停用'}</td>
            <td><button class="text-accent text-xs" disabled={runningName === j.name} onclick={() => runNow(j.name)}>立即运行</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p class="text-xs text-muted">改运行时间 / 开关请到「设置 · 定时任务」。</p>
  </div>
{:else if sub === 'runs'}
  <div class="space-y-3">
    <select bind:value={filterTask} onchange={loadRuns} class="text-sm border border-border rounded px-2 py-1 bg-surface">
      <option value="">全部</option><option value="metrics">metrics</option>
      <option value="filings">filings</option><option value="scores">scores</option>
    </select>
    {#each reports as r}
      <details class="border border-border rounded">
        <summary class="px-3 py-2 flex gap-3 cursor-pointer text-sm">
          <span class="font-medium">{r.task}</span>
          <StatusPill status={r.status} />
          <span class="text-muted">{r.started_at} → {r.finished_at ?? '—'}</span>
        </summary>
        <pre class="px-3 py-2 text-xs overflow-x-auto bg-surface-2">{JSON.stringify(r.summary, null, 2)}</pre>
      </details>
    {/each}
  </div>
{:else if sub === 'ops'}
  <div class="grid gap-4 md:grid-cols-3">
    {#each metrics as m}
      <div class="border border-border rounded p-3">
        <div class="font-medium">{m.task}</div>
        <div class="text-sm text-muted">成功率 {m.total ? Math.round((m.success / m.total) * 100) : 0}% · 均耗时 {m.avg_seconds?.toFixed?.(1) ?? '—'}s</div>
        <LineChart data={(m.error_days ?? []).map((d: any) => ({ time: d.day, value: d.count }))} />
      </div>
    {/each}
  </div>
{:else}
  <div class="grid gap-4 md:grid-cols-3">
    {#each results as r}
      <div class="border border-border rounded p-3">
        <div class="font-medium mb-1">{r.task}</div>
        <pre class="text-xs overflow-x-auto">{r.summary ? JSON.stringify(r.summary, null, 2) : '暂无数据'}</pre>
      </div>
    {/each}
  </div>
{/if}
