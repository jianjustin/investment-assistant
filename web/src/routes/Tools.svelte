<script lang="ts">
  import { onDestroy, untrack } from 'svelte'
  import * as api from '../lib/api'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import { fmtTime } from '../lib/format'
  import Modal from '../lib/components/Modal.svelte'
  import FetchDateModal from '../lib/components/FetchDateModal.svelte'

  const taskName = (name:string) => name === 'us-research' ? '美股研究' : name
  let { sub = 'tasks' }: { sub?: string } = $props()
  // 旧 hash（ops/results）一律回落到任务中心
  const view = $derived(sub === 'runs' ? 'runs' : 'tasks')

  const JOB_HELP: Record<string, { goal: string; details: string[] }> = {
    ashares: {
      goal: '更新少量 A 股关注标的的研究数据，默认关闭调度。',
      details: [
        '使用 Asia/Shanghai 和已核实的 A 股交易日历；不使用 SPY/VIX 规则，不发送通知。',
        '行情默认最近400个自然日；财务最多8个报告期。失败项保留状态与旧值，独立提交成功数据。',
        '单证券窗口、复权与失败续跑请到「数据 → A 股研究数据」操作。',
      ],
    },
    metrics: {
      goal: '每个交易日早间更新市场环境与关注列表趋势。',
      details: [
        '拉取 SPY 收盘价与 200 日均线、VIX 恐慌指数，计算市场红绿灯信号（green / yellow / red）。',
        '对关注列表标的逐一扫描趋势状态（上升 / 震荡 / 下降），写入数据库，供看板与策略评分使用。',
        '支持「按日期运行」历史回补：用该日历史行情重算信号与快照（周末自动跳过）。',
      ],
    },
    filings: {
      goal: '自动跟踪关注列表公司的 SEC 信息披露。',
      details: [
        '从 SEC EDGAR 下载 10-Q / 10-K 等财报文件，按「标的 / 表单类型」归档到本地，并写入财报索引。',
        '定时运行默认拉取昨日（T-1）披露；也可点「按日期运行」回补历史。',
      ],
    },
    scores: {
      goal: '收盘后为关注列表标的计算「趋势相对强度」策略得分，作为研究证据。',
      details: [
        '加分制，满分 100：上升趋势 +30、均线多头排列 +20、跑赢 SPY +15、跑赢 QQQ +15、量能扩张 +10、宏观进攻状态 +10。',
        '例如 score=30 表示仅命中「上升趋势」一项；<40 视为弱、40–70 中等、≥70 强。',
        '分数只是证据汇总，不构成交易指令。',
      ],
    },
    event_study: {
      goal: '验证信号的历史有效性（事件研究）。',
      details: [
        '对三类事件——rs_strong（相对强度走强）、ma_reclaim（收复均线）、score_high（策略高分）——统计事件发生后 5 / 10 / 20 个交易日的收益分布。',
        '结果缓存到数据库，研究页直接读取。',
      ],
    },
  }

  const DATE_FETCH: Record<string, { description: string; defaultLabel: string }> = {
    ashares: { description: '更新现有 A 股关注列表；日期约束行情窗口，不代表严格历史 PIT。详细选项见 A 股研究数据页。', defaultLabel: '最近400个自然日' },
    metrics: { description: '按历史日期回补市场信号与关注列表快照（周末自动跳过）。', defaultLabel: '今日' },
    filings: { description: '从 SEC EDGAR 回补财报文件，按披露日匹配。', defaultLabel: '昨日（T-1）' },
    scores: { description: '按历史日期回补策略评分（基于该日快照，宏观取当前状态）。', defaultLabel: '今日' },
    event_study: { description: '重算事件研究：开始日为事件下界，结束日为 as-of。', defaultLabel: '默认（全量）' },
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
    <p class="text-xs text-muted">最近调度检查：{fmtTime(scheduler.meta.last_tick_at)}</p>
  {/if}
  {#if scheduler?.meta.tick_in_progress && scheduler.meta.tick_started_at}
    <p class="text-xs text-muted">本轮开始：{fmtTime(scheduler.meta.tick_started_at)}</p>
  {/if}
</div>
{#if loadError}<p role="alert" class="mb-3 text-sm text-danger">{loadError}。当前数据已保留，可刷新重试。</p>{/if}

{#if loading}
  <Skeleton />
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
              {#if JOB_HELP[j.name]}
                <button
                  class="inline-flex items-center justify-center w-4 h-4 ml-1 rounded-full border border-border text-muted text-[10px] align-middle hover:border-accent hover:text-accent transition-colors"
                  aria-label={`${j.name} 说明`}
                  onclick={() => helpJob = j.name}
                >?</button>
              {/if}
            </td>
            <td>{j.time_local} · {j.weekday_mask} · {j.timezone ?? '时区未配置'}</td>
            <td>{fmtTime(j.next_run_at)}</td>
            <td>{fmtTime(j.last_run_at)}</td>
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
      {#if helpJob && JOB_HELP[helpJob]}
        <p class="text-sm font-medium mb-3">{JOB_HELP[helpJob].goal}</p>
        <ul class="space-y-2 text-sm text-muted list-disc pl-4">
          {#each JOB_HELP[helpJob].details as d}
            <li>{d}</li>
          {/each}
        </ul>
      {/if}
    </Modal>
    <p class="text-xs text-muted">改运行时间 / 开关请到「设置 · 定时任务」。</p>
  </div>
{:else}
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <select aria-label="筛选任务" bind:value={filterTask} onchange={load} class="text-sm border border-border rounded px-2 py-1 bg-surface">
        <option value="">全部</option><option value="metrics">metrics</option>
        <option value="filings">filings</option><option value="scores">scores</option>
        <option value="event_study">event_study</option>
        <option value="ashares">ashares</option>
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
            <td>{fmtTime(r.started_at)}</td>
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
          <div>开始：{fmtTime(detailReport.started_at)} · 结束：{fmtTime(detailReport.finished_at)}</div>
          <div>指定日期：{fmtTargetDates(detailReport)} · 触发：{detailReport.trigger_source === 'manual' ? '手动' : '定时'}</div>
        </div>
        <pre class="text-xs overflow-auto max-h-96 bg-surface-2 rounded p-2">{JSON.stringify(detailReport.summary, null, 2)}</pre>
      {/if}
    </Modal>
  </div>
{/if}
