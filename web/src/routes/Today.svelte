<script lang="ts">
  import { onMount } from 'svelte'
  import { registerNavigationGuard } from '../lib/navigation-guard'
  import Drawer from '../lib/components/Drawer.svelte'
  import PlanDerivation from '../lib/components/PlanDerivation.svelte'
  import AgentPlanCard from '../lib/components/AgentPlanCard.svelte'
  import RuleBaseline from '../lib/components/RuleBaseline.svelte'
  import RunOverview from '../lib/components/RunOverview.svelte'
  import ConceptTerm from '../lib/components/ConceptTerm.svelte'
  import { ATTACH } from '../lib/knowledge'
  import * as api from '../lib/api'
  import { fmtBeijing } from '../lib/format'
  import * as tl from '../lib/timeline'
  import * as wb from '../lib/workbench'

  type Basis = wb.Basis
  type Draft = { choice: wb.Choice; reason: string; requestId: string; error: string; busy: boolean
                 basis: Basis; own: { entry_low: string; entry_high: string; stop: string; target1: string }
                 ownRequestId: string; stale: boolean }
  type Layout = wb.ReviewView['layout']

  // 布局开关存浏览器本地；读写失败（隐私模式、禁用存储）一律按默认「Agent 优先」（spec §10.1 第 5 条）。
  const LAYOUT_KEY = 'workbench.today.layout'
  function readLayout(): Layout {
    try {
      return globalThis.localStorage?.getItem(LAYOUT_KEY) === 'legacy' ? 'legacy' : 'agent_first'
    } catch {
      return 'agent_first'
    }
  }
  let layout = $state<Layout>(readLayout())
  function setLayout(next: Layout) {
    layout = next
    try { globalThis.localStorage?.setItem(LAYOUT_KEY, next) } catch { /* 存储不可用：只在本页生效 */ }
  }
  // 规则基线：本次会话里的展开状态，以及是否展开过（决定时上报 review_view.baseline_expanded）。
  let baselineOpen = $state<Record<string, boolean>>({})
  let baselineSeen = $state<Record<string, boolean>>({})
  let rechecks = $state<Record<string, { busy: boolean; text: string }>>({})

  let view = $state<wb.TodayView | null>(null)
  let error = $state('')
  let loading = $state(true)
  let notice = $state('')
  let drafts = $state<Record<string, Draft>>({})
  let generation = 0
  let callDrawer = $state<{ open: boolean; call: wb.AgentToolCall | null }>({ open: false, call: null })
  let callError = $state('')
  let screenExpanded = $state(false)
  let screenFull = $state<wb.ScreenReport | null>(null)
  let screenError = $state('')
  // 展开状态只在内存里，不进地址（设计 §10）；三种入口按 kind 区分。
  let derivationOpen = $state<Record<string, boolean>>({})
  const derivationShown = (kind: 'trigger', u: wb.Unit): boolean =>
    !!derivationOpen[`${kind}|${keyOf(u)}`]
  const toggleDerivation = (kind: 'trigger', u: wb.Unit) => {
    const key = `${kind}|${keyOf(u)}`
    derivationOpen[key] = !derivationOpen[key]
  }

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

  const keyOf = (u: wb.Unit) => `${u.ticker}|${u.signal_date}`

  async function load() {
    const token = ++generation
    loading = true
    try {
      const next = await wb.getToday()
      if (token !== generation) return
      for (const u of next.units) {
        // Drafts survive reloads and failed submits; the request id stays the same until success.
        drafts[keyOf(u)] ??= { choice: 'accept', reason: '', requestId: wb.newRequestId(), error: '', busy: false,
                                basis: defaultBasis(u),
                                own: { entry_low: '', entry_high: '', stop: '', target1: '' },
                                ownRequestId: wb.newRequestId(), stale: false }
      }
      view = next
      error = ''
    } catch (e) {
      if (token === generation) { error = wb.describeError(e); view = null }
    } finally {
      if (token === generation) loading = false
    }
  }

  const ruleUsable = (u: wb.Unit) => u.plan != null && u.plan.status === 'ok'
  const agentPlanOf = (u: wb.Unit) => (u.agent != null && 'plan' in u.agent ? u.agent.plan : null)
  const chainOf = (u: wb.Unit) => (u.agent?.chain ?? null)
  const agentUsable = (u: wb.Unit) => agentPlanOf(u)?.status === 'ok' && chainOf(u)?.state !== 'invalidated'
  const timelineReady = () => view?.timeline_ready !== false
  // 任一计划存在时采纳买入必须带依据（后端同规则）；规则计划缺失或作废时只能 Agent 或自定。
  const needsBasis = (u: wb.Unit) => u.proposed_action === 'buy' && (u.plan != null || agentPlanOf(u) != null)
  // Agent 可用时默认选 Agent（spec §10.1 第 4 条）。
  const defaultBasis = (u: wb.Unit): Basis =>
    agentUsable(u) ? 'agent' : ruleUsable(u) ? 'rule' : needsBasis(u) ? 'own' : 'rule'
  const agentBasisLabel = (u: wb.Unit) => {
    const chain = chainOf(u)
    return chain ? `Agent 计划（第 ${chain.version_no} 版）` : 'Agent 计划'
  }
  // Agent 有可用的 agent-2 计划时规则基线才折叠；失败、不建议、已作废、agent-1、无运行都自动展开。
  const agentHasPlan = (u: wb.Unit) => {
    const a = u.agent
    const legacy = !!a?.legacy || (a != null && 'agent_version' in a && a.agent_version === 'agent-1')
    return a != null && a.status === 'ok' && !legacy && agentUsable(u)
  }
  const baselineCollapsible = (u: wb.Unit) => layout === 'agent_first' && agentHasPlan(u)
  const baselineExpanded = (u: wb.Unit) => !baselineCollapsible(u) || !!baselineOpen[keyOf(u)]
  function toggleBaseline(u: wb.Unit) {
    const key = keyOf(u)
    baselineOpen[key] = !baselineOpen[key]
    if (baselineOpen[key]) baselineSeen[key] = true
  }
  const ownReady = (draft: Draft) => draft.own.entry_low.trim() !== '' && wb.levelsError(draft.own) === null

  async function submit(u: wb.Unit) {
    const key = keyOf(u)
    const draft = drafts[key]
    if (!draft || !draft.reason.trim() || draft.busy) return
    if (draft.choice === 'accept' && draft.basis === 'own' && !ownReady(draft)) return
    draft.busy = true
    draft.error = ''
    try {
      const own = draft.choice === 'accept' && draft.basis === 'own'
        ? { request_id: draft.ownRequestId, ...draft.own } : null
      // 迁移 026 未就绪时不带新字段（后端对带新字段的请求返回 503）。
      const chain = timelineReady() ? chainOf(u) : null
      const reviewView: wb.ReviewView | null = timelineReady()
        ? { layout, baseline_expanded: !!baselineSeen[key] || baselineExpanded(u), agent_version_no: chain?.version_no ?? null }
        : null
      await wb.postDecision(wb.decisionPayload(u, draft.choice, draft.reason, draft.requestId, own, draft.basis,
                                               chain?.head_plan_id ?? null, reviewView))
      delete drafts[key]
      await load()
    } catch (e) {
      const stale = tl.staleVersion(e)
      draft.stale = stale != null
      draft.error = stale != null ? tl.staleText(stale) : wb.describeError(e)
    } finally {
      if (drafts[key]) drafts[key].busy = false
    }
  }

  // 409 agent_plan_stale 后刷新：保留草稿；页面已换成最新版，请求内容随之改变，所以换一个 request id。
  async function refreshStale(u: wb.Unit) {
    const draft = drafts[keyOf(u)]
    if (draft) { draft.stale = false; draft.error = ''; draft.requestId = wb.newRequestId() }
    await load()
  }

  async function recheck(c: tl.ChainRow) {
    const key = `${c.ticker}|${c.signal_date}`
    if (rechecks[key]?.busy) return
    rechecks[key] = { busy: true, text: '复查中…' }
    try {
      const started = await api.recheckChain(c.ticker, c.signal_date)
      const done = await api.pollRun(started.run_id, { timeoutMs: tl.RECHECK_POLL_MS })
      rechecks[key] = { busy: false, text: tl.recheckDoneText(done) }
      if (done.status === 'done') await load()
    } catch (e) {
      // 轮询超时不是失败：后台仍在复查，按钮保持不可点，提示稍后刷新（再点会 409 review_in_progress）。
      rechecks[key] = tl.isRunTimeout(e) ? { busy: true, text: tl.RECHECK_PENDING_TEXT }
        : { busy: false, text: e instanceof wb.WorkbenchError && e.status === 409
            ? `不能重新复查：${tl.recheckConflictText(e.message)}` : wb.describeError(e) }
    }
  }

  const chainReviewText = (c: tl.ChainRow) => c.latest_review
    ? `${tl.OUTCOME_TEXT[c.latest_review.outcome] ?? c.latest_review.outcome}`
      + `${c.latest_review.decided_by ? ` · ${tl.DECIDED_BY_TEXT[c.latest_review.decided_by]}` : ''}`
      + ` · ${fmtBeijing(c.latest_review.created_at)}${c.latest_review.reason ? ` · ${c.latest_review.reason}` : ''}`
    : '尚未复查'

  async function runNow() {
    try {
      const run = await wb.runWorkbench()
      notice = `已提交批处理（${run.run_id}），完成后刷新本页查看。`
    } catch (e) {
      notice = wb.describeError(e)
    }
  }

  async function showCall(u: wb.Unit, ref: string) {
    callError = ''
    try {
      const detail = await wb.getAgentRun(u.agent!.id)
      const seq = Number(ref.split(':')[1])
      callDrawer = { open: true, call: detail.tool_calls.find(c => c.seq === seq) ?? null }
    } catch (e) {
      callError = wb.describeError(e)
    }
  }

  async function rerunAgentNow(u: wb.Unit) {
    try {
      await wb.rerunAgent(u.ticker, u.signal_date)
      await load()
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
  const values = (c: wb.Candidate) =>
    Object.entries(c.inputs?.values ?? {}).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join('/') : v}`).join(' · ')

  onMount(() => {
    load()
    return registerNavigationGuard({
      snapshot: () => JSON.stringify(Object.entries(drafts).map(([k, d]) => [k, d.choice, d.reason])),
      dirty: () => Object.values(drafts).some(d => d.reason.trim() !== ''),
      discard: () => { for (const d of Object.values(drafts)) d.reason = '' },
    })
  })
</script>

<section class="space-y-4">
  <header class="flex items-center justify-between">
    <div>
      <h1 class="text-lg font-semibold">今日</h1>
      {#if view}<p class="text-xs text-muted">最近收盘交易日 {view.session} · 信号仅为研究候选，不会自动下单</p>{/if}
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <div role="group" aria-label="布局" class="flex items-center gap-1 text-xs">
        <span class="text-muted">布局：</span>
        {#each [['agent_first', 'Agent 优先'], ['legacy', '规则优先（旧）']] as [value, label]}
          <button class="px-2 py-1 border border-border rounded {layout === value ? 'bg-accent/10 text-accent' : 'hover:bg-surface-2'}"
                  aria-pressed={layout === value} onclick={() => setLayout(value as Layout)}>{label}</button>
        {/each}
      </div>
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
  {:else if view && view.units.length === 0}
    <p class="text-sm text-muted">今日没有待处理的信号</p>
  {/if}

  {#each view?.units ?? [] as u (keyOf(u))}
    {@const draft = drafts[keyOf(u)]}
    <article class="border border-border rounded p-3 space-y-3 bg-surface">
      <div class="flex flex-wrap items-center gap-2">
        <h2 class="font-semibold">{u.ticker} · {u.signal_date}</h2>
        <span class="text-xs px-1.5 py-0.5 rounded bg-accent/10 text-accent">建议{wb.ACTION_LABELS[u.proposed_action]}</span>
        {#if u.source === 'screen'}<span title="筛选来源" class="text-xs px-1.5 py-0.5 rounded bg-sky-100 text-sky-800">筛选</span>{/if}
        {#each u.labels as label}<span class="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">{wb.UNIT_LABELS[label] ?? label}</span>{/each}
        {#if u.entry_passed}<span class="text-xs text-amber-700">已过入场时点（T+1 开盘）</span>{/if}
        {#if u.position}<span class="text-xs text-muted">持仓 {u.position.quantity} · 成本 {Number(u.position.avg_cost).toFixed(2)}</span>{/if}
      </div>

      <ul class="text-sm space-y-1">
        {#each u.candidates as c (c.id)}
          <li><span class="font-medium">{wb.ruleLabel(c.rule_id)}</span> → {wb.ACTION_LABELS[c.action]} <span class="text-xs text-muted">{values(c)}</span></li>
        {/each}
      </ul>

      {#if !u.plan && !agentPlanOf(u)}
        <div class="text-sm space-y-1">
          <button class="text-xs text-accent underline" aria-expanded={derivationShown('trigger', u)}
                  onclick={() => toggleDerivation('trigger', u)}>触发依据</button>
          {#if derivationShown('trigger', u)}
            <PlanDerivation unit={{ ticker: u.ticker, signal_date: u.signal_date }} />
          {/if}
        </div>
      {/if}

      <div class="text-sm border-l-2 border-border pl-2 space-y-1">
        {#if !u.brief}
          <p class="text-muted">尚无解读</p>
        {:else if u.brief.status === 'error'}
          <p class="text-red-600">解读无效，已隐藏：{u.brief.error}</p>
        {:else if u.brief.prompt_version === 'agent-1' || u.brief.prompt_version === 'agent-2'}
          <p class="text-xs text-muted">解读见 Agent 建议</p>
        {:else}
          {#if u.brief.status === 'fallback'}<p class="text-xs text-muted">规则版解读（LLM 未参与：{u.brief.error}）</p>{/if}
          {#if u.brief.model}<p class="text-xs text-muted">模型 {u.brief.model}</p>{/if}
          <p>{u.brief.output?.summary}</p>
          {#each [['支持', u.brief.output?.support], ['反证', u.brief.output?.contra], ['冲突与缺口', u.brief.output?.conflicts]] as [title, items]}
            {#if Array.isArray(items) && items.length}
              <p class="text-xs text-muted">{title}</p>
              <ul class="list-disc ml-5">
                {#each items as item}<li>{item.text}（{item.refs.join(', ')}）</li>{/each}
              </ul>
            {/if}
          {/each}
        {/if}
      </div>

      {#if u.filings.length || u.news.length}
        <ul class="text-xs space-y-0.5 text-muted">
          {#each u.filings as f (f.id)}
            <li>SEC {f.form}{f.items?.length ? `（Items ${f.items.join(', ')}）` : ''} · {f.accepted_at ? wb.dateTime(f.accepted_at) : '受理时间未知'}</li>
          {/each}
          {#each u.news as n (n.id)}
            <li><a class="underline" href={n.url} target="_blank" rel="noreferrer">{n.title}</a> · {n.publisher ?? n.source} · {wb.publishedText(n.published_at)}</li>
          {/each}
        </ul>
      {/if}

      {#snippet agentBlock()}
        {#if u.agent}
          <AgentPlanCard agent={u.agent} onCall={ref => showCall(u, ref)} onRerun={() => rerunAgentNow(u)} />
          {#if callError}<p class="text-xs text-red-600">{callError}</p>{/if}
        {/if}
      {/snippet}
      {#snippet baselineBlock()}
        <RuleBaseline plan={u.plan} expanded={baselineExpanded(u)} collapsible={baselineCollapsible(u)}
                      ontoggle={() => toggleBaseline(u)} />
      {/snippet}
      {#if layout === 'legacy'}
        {@render baselineBlock()}
        {@render agentBlock()}
      {:else}
        {@render agentBlock()}
        {@render baselineBlock()}
      {/if}

      {#if draft}
        <form class="space-y-2" onsubmit={e => { e.preventDefault(); submit(u) }}>
          {#if draft.choice === 'accept' && needsBasis(u)}
            <fieldset class="flex gap-3 text-sm" aria-label="执行依据">
              <legend class="text-xs text-muted"><ConceptTerm id={ATTACH.today.basis}>执行依据</ConceptTerm></legend>
              <label class="flex items-center gap-1">
                <input type="radio" name={`basis-${keyOf(u)}`} value="agent" bind:group={draft.basis}
                       disabled={!agentUsable(u)} />
                {agentBasisLabel(u)}
              </label>
              <label class="flex items-center gap-1">
                <input type="radio" name={`basis-${keyOf(u)}`} value="rule" bind:group={draft.basis}
                       disabled={!ruleUsable(u)} />
                规则计划
              </label>
              <label class="flex items-center gap-1">
                <input type="radio" name={`basis-${keyOf(u)}`} value="own" bind:group={draft.basis} />
                自定价位
              </label>
            </fieldset>
            {#if draft.basis === 'own'}
              <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
                <label class="flex flex-col">入场下限<input aria-label="入场下限" inputmode="decimal" class="border border-border rounded px-2 py-1 bg-bg" bind:value={draft.own.entry_low} /></label>
                <label class="flex flex-col">入场上限<input aria-label="入场上限" inputmode="decimal" class="border border-border rounded px-2 py-1 bg-bg" bind:value={draft.own.entry_high} /></label>
                <label class="flex flex-col">止损价<input aria-label="止损价" inputmode="decimal" class="border border-border rounded px-2 py-1 bg-bg" bind:value={draft.own.stop} /></label>
                <label class="flex flex-col">T1 价<input aria-label="T1 价" inputmode="decimal" class="border border-border rounded px-2 py-1 bg-bg" bind:value={draft.own.target1} /></label>
              </div>
              {#if draft.own.entry_low.trim() !== '' && wb.levelsError(draft.own)}
                <p class="text-xs text-red-600">{wb.levelsError(draft.own)}</p>
              {/if}
            {/if}
          {/if}
          <fieldset class="flex gap-3 text-sm">
            {#each (u.proposed_action === 'watch' ? ['accept', 'reject'] : ['accept', 'reject', 'downgrade']) as choice}
              <label class="flex items-center gap-1">
                <input type="radio" name={`choice-${keyOf(u)}`} value={choice} bind:group={draft.choice} />
                {wb.CHOICE_LABELS[choice as wb.Choice]}
              </label>
            {/each}
          </fieldset>
          <textarea aria-label="理由" class="w-full border border-border rounded p-2 text-sm bg-bg" rows="2"
                    placeholder="写一句理由（必填）" bind:value={draft.reason}></textarea>
          <div class="flex items-center gap-2">
            <button type="submit" class="text-sm px-3 py-1 rounded bg-accent text-white disabled:opacity-50"
                    disabled={!draft.reason.trim() || draft.busy
                              || (draft.choice === 'accept' && draft.basis === 'own'
                                  && draft.own.entry_low.trim() !== '' && !ownReady(draft))}>提交决定</button>
            {#if draft.error}<span class="text-xs text-red-600">{draft.error}</span>{/if}
            {#if draft.stale}
              <button type="button" class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2"
                      onclick={() => refreshStale(u)}>刷新</button>
            {/if}
          </div>
        </form>
      {/if}
    </article>
  {/each}

  {#if view && timelineReady() && view.chains?.length}
    <section class="border border-border rounded p-3 bg-surface text-sm space-y-1" aria-label="进行中的 Agent 计划">
      <h2 class="font-semibold">进行中的 Agent 计划</h2>
      <ul class="space-y-1">
        {#each view.chains as c (`${c.ticker}|${c.signal_date}`)}
          {@const rk = rechecks[`${c.ticker}|${c.signal_date}`]}
          <li class="flex flex-wrap items-center gap-x-2">
            <span>{c.ticker} · {c.mode ? tl.MODE_TEXT[c.mode] : tl.CHAIN_STATE_TEXT[c.state]} · 第 {c.version_no} 版</span>
            <span class="text-xs text-muted">最近复查 {chainReviewText(c)}</span>
            <span class="text-xs text-muted">今日信号 {c.signals_today.length ? c.signals_today.map(k => tl.SIGNAL_TEXT[k] ?? k).join('、') : '无'}</span>
            <a class="text-xs text-accent underline" href={`#plan/${c.head_plan_id}`}>查看</a>
            <button class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2 disabled:opacity-50"
                    disabled={rk?.busy} onclick={() => recheck(c)}>重新复查</button>
            {#if rk?.text}<span class="text-xs">{rk.text}</span>{/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if view?.extended_units?.length}
    <details class="border border-border rounded p-3 bg-surface text-sm">
      <summary class="cursor-pointer font-medium">扩展池（只影子跟踪）· {view.extended_units.length} 个单元</summary>
      <ul class="mt-2 space-y-1">
        {#each view.extended_units as u (`${u.ticker}|${u.signal_date}`)}
          <li>{u.ticker} · {u.signal_date} · 建议{wb.ACTION_LABELS[u.proposed_action]} · {u.rule_ids.map(wb.ruleLabel).join('、')}
            {#if u.plan}· {u.plan.status === 'invalid' ? '已作废' : '有效'} · 入场 {u.plan.entry_low}–{u.plan.entry_high} · 止损 {u.plan.stop} · T1 {u.plan.target1} · 有效期至 {u.plan.valid_until}{/if}
            {#if u.agent_status}· Agent {u.agent_status}{/if}
          </li>
        {/each}
      </ul>
    </details>
  {/if}

  <Drawer open={callDrawer.open} onclose={() => callDrawer = { open: false, call: null }}>
    {#if callDrawer.call}
      {@const c = callDrawer.call}
      <h2 class="font-semibold">工具调用 call:{c.seq}</h2>
      <p class="text-xs text-muted">工具 {c.tool} · 阶段 {c.phase === 'propose' ? '建议' : '反方'} · {wb.dateTime(c.called_at)}</p>
      <p class="text-xs break-all">参数 {JSON.stringify(c.args)}</p>
      <p class="text-xs break-all">哈希 {c.result_sha256.slice(0, 8)}</p>
      <pre class="text-xs mt-2 whitespace-pre-wrap break-all">{JSON.stringify(c.result, null, 2)}</pre>
    {:else}
      <p class="text-sm text-muted">未找到该编号的工具调用</p>
    {/if}
  </Drawer>

  {#if view?.holdings?.length}
    <h2 class="font-semibold text-sm">持仓止损</h2>
    <ul class="text-sm space-y-1">
      {#each view.holdings as h (h.ticker)}
        <li class="border border-border rounded p-2 bg-surface">
          <span class="font-medium">{h.ticker}</span> · {h.quantity} 股 @ {Number(h.avg_cost).toFixed(2)} · 收盘 {h.last_close}
          {#if h.stop != null}
            · 止损 {h.stop}（{h.mode === 'trailing' ? '移动' : '初始'}）· {h.t1_reached ? '已触 T1' : '未触 T1'}
            · 距止损 {wb.pct(h.to_stop_pct)} · 距 T1 {wb.pct(h.to_target_pct)}
          {:else}
            · 无计划持仓（回撤规则看护）
          {/if}
          {#if h.next_earnings}<span class="text-amber-700"> · 下次财报 {h.next_earnings}</span>{/if}
          {#if timelineReady() && h.chain_state === 'invalidated'}<span class="text-xs text-muted"> · Agent 计划已作废，不再复查</span>
          {:else if timelineReady() && h.has_chain === false}<span class="text-xs text-muted"> · 此持仓无 Agent 计划，不参与复查</span>{/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>
