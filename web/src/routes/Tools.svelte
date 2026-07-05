<script lang="ts">
  import * as api from '../lib/api'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import LineChart from '../lib/charts/LineChart.svelte'
  import { fmtTime, todayLocalISO } from '../lib/format'
  import Modal from '../lib/components/Modal.svelte'
  import FetchDateModal from '../lib/components/FetchDateModal.svelte'

  let { sub = 'tasks' }: { sub?: string } = $props()

  const JOB_HELP: Record<string, { goal: string; details: string[] }> = {
    metrics: {
      goal: '每个交易日早间更新市场环境与关注列表趋势。',
      details: [
        '拉取 SPY 收盘价与 200 日均线、VIX 恐慌指数，计算市场红绿灯信号（green / yellow / red）。',
        '对关注列表标的逐一扫描趋势状态（上升 / 震荡 / 下降），写入数据库，供看板与策略评分使用。',
      ],
    },
    filings: {
      goal: '自动跟踪关注列表公司的 SEC 信息披露。',
      details: [
        '从 SEC EDGAR 下载 10-Q / 10-K 等财报文件，按「标的 / 表单类型」归档到本地。',
        '定时运行默认拉取昨日（T-1）披露；也可点任务行的「按日期拉取」回补历史。',
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

  let helpJob = $state<string | null>(null)

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

  // 手动抓取市场信号 / filings 回补：弹窗选日期
  let mktModalOpen = $state(false)
  let filingsModalOpen = $state(false)
  let actionMsg = $state('')

  async function fetchMarket(payload: Record<string, string>) {
    mktModalOpen = false
    actionMsg = '市场信号抓取中…'
    try {
      const r: any = await api.fetchMarketSignals(payload)
      const ok = r?.rows?.length ?? 0
      const bad = r?.failures?.length ?? 0
      actionMsg = `市场信号完成：成功 ${ok} 天${bad ? `，失败 ${bad} 天` : ''}`
    } catch (e: any) {
      actionMsg = `市场信号抓取失败：${e?.message ?? e}`
    }
  }

  async function submitFilings(payload: Record<string, string>) {
    filingsModalOpen = false
    try {
      const r = await api.runJob('filings', payload)
      actionMsg = `filings 回补已提交（${r.run_id}），结果见「运行记录」`
    } catch (e: any) {
      actionMsg = `filings 回补提交失败：${e?.message ?? e}`
    }
  }

  $effect(() => { sub; load() })
</script>

{#if loading}
  <Skeleton />
{:else if sub === 'tasks'}
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <button class="px-3 py-1.5 rounded bg-accent/10 text-accent text-sm" onclick={() => mktModalOpen = true}>手动抓取市场信号</button>
      {#if actionMsg}<span class="text-xs text-muted">{actionMsg}</span>{/if}
    </div>
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
              {#if j.name === 'filings'}
                <button class="text-accent text-xs" onclick={() => filingsModalOpen = true}>按日期拉取</button>
              {/if}
              <button class="text-accent text-xs" disabled={runningName === j.name} onclick={() => runNow(j.name)}>立即运行</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>

    <FetchDateModal
      open={mktModalOpen}
      title="手动抓取市场信号"
      description="按日期计算并保存市场红绿灯信号（SPY / VIX）。"
      defaultLabel="今日"
      defaultPayload={{ date: todayLocalISO() }}
      maxRangeDays={30}
      onConfirm={fetchMarket}
      onclose={() => mktModalOpen = false}
    />

    <FetchDateModal
      open={filingsModalOpen}
      title="filings · 按日期拉取"
      description="从 SEC EDGAR 回补财报文件，按披露日匹配。"
      defaultLabel="昨日（T-1）"
      defaultPayload={{}}
      maxRangeDays={92}
      onConfirm={submitFilings}
      onclose={() => filingsModalOpen = false}
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
