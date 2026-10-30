<script lang="ts">
  import { onMount } from 'svelte'
  import PlanTable from '../lib/components/PlanTable.svelte'
  import RunOverview from '../lib/components/RunOverview.svelte'
  import * as api from '../lib/api'
  import * as tl from '../lib/timeline'
  import * as wb from '../lib/workbench'

  // 「今日」（spec §10.1）：运行一览 → 筛选 → 市场环境 → 计划表 → 其他触发。
  // 计划表自己取数（GET /plan-table，可选日期与扩展池），不依赖批处理视图；没有任何决定按钮。
  let view = $state<wb.TodayView | null>(null)
  let error = $state('')
  let loading = $state(true)
  let notice = $state('')
  let generation = 0
  let screenExpanded = $state(false)
  let screenFull = $state<wb.ScreenReport | null>(null)
  let screenError = $state('')

  // 计划表：session 为空 = 后端缺省（最近一个已收盘交易日）
  let table = $state<wb.PlanTableView | null>(null)
  let tableError = $state('')
  let tableLoading = $state(true)
  let session = $state('')
  let includeExtended = $state(false)
  let tableGeneration = 0
  let rechecks = $state<Record<string, { busy: boolean; text: string }>>({})

  async function expandScreen() {
    if (!view || !view.screen) return
    screenExpanded = true
    screenError = ''
    try {
      const out = await wb.getScreen(view.session, true)
      screenFull = out.report
    } catch (e) {
      screenError = String((e as Error)?.message ?? e)
    }
  }

  const REVIEW_FALLBACK: Record<string, string> = { conflict: '冲突 / 回避', watch: '等待触发' }

  const reviewText = (t: wb.ScreenTrigger): string => {
    if (t.review === 'plan' && t.plan) {
      const shares = t.plan.shares != null ? `建议 ${t.plan.shares} 股`
        : t.plan.sizing_status === 'no_equity' ? '缺资金快照，无法计算股数' : '无建议股数'
      return `入场 ${t.plan.entry_low}–${t.plan.entry_high} · 止损 ${t.plan.stop} · T1 ${t.plan.target1} · ${shares}`
    }
    if (t.review === 'invalid') return `作废 ${t.invalid_reasons.join('、')}`
    return REVIEW_FALLBACK[t.review] ?? t.review
  }

  async function load() {
    const token = ++generation
    loading = true
    try {
      const next = await wb.getToday()
      if (token !== generation) return
      view = next
      error = ''
    } catch (e) {
      if (token === generation) { error = wb.describeError(e); view = null }
    } finally {
      if (token === generation) loading = false
    }
  }

  async function loadTable() {
    const token = ++tableGeneration
    tableLoading = true
    try {
      const next = await wb.getPlanTable(session || undefined, includeExtended)
      if (token !== tableGeneration) return
      table = next
      tableError = ''
    } catch (e) {
      if (token === tableGeneration) { tableError = wb.describeError(e); table = null }
    } finally {
      if (token === tableGeneration) tableLoading = false
    }
  }

  async function recheck(row: wb.PlanTableRow) {
    if (!row.chain || rechecks[row.row_id]?.busy) return
    const { signal_date } = row.chain
    rechecks[row.row_id] = { busy: true, text: '复查中…' }
    try {
      const started = await api.recheckChain(row.ticker, signal_date)
      const done = await api.pollRun(started.run_id, { timeoutMs: tl.RECHECK_POLL_MS })
      rechecks[row.row_id] = { busy: false, text: tl.recheckDoneText(done) }
      if (done.status === 'done') await loadTable()
    } catch (e) {
      // 轮询超时不是失败：后台仍在复查，按钮保持不可点，提示稍后刷新（再点会 409 review_in_progress）。
      rechecks[row.row_id] = tl.isRunTimeout(e) ? { busy: true, text: tl.RECHECK_PENDING_TEXT }
        : { busy: false, text: e instanceof wb.WorkbenchError && e.status === 409
            ? `不能重新复查：${tl.recheckConflictText(e.message)}` : wb.describeError(e) }
    }
  }

  // 备注（spec §6.5）：作用于一条链，或一份非链计划；写成功后刷新计划表。
  async function addNote(row: wb.PlanTableRow, body: string, requestId: string) {
    const target = row.chain
      ? { ticker: row.ticker, chain_signal_date: row.chain.signal_date }
      : { plan_id: row.plan?.plan_id ?? row.baseline?.plan_id }
    if (!row.chain && !target.plan_id) throw new Error('这一行没有可挂备注的计划')
    await wb.postPlanNote({ request_id: requestId, body, ...target } as wb.PlanNoteBody)
    await loadTable()
  }

  async function runNow() {
    try {
      const run = await wb.runWorkbench()
      notice = `已提交批处理（${run.run_id}），完成后刷新本页查看。`
    } catch (e) {
      notice = wb.describeError(e)
    }
  }

  async function repush() {
    try {
      const out = await wb.pushToday()
      notice = out.sent ? `已推送 ${out.messages} 条` : `未推送：${out.reason ?? '未知原因'}`
    } catch (e) {
      notice = `推送失败：${wb.describeError(e)}`
    }
  }

  const pctText = (value: number | null | undefined) =>
    value == null ? '—' : `${(value * 100).toFixed(1)}%`
  // No stored value: tell a missing key from a failed fetch (status recorded in the snapshot inputs).
  const fredMissing = (m: wb.MarketContext) => {
    const status = Object.values(m.inputs?.macro_status ?? {})
    if (status.length && status.every(s => s === 'not_configured')) return 'FRED 未配置'
    if (status.includes('error')) return 'FRED 采集失败（见运行报告）'
    return 'FRED 无数据'
  }
  const fredText = (m: wb.MarketContext) =>
    Object.values(m.macro ?? {}).every(v => v == null)
      ? fredMissing(m)
      : Object.entries(m.macro ?? {}).map(([series, view]) =>
          view == null ? `${series} 无数据` : `${series} ${view.value}（20 期 ${view.change == null ? '无变化' : (Number(view.change) >= 0 ? '+' : '') + view.change}）`).join(' · ')

  const otherLine = (u: wb.Unit) => [
    `${u.ticker} · ${u.signal_date}`, `建议${wb.ACTION_LABELS[u.proposed_action] ?? u.proposed_action}`,
    ...(u.labels ?? []).map(l => wb.UNIT_LABELS[l] ?? l),
    (u.rule_ids ?? []).map(wb.ruleLabel).join('、'),
    u.brief && u.brief.status !== 'error' ? (u.brief.output?.summary ?? '') : '',
  ].filter(Boolean).join(' · ')

  onMount(() => {
    void load()
    void loadTable()
  })
