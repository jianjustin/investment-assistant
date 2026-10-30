<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import { getTickerChains, getWatchlist, pollRun, recheckChain } from '../lib/api'
  import CandleChart from '../lib/charts/CandleChart.svelte'
  import { readChartTheme } from '../lib/charts/theme'
  import { onThemeChange } from '../lib/theme'
  import { Button } from '$lib/ui/button/index'
  import * as Card from '$lib/ui/card/index'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import MetricValue from '$lib/ui/domain/MetricValue.svelte'
  import PageHeader from '$lib/ui/domain/PageHeader.svelte'
  import PlanLevels from '$lib/ui/domain/PlanLevels.svelte'
  import Section from '$lib/ui/domain/Section.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import ConceptTerm from '../lib/components/ConceptTerm.svelte'
  import DiscussButton from '../lib/components/DiscussButton.svelte'
  import Fundamentals from '../lib/components/Fundamentals.svelte'
  import PlanDerivation from '../lib/components/PlanDerivation.svelte'
  import PlanHistoryTable from '../lib/components/PlanHistoryTable.svelte'
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
  // 「我的补充」只能作用于会被复查的链（入场期 / 持仓期）；进行中的列表还包括退出期（R10）
  const activeChains = $derived(chains.filter(c => tl.REVIEWABLE_STATES.includes(c.state))
    .map(c => ({ signal_date: c.signal_date, label: `${c.signal_date} · 第 ${c.version_no} 版` })))
  const I = ATTACH.instrument
  const liveChains = $derived(chains.filter(c => tl.ACTIVE_STATES.includes(c.state)))

  // v2.9 §10.3：计划历史；两个开关是请求参数，默认关。读不到只影响这一段（029 未执行 → 503 文案）。
  let planHistory = $state<wb.PlanHistoryView | null>(null)
  let historyError = $state('')
  let historyOpts = $state({ include_reviews: false, include_baselines: false })
  let historyGeneration = 0
  async function loadHistory(next: string, token: number) {
    const gen = ++historyGeneration
    try {
      const res = await wb.getPlanHistory(next, historyOpts)
      if (token !== generation || gen !== historyGeneration) return
      planHistory = { ticker: next, rows: Array.isArray(res?.rows) ? res.rows : [], chains: Array.isArray(res?.chains) ? res.chains : [] }
      historyError = ''
    } catch (e) {
      if (token === generation && gen === historyGeneration) { planHistory = null; historyError = wb.describeError(e) }
    }
  }
  function changeHistory(next: { include_reviews: boolean; include_baselines: boolean }) {
    historyOpts = next
    void loadHistory(ticker, generation)
  }
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
  // 接口里的价位是字符串（"95.10"）：PlanLevels 要数字；转不成数字的按缺失处理。
  const num = (value: string | number | null | undefined) => (value == null ? null : Number(value))
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
  // 均线颜色来自图表令牌 --chart-1…3（画布吃十六进制，所以读解析后的值）；图例文字用同名类 text-chart-1…3。切主题时重读。
  let chartTheme = $state(readChartTheme())
  const SELECT = 'h-8 rounded-md border border-input bg-card px-2 text-sm text-foreground'
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
    planHistory = null
    historyError = ''
    historyOpts = { include_reviews: false, include_baselines: false }
    void loadChains(next, token)
    void loadHistory(next, token)
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

  onMount(() => onThemeChange(() => { chartTheme = readChartTheme() }))

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

