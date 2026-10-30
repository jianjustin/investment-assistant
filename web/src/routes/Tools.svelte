<script lang="ts">
  import { onDestroy, untrack } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import * as Card from '$lib/ui/card/index'
  import DataTable from '$lib/ui/data-table/DataTable.svelte'
  import type { Column } from '$lib/ui/data-table/types'
  import * as Dialog from '$lib/ui/dialog/index'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import TabNav from '$lib/ui/tab-nav/TabNav.svelte'
  import * as api from '../lib/api'
  import { fmtBeijing, todayLocalISO, weekdayText } from '../lib/format'
  import FetchDateModal from '../lib/components/FetchDateModal.svelte'
  import FilingRecords from '../lib/components/FilingRecords.svelte'
  import RunDetail from '../lib/components/RunDetail.svelte'
  import { newRequestId } from '../lib/workbench'
  import { RUN_ID_RE, RESUME_ERROR_TEXT, TRIGGER_TEXT, runHref } from '../lib/runs'

  const taskName = (name:string) => name === 'us-research' ? '美股研究' : name
  let { sub = 'tasks' }: { sub?: string } = $props()
  // 旧 hash（ops/results）一律回落到任务中心；runs/<run_id> 是运行详情页（run_id 格式不对时回落到运行记录）
  const detailRunId = $derived(sub.startsWith('runs/') && RUN_ID_RE.test(sub.slice(5)) ? sub.slice(5) : null)
  const view = $derived(detailRunId ? 'detail' : sub === 'runs' || sub.startsWith('runs/') ? 'runs'
    : sub === 'filings' ? 'filings' : 'tasks')

  // 只有 sec_backfill 能按日期运行（每日工作流不接受日期，v2.8 §4.8）
  const DATE_FETCH: Record<string, { description: string; defaultLabel: string }> = {
    sec_backfill: { description: '按日期回补观察名单的 SEC 申报，与每日工作流的 SEC 监控同一套扫描、归档与去重。', defaultLabel: '昨日（T-1）' },
  }
  const yesterdayLocalISO = () => {
    const d = new Date(todayLocalISO() + 'T00:00:00')
    d.setDate(d.getDate() - 1)
    const p = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  }
  // 旧任务名只读保留（job_reports.task 的历史值），选项带后缀
  const TASK_FILTERS: [string, string][] = [
    ['daily', 'daily'], ['sec_backfill', 'sec_backfill'], ['us-research', '美股研究'],
    ['filings', 'filings（v2.7 及以前）'], ['workbench', 'workbench（v2.7 及以前）'],
    ['workbench_review', 'workbench_review（v2.7 及以前）'],
  ]

  let helpJob = $state<string | null>(null)
  let dateJob = $state<string | null>(null)
  let jobs = $state<any[]>([])
  let reports = $state<any[]>([])
  let loading = $state(true)
  let runningName = $state<string | null>(null)
  let filterTask = $state<string>('')
  let actionMsg = $state('')
  let dailyRunId = $state<string | null>(null)
  let dailyRequestId: string | null = null     // 失败后重试沿用同一个 request_id
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
    actionMsg = ''
    try {
      if (name === 'daily') {
        dailyRequestId ??= newRequestId()
        const r = await api.runDaily(dailyRequestId)
        dailyRequestId = null
        const id = r.daily_run_id ?? r.run_id
        actionMsg = `daily 已提交（${id}），进度见「运行记录」`
        dailyRunId = id
      } else {
        await api.runJob(name)
      }
    } catch (e: any) {
      // 409 daily_running 等：把错误码换成中文，其余照原文
      const code = e instanceof api.ApiError ? e.code : null
      actionMsg = `${name} 提交失败：${(code && RESUME_ERROR_TEXT[code]) || e?.message || e}`
    } finally { runningName = null; await load() }
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
    if (!r.target_start_date) return '未指定'
    if (!r.target_end_date || r.target_end_date === r.target_start_date) return r.target_start_date
    return `${r.target_start_date} ~ ${r.target_end_date}`
  }

  function fmtDuration(r: any): string {
    if (!r.started_at || !r.finished_at) return '未记录'
    const s = (new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000
    return `${s.toFixed(1)}s`
  }

  $effect(() => {
    const activeView = view
    if (activeView !== 'detail') untrack(() => { void load() })
    if (activeView === 'runs') {
      const timer = setInterval(() => { void load() }, 15_000)
      return () => clearInterval(timer)
    }
  })

  onDestroy(() => { disposed = true })

  const SELECT = 'h-8 rounded-md border border-input bg-card px-2 text-sm text-foreground'
  const planText = (j: any) => j.manual_only ? '只手动'
    : j.timezone === 'Asia/Shanghai' ? `${j.time_local} 北京 · ${weekdayText(j.weekday_mask)}`
    : `${j.time_local} · ${weekdayText(j.weekday_mask)} · ${j.timezone ?? '时区未配置'}（非北京时区）`
  const jobColumns: Column<any>[] = [
    { key: 'name', header: '任务', cell: jobName },
    { key: 'plan', header: '计划', value: planText },
    { key: 'next', header: '下次', value: j => (j.next_run_at ? fmtBeijing(j.next_run_at) : '无') },
    { key: 'last', header: '上次', value: j => (j.last_run_at ? fmtBeijing(j.last_run_at) : '从未运行') },
    { key: 'state', header: '状态', value: j => (j.manual_only ? '只手动' : j.enabled ? '任务启用' : '任务停用') },
    { key: 'actions', header: '操作', cell: jobActions },
  ]
  const reportColumns: Column<any>[] = [
    { key: 'task', header: '任务', value: r => taskName(r.task) },
    { key: 'status', header: '状态', cell: reportStatus },
    { key: 'trigger', header: '触发', value: r => TRIGGER_TEXT[r.trigger_source] ?? r.trigger_source ?? '定时' },
    { key: 'started', header: '运行时间', value: r => fmtBeijing(r.started_at) },
    { key: 'duration', header: '耗时', align: 'num', value: fmtDuration },
    { key: 'dates', header: '指定日期', value: fmtTargetDates },
    { key: 'detail', header: '详情', cell: reportLink },
  ]
  const tabs = $derived([
    { href: '#tools/tasks', label: '任务中心', current: view === 'tasks' },
    { href: '#tools/runs', label: '运行记录', current: view === 'runs' },
    { href: '#tools/filings', label: 'SEC 文件', current: view === 'filings' },
  ])
</script>

{#snippet jobName(j: any)}{j.name}{#if j.description}<Button variant="ghost" size="icon" class="ml-1 size-5 align-middle"
    aria-label={`${j.name} 说明`} onclick={() => helpJob = j.name}><Icon name="info" /></Button>{/if}{/snippet}
{#snippet jobActions(j: any)}
  <span class="inline-flex justify-end">
    {#if DATE_FETCH[j.name]}
      <Button variant="link" size="sm" class="text-xs" onclick={() => dateJob = j.name}>按日期运行</Button>
    {:else if !j.manual_only}
      <Button variant="link" size="sm" class="text-xs" busy={runningName === j.name} onclick={() => runNow(j.name)}>立即运行</Button>
    {/if}
  </span>
{/snippet}
{#snippet reportStatus(r: any)}<StatusPill domain="run" value={r.status} />{/snippet}
{#snippet reportLink(r: any)}
  {#if RUN_ID_RE.test(String(r.run_id ?? ''))}
    <a class="text-xs text-primary underline" href={runHref(r.run_id)}>详情</a>
  {:else}<span class="text-xs text-muted-foreground">无详情</span>{/if}
{/snippet}

{#if view === 'detail' && detailRunId}
  {#key detailRunId}<RunDetail runId={detailRunId} />{/key}
{:else}
<div class="grid gap-4">
<TabNav label="工具" items={tabs} />
<Card.Root size="sm" role="status" class="text-sm">
  <Card.Content class="grid gap-2">
    <div class="flex items-center justify-between gap-3">
      <StatusPill domain="system" value={scheduler?.status ?? 'unknown'} text={schedulerLabel} />
      <Button size="sm" busy={refreshing} busyText="刷新中…" onclick={load}>刷新</Button>
    </div>
    <p class="text-xs text-muted-foreground">{scheduler?.detail ?? (loading ? '正在读取调度状态…' : '服务未返回调度状态，请刷新后重试。')}</p>
    {#if scheduler && !scheduler.meta.enabled}
      <p class="text-xs text-muted-foreground">总开关关闭时，已启用的任务也不会自动运行。</p>
    {/if}
    {#if scheduler?.meta.last_tick_at}
      <p class="text-xs text-muted-foreground">最近调度检查：{fmtBeijing(scheduler.meta.last_tick_at)}</p>
    {/if}
    {#if scheduler?.meta.tick_in_progress && scheduler.meta.tick_started_at}
      <p class="text-xs text-muted-foreground">本轮开始：{fmtBeijing(scheduler.meta.tick_started_at)}</p>
    {/if}
  </Card.Content>
</Card.Root>
{#if loadError}
  <Alert variant="danger"><Icon name="circle-x" /><AlertDescription>{loadError}。当前数据已保留，可刷新重试。</AlertDescription></Alert>
{/if}

{#if loading && view !== 'filings'}
  <DataBlock state="loading" skeleton="table" />
{:else if view === 'filings'}
  <h2 class="text-lg font-medium">SEC 文件</h2>
  <FilingRecords />
{:else if view === 'tasks'}
  <div class="grid gap-4">
    {#if actionMsg}
      <p class="text-xs text-muted-foreground">{actionMsg}
        {#if dailyRunId && RUN_ID_RE.test(dailyRunId) && actionMsg.startsWith('daily 已提交')}
          <a class="text-primary underline" href={runHref(dailyRunId)}>运行详情</a>
        {/if}
      </p>
    {/if}
    {#if jobs.length}
      <DataTable columns={jobColumns} rows={jobs} rowKey={j => j.name} ariaLabel="任务中心" />
    {:else}
      <DataBlock state="empty" message="没有已注册的任务" />
    {/if}

    <FetchDateModal
      open={dateJob !== null}
      title={`${dateJob ?? ''} · 按日期运行`}
      description={dateJob ? (DATE_FETCH[dateJob]?.description ?? '') : ''}
      defaultLabel={dateJob ? (DATE_FETCH[dateJob]?.defaultLabel ?? '默认') : '默认'}
      defaultPayload={{ date: yesterdayLocalISO() }}
      maxRangeDays={92}
      onConfirm={submitDated}
      onclose={() => dateJob = null}
    />

    <Dialog.Root open={helpJob !== null} onOpenChange={(next) => { if (!next) helpJob = null }}>
      <Dialog.Content>
        <Dialog.Header>
          <Dialog.Title>{helpJob} · 任务说明</Dialog.Title>
        </Dialog.Header>
        {#if helpJob && jobs.find((j) => j.name === helpJob)?.description}
          {@const info = jobs.find((j) => j.name === helpJob)!.description}
          <p class="text-sm font-medium">{info.goal}</p>
          <ul class="list-disc space-y-2 pl-4 text-sm text-muted-foreground">
            {#each info.details as d}
              <li>{d}</li>
            {/each}
          </ul>
          <p class="text-xs text-muted-foreground">手动运行：{info.manual_note}</p>
        {/if}
      </Dialog.Content>
    </Dialog.Root>
    <p class="text-xs text-muted-foreground">改运行时间 / 开关请到「设置 · 定时任务」。</p>
  </div>
{:else}
  <div class="grid gap-3">
    <div class="flex items-center gap-3">
      <select aria-label="筛选任务" bind:value={filterTask} onchange={load} class={SELECT}>
        <option value="">全部</option>
        {#each TASK_FILTERS as [value, label] (value)}<option {value}>{label}</option>{/each}
      </select>
      <span class="text-xs text-muted-foreground">每 15 秒自动刷新</span>
    </div>
    {#if reports.length}
      <DataTable columns={reportColumns} rows={reports} rowKey={(r) => r.run_id ?? `${r.task}-${r.started_at}`} ariaLabel="运行记录" />
    {:else}
      <DataBlock state="empty" message="暂无运行记录" />
    {/if}
  </div>
{/if}
</div>
{/if}
