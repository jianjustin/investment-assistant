<script lang="ts">
  import * as api from '../lib/api'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import { fmtTime } from '../lib/format'
  import Modal from '../lib/components/Modal.svelte'
  import FetchDateModal from '../lib/components/FetchDateModal.svelte'

  let { sub = 'tasks' }: { sub?: string } = $props()
  // 旧 hash（ops/results）一律回落到任务中心
  const view = $derived(sub === 'runs' ? 'runs' : 'tasks')

  const JOB_HELP: Record<string, { goal: string; details: string[] }> = {
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

  async function loadTasks() { jobs = (await api.getScheduledJobs()).jobs }
  async function loadRuns() { reports = (await api.getJobReports(filterTask || undefined, 50)).reports }

  async function load() {
    loading = true
    try {
      if (view === 'tasks') await loadTasks()
      else await loadRuns()
    } finally { loading = false }
  }

  async function runNow(name: string) {
    runningName = name
    try { await api.runJob(name) } finally { runningName = null; await loadTasks() }
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

  $effect(() => { view; load() })
</script>

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
            <td>{j.time_local} · {j.weekday_mask}</td>
            <td>{fmtTime(j.next_run_at)}</td>
            <td>{fmtTime(j.last_run_at)}</td>
            <td>{j.enabled ? '启用' : '停用'}</td>
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
    <select bind:value={filterTask} onchange={loadRuns} class="text-sm border border-border rounded px-2 py-1 bg-surface">
      <option value="">全部</option><option value="metrics">metrics</option>
      <option value="filings">filings</option><option value="scores">scores</option>
      <option value="event_study">event_study</option>
    </select>
    <table class="w-full text-sm">
      <thead>
        <tr class="text-muted text-left">
          <th>任务</th><th>状态</th><th>触发</th><th>运行时间</th><th>耗时</th><th>指定日期</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each reports as r}
          <tr class="border-t border-border">
            <td class="py-2 font-medium">{r.task}</td>
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

    <Modal open={detailReport !== null} title={`${detailReport?.task ?? ''} · 运行详情`} onclose={() => detailReport = null}>
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