</script>

<section class="space-y-4">
  <header class="flex items-center justify-between">
    <div>
      <h1 class="text-lg font-semibold">今日</h1>
      {#if table || view}<p class="text-xs text-muted">最近收盘交易日 {table?.session ?? view?.session} · 信号仅为研究候选，不会自动下单</p>{/if}
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <button class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2" onclick={runNow}>立即运行批处理</button>
      <button class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2" onclick={repush}>重新推送今日计划</button>
    </div>
  </header>
  {#if notice}<p class="text-xs text-muted">{notice}</p>{/if}

  <!-- v2.6 §7.5：运行一览在最顶部（筛选、市场环境之前）；自己取数，不依赖下面的批处理视图 -->
  <RunOverview />

  {#if view}
    <section class="border border-border rounded p-3 bg-surface text-sm" aria-label="筛选">
      {#if view.screen}
        {@const sc = view.screen}
        <h2 class="font-semibold">筛选 <span class="text-xs px-1.5 py-0.5 rounded bg-accent/10 text-accent">{sc.calc_version}</span></h2>
        {#if sc.status === 'error'}
          <p>筛选未运行：{sc.error}</p>
          <p class="text-xs text-muted">沿用成员 {sc.members} 只</p>
        {:else}
          {@const counts = sc.counts ?? {}}
          {@const picked = sc.selected ?? []}
          <!-- Split today's picks, not the groups that passed: setups beyond the cut are not picked (same as the push). -->
          {@const triggerPicked = (sc.triggers ?? []).filter((t) => picked.includes(t.ticker)).length}
          <p>范围 {counts.universe ?? 0} · 通过过滤 {(counts.trigger ?? 0) + (counts.setup ?? 0)}
             · 今日入选 {picked.length}（触发 {triggerPicked} / 形态 {picked.length - triggerPicked}）
             · 成员 {sc.members}/{sc.cap} · 移出 {(sc.removed ?? []).length}</p>
          {#if sc.universe?.stale}<p class="text-xs text-muted">提示 universe_stale（范围文件超过 120 天）</p>{/if}
          {#if (sc.flags ?? []).length}<p class="text-xs text-muted">提示 {(sc.flags ?? []).join('、')}</p>{/if}
          <h3 class="mt-2 font-medium">今日触发 → 复核</h3>
          <ul class="space-y-1">
            {#each sc.triggers ?? [] as t (t.ticker)}
              <li>{t.ticker} · {(t.rule_ids ?? []).join('、')} · RS {t.rs} · {reviewText(t)}</li>
            {:else}
              <li class="text-muted">今日无触发</li>
            {/each}
          </ul>
          <h3 class="mt-2 font-medium">形态候选（等待触发）</h3>
          <ul class="space-y-1">
            {#each (screenExpanded && screenFull ? (screenFull.setups ?? []) : (sc.setups ?? [])) as s (s.ticker)}
              <li>{s.ticker} · RS {s.rs} · ATR {s.atr_pct == null ? '—' : (s.atr_pct * 100).toFixed(2) + '%'}</li>
            {:else}
              <li class="text-muted">今日无形态候选</li>
            {/each}
          </ul>
          {#if !screenExpanded && (sc.setups_more ?? 0) > 0}
            <p class="text-xs text-muted">另 {sc.setups_more} 只 <button class="text-accent underline" onclick={expandScreen}>展开全部</button></p>
          {/if}
          {#if screenError}<p class="text-xs text-red-600">展开失败：{screenError}</p>{/if}
        {/if}
      {:else}
        <h2 class="font-semibold">筛选 <span class="text-xs text-muted">今日无筛选记录</span></h2>
      {/if}
    </section>

    <section class="border border-border rounded p-3 bg-surface text-sm" aria-label="市场环境">
      {#if view.market}
        {@const m = view.market}
        <h2 class="font-semibold">市场环境 <span class="text-xs px-1.5 py-0.5 rounded bg-accent/10 text-accent">{wb.REGIME_LABELS[m.label] ?? m.label}</span></h2>
        <p>站上 MA50 {pctText(m.breadth?.pct_50)} · MA200 {pctText(m.breadth?.pct_200)} · 新高 {m.breadth?.new_highs ?? 0} / 新低 {m.breadth?.new_lows ?? 0}</p>
        {#if m.sectors && Object.keys(m.sectors).length}
          <p class="text-xs text-muted">{Object.entries(m.sectors).map(([etf, v]) =>
            v == null ? `${etf} 数据不足` : `${etf} rs20 ${wb.pct(v.rs20)} ${wb.SECTOR_STATE_LABELS[v.state] ?? '数据不足'}`).join(' · ')}</p>
        {/if}
        <p class="text-xs text-muted">{fredText(m)}</p>
      {:else}
        <h2 class="font-semibold">市场环境 <span class="text-xs text-muted">未生成</span></h2>
      {/if}
    </section>
  {/if}

  {#if error}
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if loading && !view}
    <p class="text-sm text-muted">加载中…</p>
  {/if}

  <!-- v2.9 §10.1：计划表（入场期 / 持仓中 / 已结束）；自己取数、可选日期、扩展池开关 -->
  <section aria-label="计划表" class="space-y-3">
    <div class="flex flex-wrap items-center gap-3">
      <h2 class="font-semibold">计划表</h2>
      <label class="flex items-center gap-1 text-xs">交易日
        <input type="date" aria-label="交易日" class="border border-border rounded px-1 py-0.5 bg-bg" value={session}
               onchange={e => { session = (e.currentTarget as HTMLInputElement).value; void loadTable() }} />
      </label>
      <label class="flex items-center gap-1 text-xs">
        <input type="checkbox" checked={includeExtended}
               onchange={e => { includeExtended = (e.currentTarget as HTMLInputElement).checked; void loadTable() }} />
        显示扩展池（只影子跟踪）
      </label>
    </div>
    {#if tableError}
      <p role="alert" class="text-sm text-red-600">{tableError}</p>
    {:else if tableLoading && !table}
      <p class="text-sm text-muted">加载中…</p>
    {/if}
    {#if table}
      {#each Object.entries(table.errors ?? {}) as [name, reason] (name)}
        <p class="text-xs text-muted">{name} 暂不可用：{reason}</p>
      {/each}
      <PlanTable groups={table.groups} {rechecks} onRecheck={recheck} onNote={addNote} />
    {/if}
  </section>

  {#if table?.other_units?.length}
    <section aria-label="其他触发" class="space-y-1">
      <h2 class="font-semibold text-sm">其他触发</h2>
      <ul class="text-sm space-y-1">
        {#each table.other_units as u (`${u.ticker}|${u.signal_date}`)}
          <li class="border-l-2 border-border pl-2">{otherLine(u)}</li>
        {/each}
      </ul>
    </section>
  {/if}
</section>
