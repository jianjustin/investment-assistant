<script lang="ts">
  import { onDestroy, untrack } from 'svelte'
  import * as api from '../lib/api'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import { fmtBeijing, weekdayText } from '../lib/format'
  import Modal from '../lib/components/Modal.svelte'
  import FetchDateModal from '../lib/components/FetchDateModal.svelte'
  import FilingRecords from '../lib/components/FilingRecords.svelte'

  const taskName = (name:string) => name === 'us-research' ? '美股研究' : name
  let { sub = 'tasks' }: { sub?: string } = $props()
  // 旧 hash（ops/results）一律回落到任务中心
  const view = $derived(sub === 'runs' ? 'runs' : sub === 'filings' ? 'filings' : 'tasks')

  const DATE_FETCH: Record<string, { description: string; defaultLabel: string }> = {
    filings: { description: '从 SEC EDGAR 回补财报文件，按披露日匹配。', defaultLabel: '昨日（T-1）' },
  }

  let helpJob = $state<string | null>(null)
  let dateJob = $state<string | null>(null)
  let jobs = $state<any[]>([])
  let reports = $state<any[]>([])
  let detailReport = $state<any | null>(null)
  let loading = $state(true)
  let runningName = $state<string | null>(null)
  let filterTask = $state<string>('')
  let actionMsg = $state('')
  let scheduler = $state<api.SchedulerStatus | null>(null)
  let loadError = $state('')
  let refreshing = $state(false)
  let inFlight = false
  let inFlightView = ''
  let inFlightFilter = ''
  let reloadAfterCurrent = false
  let disposed = false

  const schedulerLabel = $derived.by(() => {
    if (!scheduler) return '调度状态待确认'
    if (!scheduler.meta.enabled) return '自动调度已关闭'
    if (scheduler.meta.tick_in_progress) {
      if (scheduler.meta.last_tick_failed) return '自动调度重试中'
      return scheduler.status === 'degraded' ? '本轮调度仍在执行' : '自动调度正在执行'
    }
    if (scheduler.status === 'down' || scheduler.meta.last_tick_failed) return '自动调度异常'
    if (!scheduler.meta.last_tick_at && !scheduler.meta.tick_started_at) return '自动调度等待首次检查'
    return scheduler.status === 'up' ? '自动调度运行中' : '自动调度异常'
  })

  async function load() {
    const requestedView = view
    const requestedFilter = filterTask
    if (inFlight) {
      if (requestedView !== inFlightView || requestedFilter !== inFlightFilter) reloadAfterCurrent = true
      return
    }
    inFlight = true
    inFlightView = requestedView
    inFlightFilter = requestedFilter
    refreshing = true
    try {
      const [scheduledResult, reportsResult] = await Promise.allSettled([
        api.getScheduledJobs(),
        requestedView === 'runs' ? api.getJobReports(requestedFilter || undefined, 50) : Promise.resolve(null),
      ])
      if (disposed) return
      const errors: string[] = []
      if (scheduledResult.status === 'fulfilled') {
        scheduler = scheduledResult.value.scheduler ?? null
        if (scheduledResult.value.degraded) errors.push('定时任务数据暂不可用')
        else jobs = scheduledResult.value.jobs
      } else {
        errors.push(`调度状态读取失败：${scheduledResult.reason?.message ?? scheduledResult.reason}`)
      }
      if (reportsResult.status === 'fulfilled') {
        if (reportsResult.value && requestedView === view && requestedFilter === filterTask) {
          if (reportsResult.value.degraded) errors.push('运行记录数据暂不可用')
          else reports = reportsResult.value.reports
        }
      } else {
        errors.push(`运行记录读取失败：${reportsResult.reason?.message ?? reportsResult.reason}`)
      }
      if (requestedView === view && requestedFilter === filterTask) loadError = errors.join('；')
    } finally {
      inFlight = false
      if (!disposed) {
        refreshing = false
        loading = false
        if (reloadAfterCurrent) {
          reloadAfterCurrent = false
          void load()
        }
      }
    }
  }

  async function runNow(name: string) {
    runningName = name
    try { await api.runJob(name) } finally { runningName = null; await load() }
  }

  async function submitDated(payload: Record<string, string>) {
    const name = dateJob
    dateJob = null
    if (!name) return
    try {
      const r = await api.runJob(name, payload)
      actionMsg = `${name} 已提交（${r.run_id}），结果见「运行记录」`
    } catch (e: any) {
      actionMsg = `${name} 提交失败：${e?.message ?? e}`
    }
  }

  function fmtTargetDates(r: any): string {
    if (!r.target_start_date) return '—'
    if (!r.target_end_date || r.target_end_date === r.target_start_date) return r.target_start_date
    return `${r.target_start_date} ~ ${r.target_end_date}`
  }

  function fmtDuration(r: any): string {
    if (!r.started_at || !r.finished_at) return '—'
    const s = (new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000
    return `${s.toFixed(1)}s`
  }

  $effect(() => {
    const activeView = view
    untrack(() => { void load() })
    if (activeView === 'runs') {
      const timer = setInterval(() => { void load() }, 15_000)
      return () => clearInterval(timer)
    }
  })

  onDestroy(() => { disposed = true })
</script>

<div class="mb-4 space-y-2 rounded border border-border bg-surface p-3 text-sm" role="status">
  <div class="flex items-center justify-between gap-3">
    <p class:text-success={scheduler?.status === 'up'} class:text-warn={scheduler?.status !== 'up'} class="font-medium">{schedulerLabel}</p>
    <button class="text-accent text-xs" disabled={refreshing} onclick={load}>{refreshing ? '刷新中…' : '刷新'}</button>
  </div>
  <p class="text-xs text-muted">{scheduler?.detail ?? (loading ? '正在读取调度状态…' : '服务未返回调度状态，请刷新后重试。')}</p>
  {#if scheduler && !scheduler.meta.enabled}
    <p class="text-xs text-muted">总开关关闭时，已启用的任务也不会自动运行。</p>
  {/if}
  {#if scheduler?.meta.last_tick_at}
    <p class="text-xs text-muted">最近调度检查：{fmtBeijing(scheduler.meta.last_tick_at)}</p>
  {/if}
  {#if scheduler?.meta.tick_in_progress && scheduler.meta.tick_started_at}
    <p class="text-xs text-muted">本轮开始：{fmtBeijing(scheduler.meta.tick_started_at)}</p>
  {/if}
</div>
{#if loadError}<p role="alert" class="mb-3 text-sm text-danger">{loadError}。当前数据已保留，可刷新重试。</p>{/if}

{#if loading && view !== 'filings'}
  <Skeleton />
{:else if view === 'filings'}
  <h2 class="mb-3 text-lg font-semibold">SEC 文件</h2>
  <FilingRecords />
{:else if view === 'tasks'}
  <div class="space-y-4">
    {#if actionMsg}<p class="text-xs text-muted">{actionMsg}</p>{/if}
    <table class="w-full text-sm">
      <thead><tr class="text-muted text-left"><th>任务</th><th>计划</th><th>下次</th><th>上次</th><th>状态</th><th></th></tr></thead>
      <tbody>
        {#each jobs as j}
          <tr class="border-t border-border">
            <td class="py-2">
              {j.name}
              {#if j.description}
                <button
                  class="inline-flex items-center justify-center w-4 h-4 ml-1 rounded-full border border-border text-muted text-[10px] align-middle hover:border-accent hover:text-accent transition-colors"
                  aria-label={`${j.name} 说明`}
                  onclick={() => helpJob = j.name}
                >?</button>
              {/if}
            </td>
            <td>
              {#if j.timezone === 'Asia/Shanghai'}
                {j.time_local} 北京 · {weekdayText(j.weekday_mask)}
              {:else}
                {j.time_local} · {weekdayText(j.weekday_mask)} · {j.timezone ?? '时区未配置'}（非北京时区）
              {/if}
            </td>
            <td>{fmtBeijing(j.next_run_at)}</td>
            <td>{fmtBeijing(j.last_run_at)}</td>
            <td>{j.enabled ? '任务启用' : '任务停用'}</td>
            <td class="whitespace-nowrap text-right space-x-3">
              <button class="text-accent text-xs" onclick={() => dateJob = j.name}>按日期运行</button>
              <button class="text-accent text-xs" disabled={runningName === j.name} onclick={() => runNow(j.name)}>立即运行</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>

    <FetchDateModal
      open={dateJob !== null}
      title={`${dateJob ?? ''} · 按日期运行`}
      description={dateJob ? (DATE_FETCH[dateJob]?.description ?? '') : ''}
      defaultLabel={dateJob ? (DATE_FETCH[dateJob]?.defaultLabel ?? '默认') : '默认'}
      defaultPayload={{}}
      maxRangeDays={92}
      onConfirm={submitDated}
      onclose={() => dateJob = null}
    />

    <Modal open={helpJob !== null} title={`${helpJob} · 任务说明`} onclose={() => helpJob = null}>
      {#if helpJob && jobs.find((j) => j.name === helpJob)?.description}
        {@const info = jobs.find((j) => j.name === helpJob)!.description}
        <p class="text-sm font-medium mb-3">{info.goal}</p>
        <ul class="space-y-2 text-sm text-muted list-disc pl-4">
          {#each info.details as d}
            <li>{d}</li>
          {/each}
        </ul>
        <p class="mt-3 text-xs text-muted">手动运行：{info.manual_note}</p>
      {/if}
    </Modal>
    <p class="text-xs text-muted">改运行时间 / 开关请到「设置 · 定时任务」。</p>
  </div>
{:else}
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <select aria-label="筛选任务" bind:value={filterTask} onchange={load} class="text-sm border border-border rounded px-2 py-1 bg-surface">
        <option value="">全部</option><option value="filings">filings</option>
        <option value="workbench">workbench</option><option value="workbench_review">workbench_review</option>
        <option value="us-research">美股研究</option>
      </select>
      <span class="text-xs text-muted">每 15 秒自动刷新</span>
    </div>
    <table class="w-full text-sm">
      <thead>
        <tr class="text-muted text-left">
          <th>任务</th><th>状态</th><th>触发</th><th>运行时间</th><th>耗时</th><th>指定日期</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each reports as r}
          <tr class="border-t border-border">
            <td class="py-2 font-medium">{taskName(r.task)}</td>
            <td><StatusPill status={r.status} /></td>
            <td>{r.trigger_source === 'manual' ? '手动' : '定时'}</td>
            <td>{fmtBeijing(r.started_at)}</td>
            <td>{fmtDuration(r)}</td>
            <td>{fmtTargetDates(r)}</td>
            <td class="text-right"><button class="text-accent text-xs" onclick={() => detailReport = r}>详情</button></td>
          </tr>
        {:else}
          <tr><td colspan="7" class="py-4 text-muted text-sm">暂无运行记录</td></tr>
        {/each}
      </tbody>
    </table>

    <Modal open={detailReport !== null} title={`${taskName(detailReport?.task ?? '')} · 运行详情`} onclose={() => detailReport = null}>
      {#if detailReport}
        <div class="text-xs text-muted mb-2 space-y-1">
          <div>run_id：{detailReport.run_id}</div>
          <div>开始：{fmtBeijing(detailReport.started_at)} · 结束：{fmtBeijing(detailReport.finished_at)}</div>
          <div>指定日期：{fmtTargetDates(detailReport)} · 触发：{detailReport.trigger_source === 'manual' ? '手动' : '定时'}</div>
        </div>
        <pre class="text-xs overflow-auto max-h-96 bg-surface-2 rounded p-2">{JSON.stringify(detailReport.summary, null, 2)}</pre>
      {/if}
    </Modal>
  </div>
{/if}
