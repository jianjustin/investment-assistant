<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import { getTickerChains, getWatchlist, pollRun, recheckChain } from '../lib/api'
  import CandleChart from '../lib/charts/CandleChart.svelte'
  import ConceptTerm from '../lib/components/ConceptTerm.svelte'
  import DiscussButton from '../lib/components/DiscussButton.svelte'
  import Fundamentals from '../lib/components/Fundamentals.svelte'
  import PlanDerivation from '../lib/components/PlanDerivation.svelte'
  import UserInputs from '../lib/components/UserInputs.svelte'
  import VolumeBars from '../lib/components/VolumeBars.svelte'
  import { ATTACH, ruleConcept } from '../lib/knowledge'
  import { toLineData } from '../lib/technicals'
  import { fmtBeijing } from '../lib/format'
  import * as tl from '../lib/timeline'
  import * as wb from '../lib/workbench'

  let { sub }: { sub?: string } = $props()

  let ticker = $state('')
  let tickers = $state<string[]>([])
  let view = $state<wb.InstrumentView | null>(null)
  let error = $state('')
  let loading = $state(false)
  let generation = 0
  // v2.5 §11：页尾「我的补充」与该标的的 Agent 链列表；读不到（如迁移 026 未执行）只影响这一段。
  let chains = $state<tl.TickerChain[]>([])
  let chainsError = $state('')
  // 503 = 迁移 026 未执行（或数据库不可用）：用户输入也写不进去，隐藏「我的补充」。
  let timelineMissing = $state(false)

  async function loadChains(next: string, token: number) {
    try {
      const res = await getTickerChains(next)
      if (token !== generation) return
      chains = Array.isArray(res?.chains) ? res.chains : []
      chainsError = ''
      timelineMissing = false
    } catch (e) {
      if (token === generation) {
        chains = []
        chainsError = wb.describeError(e)
        timelineMissing = e instanceof wb.WorkbenchError && e.status === 503
      }
    }
  }
  const activeChains = $derived(chains.filter(c => tl.ACTIVE_STATES.includes(c.state))
    .map(c => ({ signal_date: c.signal_date, label: `${c.signal_date} · 第 ${c.version_no} 版` })))
  const I = ATTACH.instrument
  const liveChains = $derived(chains.filter(c => tl.ACTIVE_STATES.includes(c.state)))
  const endedChains = $derived(chains.filter(c => !tl.ACTIVE_STATES.includes(c.state)))
  let rechecks = $state<Record<string, { busy: boolean; text: string }>>({})
  let triggerOpen = $state<Record<string, boolean>>({})

  async function recheck(c: tl.TickerChain) {
    const key = c.signal_date
    const target = ticker
    if (rechecks[key]?.busy) return
    rechecks[key] = { busy: true, text: '复查中…' }
    try {
      const started = await recheckChain(target, c.signal_date)
      const done = await pollRun(started.run_id, { timeoutMs: tl.RECHECK_POLL_MS })
      rechecks[key] = { busy: false, text: tl.recheckDoneText(done) }
      if (done.status === 'done') await loadChains(target, generation)
    } catch (e) {
      // 轮询超时不是失败：后台仍在复查，按钮保持不可点（再点会 409 review_in_progress）。
      rechecks[key] = tl.isRunTimeout(e) ? { busy: true, text: tl.RECHECK_PENDING_TEXT }
        : { busy: false, text: e instanceof wb.WorkbenchError && e.status === 409
            ? `不能重新复查：${tl.recheckConflictText(e.message)}` : wb.describeError(e) }
    }
  }

  // v2.6 §9：四段所用的派生数据；旧后端没有这些键时一律按空处理。
  const focus = $derived(view?.focus ?? [])
  // v2.7 §5.5：挂在该标的上的有效经验；旧后端没有这个键时按空处理
  const knowledge = $derived(view?.knowledge ?? [])
  const blockError = (name: string) => view?.errors?.[name] ?? null
  const todays = $derived(view ? view.candidates.filter(c => c.signal_date === view!.session) : [])
  const plans = $derived(view?.plans ?? [])
  const planOfHead = (id: string) => plans.find(p => p.id === id)
  const livePlans = $derived(plans.filter(p => p.kind !== 'agent' && p.status === 'ok'
    && !!view && p.valid_until >= view.session))
  const annotations = $derived(view?.chart.annotations)
  const focusPlanLink = $derived(focus.find(item => item.link?.startsWith('#plan/'))?.link ?? null)
  const planLine = (p: { entry_low: string | number; entry_high: string | number; stop: string | number; target1: string | number }) =>
    `入场 ${p.entry_low}–${p.entry_high} · 止损 ${p.stop} · T1 ${p.target1}`
  const candidateValues = (c: wb.Candidate) =>
    Object.entries(c.inputs?.values ?? {}).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join('/') : v}`).join(' · ')
  const NEWS_KINDS: wb.TimelineItem['kind'][] = ['filing', 'news']
  const allTimeline = $derived(view ? wb.timeline(view) : [])
  const backgroundItems = $derived(allTimeline.filter(item => NEWS_KINDS.includes(item.kind)))
  const historyItems = $derived(allTimeline.filter(item => !NEWS_KINDS.includes(item.kind)))
  const KEY_LABELS: [string, string][] = [
    ['last_close', '最近收盘'], ['atr14', 'ATR14'], ['ma20', 'MA20'], ['ma50', 'MA50'], ['ma200', 'MA200'],
    ['high_20', '20 日高'], ['low_20', '20 日低'], ['high_252', '252 日高'], ['low_252', '252 日低'],
    ['avg_volume_20', '20 日均量'], ['volume_ratio', '量比'],
    ['rs20', '相对 SPY 20 日强弱'], ['rs60', '相对 SPY 60 日强弱'],
  ]
  const EARNINGS_STATUS: Record<string, string> = { known: '已知', unknown: '未知' }
  const KIND_COLOR: Record<string, string> = { rule: '#0ea5e9', own: '#a855f7', agent: '#f97316' }
  const chainLine = (c: tl.TickerChain) => [
    c.signal_date, tl.CHAIN_STATE_TEXT[c.state] ?? c.state, `第 ${c.version_no} 版`,
    c.latest_review
      ? `最近复查 ${tl.OUTCOME_TEXT[c.latest_review.outcome] ?? c.latest_review.outcome}`
        + `${c.latest_review.decided_by ? ` · ${tl.DECIDED_BY_TEXT[c.latest_review.decided_by]}` : ''}`
        + ` · ${fmtBeijing(c.latest_review.created_at)}`
      : '尚未复查',
  ].join(' · ')

  const KIND_LABELS: Record<wb.TimelineItem['kind'], string> = {
    filing: '财报', news: '资讯', candidate: '信号', decision: '决定', trade: '成交',
  }

  async function select(next: string, updateHash = true) {
    next = next.trim().toUpperCase()
    if (!next || next === ticker) return
    ticker = next
    if (updateHash) history.replaceState(null, '', `#instrument/${next}`)
    const token = ++generation
    loading = true
    error = ''
    view = null
    chains = []
    chainsError = ''
    timelineMissing = false
    rechecks = {}
    triggerOpen = {}
    void loadChains(next, token)
    try {
      const loaded = await wb.getInstrument(next)
      if (token !== generation) return
      // A late response for another ticker must never be shown under this one.
      if (loaded.ticker !== next) throw new Error('响应标的不匹配')
      view = loaded
    } catch (e) {
      if (token === generation) error = wb.describeError(e)
    } finally {
      if (token === generation) loading = false
    }
  }

  // Only a route change selects; untracked so selecting from the picker is not undone.
  $effect(() => {
    const routed = sub
    untrack(() => { if (routed) select(routed, false) })
  })

  onMount(async () => {
    try {
      const rows = (await getWatchlist()) as { rows?: { ticker: string; identity_error?: string }[] }
      // Rows with an invalid identity stay listed in settings for deletion, never here.
      tickers = (rows.rows ?? []).filter(r => !r.identity_error).map(r => r.ticker)
      if (!sub && tickers[0]) select(tickers[0])
    } catch {
      tickers = []
    }
  })