{#snippet missing()}<StatusPill domain="block" value="not_computed" />{/snippet}

<div class="grid gap-6">
  <PageHeader level={1} title="标的">
    {#snippet actions()}
      <select aria-label="标的" class={SELECT} value={ticker}
              onchange={e => select((e.currentTarget as HTMLSelectElement).value)}>
        {#if ticker && !tickers.includes(ticker)}<option value={ticker}>{ticker}</option>{/if}
        {#each tickers as t}<option value={t}>{t}</option>{/each}
      </select>
    {/snippet}
  </PageHeader>

  {#if error}
    <DataBlock state="error" message={error} />
  {:else if loading}
    <DataBlock state="loading" skeleton="block" />
  {:else if !ticker}
    <DataBlock state="empty" message="观察名单为空，请在「更多 → 设置 → 关注列表」添加美股。" />
  {/if}

  {#if view}
    <PageHeader level={2} title={`${view.ticker} · 截至 ${view.session}`} />

    <!-- ① 信号与计划：首屏先回答「今天该关注什么」 -->
    <Section level={2} title="信号与计划">
      {#if blockError('focus')}<DataBlock state="error" message={`今天该关注什么暂不可用：${blockError('focus')}`} />{/if}
      {#if focus.length}
        <ul aria-label="今天该关注什么" class="grid gap-1 text-sm">
          {#each focus as item, i (i)}
            <li class="border-l-2 border-primary/50 pl-2">{item.text}
              {#if item.link}<a class="text-primary underline" href={item.link}>查看</a>{/if}
              {#each item.concepts as id, i (i)}<span class="text-xs"> <ConceptTerm {id} /></span>{/each}
            </li>
          {/each}
        </ul>
      {/if}

      {#if todays.length}
        <div class="grid gap-1 text-sm">
          <p class="text-xs text-muted-foreground"><ConceptTerm id={I.trigger}>今日触发</ConceptTerm></p>
          <ul aria-label="今日触发" class="grid gap-1">
            {#each todays as c (c.id)}
              <li>
                <ConceptTerm id={ruleConcept(c.rule_id)}>{wb.ruleLabel(c.rule_id)}</ConceptTerm> → {wb.ACTION_LABELS[c.action]}
                <span class="text-xs text-muted-foreground">{candidateValues(c)}</span>
                <Button variant="link" size="sm" class="text-xs" aria-expanded={!!triggerOpen[c.id]}
                        onclick={() => triggerOpen[c.id] = !triggerOpen[c.id]}>触发依据</Button>
                {#if triggerOpen[c.id]}<PlanDerivation unit={{ ticker: view.ticker, signal_date: c.signal_date }} />{/if}
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      <Card.Root size="sm" class="gap-1 px-3 text-sm">
        <h3 class="font-medium"><ConceptTerm id={I.chain}>Agent 计划</ConceptTerm></h3>
        {#if chainsError}
          <DataBlock state="error" message={`Agent 计划列表不可用：${chainsError}`} />
        {:else if liveChains.length}
          <ul aria-label="Agent 计划" class="grid gap-1">
            {#each liveChains as c (c.signal_date)}
              {@const head = planOfHead(c.head_plan_id)}
              {@const rk = rechecks[c.signal_date]}
              <li>{chainLine(c)}{#if head} · <PlanLevels low={num(head.entry_low)} high={num(head.entry_high)} stop={num(head.stop)} target1={num(head.target1)} />{/if} · <a class="text-primary underline" href={`#plan/${c.head_plan_id}`}>查看</a>
                <Button size="sm" class="text-xs" busy={rk?.busy} disabled={c.state === 'exiting'} title={c.state === 'exiting' ? wb.CHAIN_EXITING_TEXT : ''}
                        onclick={() => recheck(c)}>重新复查</Button>
                <DiscussButton context={{ kind: 'plan', plan_id: c.head_plan_id }} />
                {#if rk?.text}<span class="text-xs">{rk.text}</span>{/if}
                {#if c.latest_review?.reason}<p class="text-xs text-muted-foreground">{c.latest_review.reason}</p>{/if}
              </li>
            {/each}
          </ul>
        {:else if chains.length}
          <DataBlock state="empty" message="没有进行中的 Agent 计划，已结束的见下方计划历史" />
        {:else}
          <DataBlock state="empty" message="该标的还没有 Agent 版本链" />
        {/if}
      </Card.Root>

      {#if livePlans.length}
        <div class="grid gap-1 text-sm">
          <p class="text-xs text-muted-foreground"><ConceptTerm id={I.entryZone}>当前有效的规则 / 自定计划</ConceptTerm></p>
          <ul aria-label="当前有效的计划" class="grid gap-1">
            {#each livePlans as p (p.id)}
              <li>{wb.KIND_TEXT[p.kind] ?? p.kind} · {p.plan_version} · <PlanLevels low={num(p.entry_low)} high={num(p.entry_high)} stop={num(p.stop)} target1={num(p.target1)} /> · 有效期至 {p.valid_until}
                · <a class="text-primary underline" href={`#plan/${p.id}`}>推导</a></li>
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
              · T1 {#if h.target1 != null}{h.target1}{:else}{@render missing()}{/if}（{h.t1_reached ? '已触 T1' : '未触 T1'}）<span class="text-xs"><ConceptTerm id={I.target1}>T1</ConceptTerm></span>
              · 收盘 {#if h.last_close != null}{h.last_close}{:else}{@render missing()}{/if} · 距止损 <MetricValue value={h.to_stop_pct} percent signed /> · 距 T1 <MetricValue value={h.to_target_pct} percent signed />
            {:else}
              无计划持仓（回撤规则看护）
            {/if}
          </p>
        {:else if blockError('holding')}
          <DataBlock state="error" message={`当前止损与 T1 暂不可用：${blockError('holding')}`} />
        {/if}
      {:else}
        <DataBlock state="empty" message="当前无持仓" />
      {/if}

      {#if timelineMissing}
        <Card.Root size="sm" role="region" aria-label="我的补充" class="gap-1 px-3 text-sm">
          <h2 class="text-base font-medium">我的补充</h2>
          <p class="text-xs text-muted-foreground"><ConceptTerm id={I.userInput}>用户输入说明</ConceptTerm></p>
          <DataBlock state="error" message={`暂不可用：${chainsError}`} />
        </Card.Root>
      {:else}
        <p class="text-xs text-muted-foreground"><ConceptTerm id={I.userInput}>用户输入说明</ConceptTerm></p>
        {#key view.ticker}
          <UserInputs ticker={view.ticker} chains={activeChains} />
        {/key}
      {/if}

      <Section level={3} title="计划历史">
        {#snippet actions()}<span class="text-xs"><ConceptTerm id={I.chain}>说明</ConceptTerm></span>{/snippet}
        {#if historyError}
          <DataBlock state="error" message={`计划历史暂不可用：${historyError}`} />
        {:else if planHistory}
          <PlanHistoryTable rows={planHistory.rows} chains={planHistory.chains} ticker={view.ticker}
                            includeReviews={historyOpts.include_reviews} includeBaselines={historyOpts.include_baselines}
                            onToggle={changeHistory} />
        {:else}
          <DataBlock state="loading" skeleton="table" />
        {/if}
      </Section>
    </Section>

    <!-- ①' 我的知识：挂在这个标的上的有效经验（v2.7） -->
    <Section level={2} title="我的知识">
      <p class="text-xs text-muted-foreground"><ConceptTerm id={ATTACH.myKnowledge.item}>说明</ConceptTerm>
        · <a class="text-primary underline" href={`#knowledge/mine/new?ticker=${encodeURIComponent(view.ticker)}`}>写一条</a></p>
      {#if blockError('knowledge')}
        <DataBlock state="error" message={`暂不可用：${blockError('knowledge')}`} />
      {:else if knowledge.length}
        <ul aria-label="我的知识条目" class="grid gap-1 text-sm">
          {#each knowledge as e (e.id)}
            <li><a class="text-primary underline" href={`#knowledge/mine/${e.id}`}>{e.title}</a>
              <span class="text-xs text-muted-foreground"> · 适用范围：{e.scope} · 第 {e.current_version} 版 · 被引用 {e.citation_count} 次</span></li>
          {/each}
        </ul>
      {:else}
        <DataBlock state="empty" message={`还没有挂在 ${view.ticker} 上的经验`} />
      {/if}
    </Section>

    <!-- ② 关键数据：与 Agent 工具同一个纯函数现算，截至最近收盘 -->
    <Section level={2} title="关键数据">
      {#if view.key_data}
        {@const kd = view.key_data}
        <p class="text-xs text-muted-foreground">截至 {#if kd.as_of}{kd.as_of}{:else}{@render missing()}{/if}
          {#if focusPlanLink} · 焦点计划 <a class="text-primary underline" href={focusPlanLink}>看推导</a>{/if}</p>
        <ul aria-label="关键数据" class="grid grid-cols-1 gap-x-6 gap-y-0.5 text-sm md:grid-cols-2">
          {#each KEY_LABELS as [key, label] (key)}
            <li class="flex justify-between gap-2">
              <span class="text-muted-foreground">{#if kd.concepts?.[key]}<ConceptTerm id={kd.concepts[key]}>{label}</ConceptTerm>{:else}{label}{/if}</span>
              <span class="tabular-nums">{kd.values?.[key] ?? '—'}</span>
            </li>
          {/each}
        </ul>
      {:else if blockError('key_data')}
        <DataBlock state="error" message={`暂无关键数据：${blockError('key_data')}`} />
      {:else}
        <DataBlock state="empty" message="暂无关键数据" />
      {/if}
    </Section>

    <!-- ③ 背景：财报日、区制、行业、基本面、近期资讯与 SEC 文件 -->
    <Section level={2} title="背景">
      {#if blockError('context')}<DataBlock state="error" message={`财报日、区制与行业暂不可用：${blockError('context')}`} />{/if}
      <ul aria-label="背景要点" class="grid gap-0.5 text-sm">
        <li><ConceptTerm id={I.earnings}>下次财报</ConceptTerm>：
          {#if view.context?.earnings?.date}
            {view.context.earnings.date}（{#if view.context.earnings.status}{EARNINGS_STATUS[view.context.earnings.status] ?? view.context.earnings.status}{:else}{@render missing()}{/if}{#if view.context.earnings.sessions_until != null}，距今 {view.context.earnings.sessions_until} 个交易日{/if}）
          {:else}下次财报日未知{/if}</li>
        <li><ConceptTerm id={I.regime}>区制</ConceptTerm>：
          {#if view.context?.regime}{wb.REGIME_LABELS[view.context.regime.label] ?? view.context.regime.label}（{view.context.regime.session}）{:else}未生成{/if}</li>
        <li><ConceptTerm id={I.sector}>行业强弱</ConceptTerm>：
          {#if view.context?.sector}
            {view.context.sector.etf} {view.context.sector.state ? (wb.SECTOR_STATE_LABELS[view.context.sector.state] ?? view.context.sector.state) : '数据不足'}
            · rs20 {#if view.context.sector.rs20 != null}{view.context.sector.rs20}{:else}{@render missing()}{/if} · rs60 {#if view.context.sector.rs60 != null}{view.context.sector.rs60}{:else}{@render missing()}{/if}
          {:else}未映射行业 ETF{/if}</li>
      </ul>
      <Fundamentals ticker={view.ticker} />
      <p class="text-xs text-muted-foreground"><ConceptTerm id={I.news}>近期资讯</ConceptTerm> 与 <ConceptTerm id={I.filings}>SEC 文件</ConceptTerm></p>
      <ol class="grid gap-1 text-sm">
        {#each backgroundItems as item}
          <li class="flex gap-2">
            <span class="w-32 shrink-0 text-xs text-muted-foreground">{wb.dateTime(item.at)}</span>
            <span class="shrink-0 rounded-sm bg-muted px-1 text-xs">{KIND_LABELS[item.kind]}</span>
            {#if item.url}<a class="text-primary underline" href={item.url} target="_blank" rel="noreferrer">{item.text}</a>{:else}<span>{item.text}</span>{/if}
          </li>
        {:else}
          <li class="text-muted-foreground">暂无记录</li>
        {/each}
      </ol>
    </Section>

    <!-- ④ 历史：K 线与标注、计划价位、候选 / 决定 / 成交时间线 -->
    <Section level={2} title="历史">
      {#if view.bars.length}
        {@const last = view.bars[view.bars.length - 1]}
        <p class="text-xs text-muted-foreground">最新日线 {last.price_date}：开 {last.open} · 收 {last.close}（拆股调整、未分红调整）</p>
      {/if}
      {#if view.chart.bars.length}
        {@const chartBars = view.chart.bars.map(b => ({ date: b.price_date, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }))}
        <div data-testid="instrument-chart" class="grid gap-2">
          <CandleChart
            data={chartBars.map(b => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close }))}
            overlays={[
              { color: chartTheme.series[0], data: toLineData(chartBars, view.chart.bars.map(b => b.ma20)) },
              { color: chartTheme.series[1], data: toLineData(chartBars, view.chart.bars.map(b => b.ma50)) },
              { color: chartTheme.series[2], data: toLineData(chartBars, view.chart.bars.map(b => b.ma200)) },
            ]}
            markers={annotations?.markers ?? []}
            segments={annotations?.segments ?? []} />
          <VolumeBars bars={chartBars} days={250} />
          <p class="text-xs text-muted-foreground">拆股调整、未分红调整 · <span class="text-chart-1">MA20</span> · <span class="text-chart-2">MA50</span> · <span class="text-chart-3">MA200</span>
            <ConceptTerm id={I.movingAverage} /></p>
          {#if blockError('chart.annotations')}<DataBlock state="error" message={`图上标注暂不可用：${blockError('chart.annotations')}`} />{/if}
          {#if annotations?.markers?.length || annotations?.segments?.length}
            <p class="text-xs text-muted-foreground">标注：▲ 买入候选 · ▼ 卖出候选 · ● 观察候选 · B / S 你的成交 · 计划价位线（入场上下沿、止损、T1）：
              <span class="text-chart-rule">规则</span> · <span class="text-chart-own">自定</span> · <span class="text-chart-agent">Agent</span>（虚线为止损；作废的计划线段淡显）</p>
          {/if}
        </div>
      {:else}
        <DataBlock state="empty" message="暂无日线，等下一次批处理采集" />
      {/if}

      <div class="grid gap-1 text-sm">
        <h3 class="font-medium"><ConceptTerm id={I.entryZone}>计划价位</ConceptTerm></h3>
        <p class="text-xs text-muted-foreground">说明：<ConceptTerm id={I.stop}>止损</ConceptTerm> <ConceptTerm id={I.target1}>T1</ConceptTerm> <ConceptTerm id={I.chain}>版本链</ConceptTerm></p>
        {#if plans.length}
          <ul aria-label="计划价位" class="grid gap-0.5">
            {#each plans as p (p.id)}
              <li class={p.status === 'invalid' ? 'text-muted-foreground' : ''}>{wb.KIND_TEXT[p.kind] ?? p.kind}{p.kind === 'agent' && p.version_no != null ? ` · 第 ${p.version_no} 版` : ` · ${p.plan_version}`}
                · <PlanLevels low={num(p.entry_low)} high={num(p.entry_high)} stop={num(p.stop)} target1={num(p.target1)} /> · 有效期 {p.valid_from} 至 {p.valid_until}{p.status === 'invalid' ? ' · 已作废' : ''}
                · <a class="text-primary underline" href={`#plan/${p.id}`}>推导</a>
                <DiscussButton context={{ kind: 'plan', plan_id: p.id }} /></li>
            {/each}
          </ul>
        {:else}
          <DataBlock state="empty" message={`图上窗口内没有计划${blockError('plans') ? `（计划列表暂不可用：${blockError('plans')}）` : ''}`} />
        {/if}
        {#if annotations?.omitted}<p class="text-xs text-muted-foreground">另有 {annotations.omitted} 份未画</p>{/if}
      </div>

      <p class="text-xs text-muted-foreground"><ConceptTerm id={I.position}>候选、决定与成交</ConceptTerm></p>
      <ol class="grid gap-1 text-sm">
        {#each historyItems as item}
          <li class="flex gap-2">
            <span class="w-32 shrink-0 text-xs text-muted-foreground">{wb.dateTime(item.at)}</span>
            <span class="shrink-0 rounded-sm bg-muted px-1 text-xs">{KIND_LABELS[item.kind]}</span>
            <span>{item.text}</span>
          </li>
        {:else}
          <li class="text-muted-foreground">暂无记录</li>
        {/each}
      </ol>
    </Section>
  {/if}
</div>
