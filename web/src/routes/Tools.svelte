<script lang="ts">
  import * as api from '../lib/api'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import LineChart from '../lib/charts/LineChart.svelte'
  import { fmtTime, todayLocalISO } from '../lib/format'

  let { sub = 'tasks' }: { sub?: string } = $props()

  const JOB_HELP: Record<string, string> = {
    metrics: '每日早间拉取 SPY/VIX 计算市场信号，并扫描关注列表标的的趋势状态，写入数据库',
    filings: '从 SEC EDGAR 下载关注列表标的的财报文件（默认拉取昨日披露，可选日期回补历史）',
    scores: '收盘后按策略规则对关注列表标的计算评分快照',
    event_study: '重算事件研究（信号后收益分布统计）并缓存结果',
  }

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

  // filings 回补：留空 = 默认昨日；只填「从」= 单日；两个都填 = 范围
  let filingsFrom = $state('')
  let filingsTo = $state('')

  async function runNow(name: string) {
    runningName = name
    try {
      let body: Record<string, string> = {}
      if (name === 'filings' && filingsFrom) {
        body = filingsTo ? { from: filingsFrom, to: filingsTo } : { date: filingsFrom }
      }
      await api.runJob(name, body)
    } finally { runningName = null; await loadTasks() }
  }

  // 手动抓取市场信号：后端要求 date 或 from/to，默认今天
  let mktFrom = $state(todayLocalISO())
  let mktTo = $state(todayLocalISO())
  let mktMsg = $state('')

  async function fetchMarket() {
    mktMsg = '抓取中…'
    try {
      const r: any = await api.fetchMarketSignals({ from: mktFrom, to: mktTo })
      const ok = r?.rows?.length ?? 0
      const bad = r?.failures?.length ?? 0
      mktMsg = `完成：成功 ${ok} 天${bad ? `，失败 ${bad} 天` : ''}`
    } catch (e: any) {
      mktMsg = `失败：${e?.message ?? e}`
    }
  }

  $effect(() => { sub; load() })
</script>

{#if loading}
  <Skeleton />
{:else if sub === 'tasks'}
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <input type="date" bind:value={mktFrom} class="border border-border rounded px-2 py-1 text-sm bg-surface" />
      <span class="text-muted text-xs">至</span>
      <input type="date" bind:value={mktTo} class="border border-border rounded px-2 py-1 text-sm bg-surface" />
      <button class="px-3 py-1.5 rounded bg-accent/10 text-accent text-sm" onclick={fetchMarket}>手动抓取市场信号</button>
      {#if mktMsg}<span class="text-xs text-muted">{mktMsg}</span>{/if}
    </div>
    <table class="w-full text-sm">
      <thead><tr class="text-muted text-left"><th>任务</th><th>计划</th><th>下次</th><th>上次</th><th>状态</th><th></th></tr></thead>
      <tbody>
        {#each jobs as j}
          <tr class="border-t border-border">
            <td class="py-2">
              {j.name}
              {#if JOB_HELP[j.name]}
                <span
                  class="inline-flex items-center justify-center w-4 h-4 ml-1 rounded-full border border-border text-muted text-[10px] cursor-help align-middle"
                  title={JOB_HELP[j.name]}
                >?</span>
              {/if}
            </td>
            <td>{j.time_local} · {j.weekday_mask}</td>
            <td>{fmtTime(j.next_run_at)}</td>
            <td>{fmtTime(j.last_run_at)}</td>
            <td>{j.enabled ? '启用' : '停用'}</td>
            <td class="whitespace-nowrap text-right">
              {#if j.name === 'filings'}
                <input type="date" bind:value={filingsFrom} title="回补起始日（留空默认昨日）"
                  class="border border-border rounded px-1 py-0.5 text-xs bg-surface" />
                <input type="date" bind:value={filingsTo} title="回补结束日（留空则只拉单日）"
                  class="border border-border rounded px-1 py-0.5 text-xs bg-surface" />
              {/if}
              <button class="text-accent text-xs" disabled={runningName === j.name} onclick={() => runNow(j.name)}>立即运行</button>
            </td>
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
          <span class="text-muted">{fmtTime(r.started_at)} → {fmtTime(r.finished_at)}</span>
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