</script>

<section class="space-y-4">
  <header class="flex items-center gap-3">
    <h1 class="text-lg font-semibold">标的</h1>
    <select aria-label="标的" class="border border-border rounded px-2 py-1 text-sm bg-bg" value={ticker}
            onchange={e => select((e.currentTarget as HTMLSelectElement).value)}>
      {#if ticker && !tickers.includes(ticker)}<option value={ticker}>{ticker}</option>{/if}
      {#each tickers as t}<option value={t}>{t}</option>{/each}
    </select>
  </header>

  {#if error}
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if loading}
    <p class="text-sm text-muted">加载中…</p>
  {:else if !ticker}
    <p class="text-sm text-muted">观察名单为空，请在「更多 → 设置 → 关注列表」添加美股。</p>
  {/if}

  {#if view}
    <h2 class="font-semibold">{view.ticker} · 截至 {view.session}</h2>

    <!-- ① 信号与计划：首屏先回答「今天该关注什么」 -->
    <section aria-label="信号与计划" class="space-y-3">
      <h2 class="font-semibold">信号与计划</h2>
      {#if blockError('focus')}<p class="text-xs text-muted">今天该关注什么暂不可用：{blockError('focus')}</p>{/if}
      {#if focus.length}
        <ul aria-label="今天该关注什么" class="space-y-1 text-sm">
          {#each focus as item, i (i)}
            <li class="border-l-2 border-accent/50 pl-2">{item.text}
              {#if item.link}<a class="text-accent underline" href={item.link}>查看</a>{/if}
              {#each item.concepts as id, i (i)}<span class="text-xs"> <ConceptTerm {id} /></span>{/each}
            </li>
          {/each}
        </ul>
      {/if}

      {#if todays.length}
        <div class="text-sm space-y-1">
          <p class="text-xs text-muted"><ConceptTerm id={I.trigger}>今日触发</ConceptTerm></p>
          <ul aria-label="今日触发" class="space-y-1">
            {#each todays as c (c.id)}
              <li>
                <ConceptTerm id={ruleConcept(c.rule_id)}>{wb.ruleLabel(c.rule_id)}</ConceptTerm> → {wb.ACTION_LABELS[c.action]}
                <span class="text-xs text-muted">{candidateValues(c)}</span>
                <button type="button" class="text-xs text-accent underline" aria-expanded={!!triggerOpen[c.id]}
                        onclick={() => triggerOpen[c.id] = !triggerOpen[c.id]}>触发依据</button>
                {#if triggerOpen[c.id]}<PlanDerivation unit={{ ticker: view.ticker, signal_date: c.signal_date }} />{/if}
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      <div class="border border-border rounded p-3 bg-surface text-sm space-y-1">
        <h3 class="font-medium"><ConceptTerm id={I.chain}>Agent 计划</ConceptTerm></h3>
        {#if chainsError}
          <p class="text-xs text-muted">Agent 计划列表不可用：{chainsError}</p>
        {:else if liveChains.length}
          <ul aria-label="Agent 计划" class="space-y-1">
            {#each liveChains as c (c.signal_date)}
              {@const head = planOfHead(c.head_plan_id)}
              {@const rk = rechecks[c.signal_date]}
              <li>{chainLine(c)}{#if head} · {planLine(head)}{/if} · <a class="text-accent underline" href={`#plan/${c.head_plan_id}`}>查看</a>
                <button type="button" class="text-xs px-2 py-0.5 border border-border rounded hover:bg-surface-2 disabled:opacity-50"
                        disabled={rk?.busy} onclick={() => recheck(c)}>重新复查</button>
                <DiscussButton context={{ kind: 'plan', plan_id: c.head_plan_id }} />
                {#if rk?.text}<span class="text-xs">{rk.text}</span>{/if}
                {#if c.latest_review?.reason}<p class="text-xs text-muted">{c.latest_review.reason}</p>{/if}
              </li>
            {/each}
          </ul>
        {:else if chains.length}
          <p class="text-xs text-muted">没有进行中的 Agent 计划</p>
        {:else}
          <p class="text-xs text-muted">该标的还没有 Agent 版本链</p>
        {/if}
        {#if endedChains.length}
          <details>
            <summary class="cursor-pointer text-xs"><ConceptTerm id={I.chainState}>已结束的链</ConceptTerm>（{endedChains.length}）</summary>
            <ul aria-label="已结束的链" class="space-y-1">
              {#each endedChains as c (c.signal_date)}
                <li>{chainLine(c)} · <a class="text-accent underline" href={`#plan/${c.head_plan_id}`}>查看</a>
                  {#if c.latest_review?.reason}<p class="text-xs text-muted">{c.latest_review.reason}</p>{/if}
                </li>
              {/each}
            </ul>
          </details>
        {/if}
      </div>

      {#if livePlans.length}
        <div class="text-sm space-y-1">
          <p class="text-xs text-muted"><ConceptTerm id={I.entryZone}>当前有效的规则 / 自定计划</ConceptTerm></p>
          <ul aria-label="当前有效的计划" class="space-y-1">
            {#each livePlans as p (p.id)}
              <li>{wb.KIND_TEXT[p.kind] ?? p.kind} · {p.plan_version} · {planLine(p)} · 有效期至 {p.valid_until}
                · <a class="text-accent underline" href={`#plan/${p.id}`}>推导</a></li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if view.position}
        <p class="text-sm">持仓 {view.position.quantity} 股 · 成本 {Number(view.position.avg_cost).toFixed(2)} · 开仓 {wb.dateTime(view.position.opened_at)}
          <span class="text-xs"><ConceptTerm id={I.position}>持仓说明</ConceptTerm></span></p>
        {#if view.holding}
          {@const h = view.holding}
          <p class="text-sm" aria-label="持仓止损">
            {#if h.stop != null}
              当前止损 {h.stop}（{h.mode === 'trailing' ? '移动' : '初始'}）<span class="text-xs"><ConceptTerm id={I.stop}>止损</ConceptTerm>{#if h.mode === 'trailing'} <ConceptTerm id={I.trailing}>移动止损</ConceptTerm>{/if}</span>
              · T1 {h.target1 ?? '—'}（{h.t1_reached ? '已触 T1' : '未触 T1'}）<span class="text-xs"><ConceptTerm id={I.target1}>T1</ConceptTerm></span>
              · 收盘 {h.last_close ?? '—'} · 距止损 {wb.pct(h.to_stop_pct)} · 距 T1 {wb.pct(h.to_target_pct)}
            {:else}
              无计划持仓（回撤规则看护）
            {/if}
          </p>
        {:else if blockError('holding')}
          <p class="text-xs text-muted">当前止损与 T1 暂不可用：{blockError('holding')}</p>
        {/if}
      {:else}
        <p class="text-sm text-muted">当前无持仓</p>
      {/if}

      {#if timelineMissing}
        <section class="border border-border rounded p-3 bg-surface text-sm">
          <h2 class="font-semibold">我的补充</h2>
          <p class="text-xs text-muted"><ConceptTerm id={I.userInput}>用户输入说明</ConceptTerm></p>
          <p class="text-xs text-muted">暂不可用：{chainsError}</p>
        </section>
      {:else}
        <p class="text-xs text-muted"><ConceptTerm id={I.userInput}>用户输入说明</ConceptTerm></p>
        {#key view.ticker}
          <UserInputs ticker={view.ticker} chains={activeChains} />
        {/key}
      {/if}
    </section>

    <!-- ①' 我的知识：挂在这个标的上的有效经验（v2.7） -->
    <section aria-label="我的知识" class="space-y-2">
      <h2 class="font-semibold">我的知识</h2>
      <p class="text-xs text-muted"><ConceptTerm id={ATTACH.myKnowledge.item}>说明</ConceptTerm>
        · <a class="text-accent underline" href={`#knowledge/mine/new?ticker=${encodeURIComponent(view.ticker)}`}>写一条</a></p>
      {#if blockError('knowledge')}
        <p class="text-xs text-muted">暂不可用：{blockError('knowledge')}</p>
      {:else if knowledge.length}
        <ul aria-label="我的知识条目" class="space-y-1 text-sm">
          {#each knowledge as e (e.id)}
            <li><a class="text-accent underline" href={`#knowledge/mine/${e.id}`}>{e.title}</a>
              <span class="text-xs text-muted"> · 适用范围：{e.scope} · 第 {e.current_version} 版 · 被引用 {e.citation_count} 次</span></li>
          {/each}
        </ul>
      {:else}
        <p class="text-xs text-muted">还没有挂在 {view.ticker} 上的经验</p>
      {/if}
    </section>

    <!-- ② 关键数据：与 Agent 工具同一个纯函数现算，截至最近收盘 -->
    <section aria-label="关键数据" class="space-y-2">
      <h2 class="font-semibold">关键数据</h2>
      {#if view.key_data}
        {@const kd = view.key_data}
        <p class="text-xs text-muted">截至 {kd.as_of ?? '—'}
          {#if focusPlanLink} · 焦点计划 <a class="text-accent underline" href={focusPlanLink}>看推导</a>{/if}</p>
        <ul aria-label="关键数据" class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-0.5 text-sm">
          {#each KEY_LABELS as [key, label] (key)}
            <li class="flex justify-between gap-2">
              <span class="text-muted">{#if kd.concepts?.[key]}<ConceptTerm id={kd.concepts[key]}>{label}</ConceptTerm>{:else}{label}{/if}</span>
              <span class="tabular">{kd.values?.[key] ?? '—'}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="text-xs text-muted">暂无关键数据{blockError('key_data') ? `：${blockError('key_data')}` : ''}</p>
      {/if}
    </section>

    <!-- ③ 背景：财报日、区制、行业、基本面、近期资讯与 SEC 文件 -->
    <section aria-label="背景" class="space-y-2">
      <h2 class="font-semibold">背景</h2>
      {#if blockError('context')}<p class="text-xs text-muted">财报日、区制与行业暂不可用：{blockError('context')}</p>{/if}
      <ul aria-label="背景要点" class="text-sm space-y-0.5">
        <li><ConceptTerm id={I.earnings}>下次财报</ConceptTerm>：
          {#if view.context?.earnings?.date}
            {view.context.earnings.date}（{EARNINGS_STATUS[view.context.earnings.status ?? ''] ?? view.context.earnings.status ?? '—'}{#if view.context.earnings.sessions_until != null}，距今 {view.context.earnings.sessions_until} 个交易日{/if}）
          {:else}下次财报日未知{/if}</li>
        <li><ConceptTerm id={I.regime}>区制</ConceptTerm>：
          {#if view.context?.regime}{wb.REGIME_LABELS[view.context.regime.label] ?? view.context.regime.label}（{view.context.regime.session}）{:else}未生成{/if}</li>
        <li><ConceptTerm id={I.sector}>行业强弱</ConceptTerm>：
          {#if view.context?.sector}
            {view.context.sector.etf} {view.context.sector.state ? (wb.SECTOR_STATE_LABELS[view.context.sector.state] ?? view.context.sector.state) : '数据不足'}
            · rs20 {view.context.sector.rs20 ?? '—'} · rs60 {view.context.sector.rs60 ?? '—'}
          {:else}未映射行业 ETF{/if}</li>
      </ul>
      <Fundamentals ticker={view.ticker} />
      <p class="text-xs text-muted"><ConceptTerm id={I.news}>近期资讯</ConceptTerm> 与 <ConceptTerm id={I.filings}>SEC 文件</ConceptTerm></p>
      <ol class="space-y-1 text-sm">
        {#each backgroundItems as item}
          <li class="flex gap-2">
            <span class="text-xs text-muted w-32 shrink-0">{wb.dateTime(item.at)}</span>
            <span class="text-xs px-1 rounded bg-surface-2 shrink-0">{KIND_LABELS[item.kind]}</span>
            {#if item.url}<a class="underline" href={item.url} target="_blank" rel="noreferrer">{item.text}</a>{:else}<span>{item.text}</span>{/if}
          </li>
        {:else}
          <li class="text-muted">暂无记录</li>
        {/each}
      </ol>
    </section>

    <!-- ④ 历史：K 线与标注、计划价位、候选 / 决定 / 成交时间线 -->
    <section aria-label="历史" class="space-y-2">
      <h2 class="font-semibold">历史</h2>
      {#if view.bars.length}
        {@const last = view.bars[view.bars.length - 1]}
        <p class="text-xs text-muted">最新日线 {last.price_date}：开 {last.open} · 收 {last.close}（拆股调整、未分红调整）</p>
      {/if}
      {#if view.chart.bars.length}
        {@const chartBars = view.chart.bars.map(b => ({ date: b.price_date, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }))}
        <div data-testid="instrument-chart">
          <CandleChart
            data={chartBars.map(b => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close }))}
            overlays={[
              { color: '#22c55e', data: toLineData(chartBars, view.chart.bars.map(b => b.ma20)) },
              { color: '#60a5fa', data: toLineData(chartBars, view.chart.bars.map(b => b.ma50)) },
              { color: '#f59e0b', data: toLineData(chartBars, view.chart.bars.map(b => b.ma200)) },
            ]}
            markers={annotations?.markers ?? []}
            segments={annotations?.segments ?? []} />
          <VolumeBars bars={chartBars} days={250} />
          <p class="text-xs text-muted">拆股调整、未分红调整 · <span style="color:#22c55e">MA20</span> · <span style="color:#60a5fa">MA50</span> · <span style="color:#f59e0b">MA200</span>
            <ConceptTerm id={I.movingAverage} /></p>
          {#if blockError('chart.annotations')}<p class="text-xs text-muted">图上标注暂不可用：{blockError('chart.annotations')}</p>{/if}
          {#if annotations?.markers?.length || annotations?.segments?.length}
            <p class="text-xs text-muted">标注：▲ 买入候选 · ▼ 卖出候选 · ● 观察候选 · B / S 你的成交 · 计划价位线（入场上下沿、止损、T1）：
              <span style={`color:${KIND_COLOR.rule}`}>规则</span> · <span style={`color:${KIND_COLOR.own}`}>自定</span> · <span style={`color:${KIND_COLOR.agent}`}>Agent</span>（虚线为止损；作废的计划线段淡显）</p>
          {/if}
        </div>
      {:else}
        <p class="text-xs text-muted">暂无日线，等下一次批处理采集</p>
      {/if}

      <div class="text-sm space-y-1">
        <h3 class="font-medium"><ConceptTerm id={I.entryZone}>计划价位</ConceptTerm></h3>
        <p class="text-xs text-muted">说明：<ConceptTerm id={I.stop}>止损</ConceptTerm> <ConceptTerm id={I.target1}>T1</ConceptTerm> <ConceptTerm id={I.chain}>版本链</ConceptTerm></p>
        {#if plans.length}
          <ul aria-label="计划价位" class="space-y-0.5">
            {#each plans as p (p.id)}
              <li>{wb.KIND_TEXT[p.kind] ?? p.kind}{p.kind === 'agent' && p.version_no != null ? ` · 第 ${p.version_no} 版` : ` · ${p.plan_version}`}
                · {planLine(p)} · 有效期 {p.valid_from} 至 {p.valid_until}{p.status === 'invalid' ? ' · 已作废' : ''}
                · <a class="text-accent underline" href={`#plan/${p.id}`}>推导</a>
                <DiscussButton context={{ kind: 'plan', plan_id: p.id }} /></li>
            {/each}
          </ul>
        {:else}
          <p class="text-xs text-muted">图上窗口内没有计划{blockError('plans') ? `（计划列表暂不可用：${blockError('plans')}）` : ''}</p>
        {/if}
        {#if annotations?.omitted}<p class="text-xs text-muted">另有 {annotations.omitted} 份未画</p>{/if}
      </div>

      <p class="text-xs text-muted"><ConceptTerm id={I.position}>候选、决定与成交</ConceptTerm></p>
      <ol class="space-y-1 text-sm">
        {#each historyItems as item}
          <li class="flex gap-2">
            <span class="text-xs text-muted w-32 shrink-0">{wb.dateTime(item.at)}</span>
            <span class="text-xs px-1 rounded bg-surface-2 shrink-0">{KIND_LABELS[item.kind]}</span>
            <span>{item.text}</span>
          </li>
        {:else}
          <li class="text-muted">暂无记录</li>
        {/each}
      </ol>
    </section>
  {/if}
</section>
