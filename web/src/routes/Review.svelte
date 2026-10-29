<script lang="ts">
  import { onMount } from 'svelte'
  import { fmtPct } from '../lib/format'
  import * as wb from '../lib/workbench'
  import * as api from '../lib/api'
  import Drawer from '../lib/components/Drawer.svelte'
  import ConceptTerm from '../lib/components/ConceptTerm.svelte'
  import ReviewCard from '../lib/components/ReviewCard.svelte'
  import ReviewCardList from '../lib/components/ReviewCardList.svelte'
  import { ATTACH } from '../lib/knowledge'
  import { actualRText, knowHref } from '../lib/growth'
  import type { WeeklyLearning } from '../lib/growth'

  let { sub }: { sub?: string } = $props()
  const TABS = [['trades', '交易与持仓'], ['cards', '复盘卡'], ['shadow', '对照组'], ['tracks', '轨道对比'], ['weekly', '周度复盘'],
                 ['monthly', '月度复盘'], ['account', '资金'], ['backchecks', '上线前检查']] as const
  // sub is the path below #review/: `cards`, `cards/12`, `weekly` …
  const head = $derived(sub?.split('/')[0])
  let tab = $derived(TABS.some(([id]) => id === head) ? head! : 'trades')
  const cardId = $derived.by(() => {
    const m = /^cards\/(\d+)$/.exec(sub ?? '')
    return m ? Number(m[1]) : null
  })
  // 页签上的待审定数（v2.7 §4.7）；读不到（如迁移 027 未执行）就不显示
  let toReview = $state(0)
  async function loadCardCounts() {
    try { toReview = (await api.getReviewCards({}))?.counts?.to_review ?? 0 } catch { toReview = 0 }
  }
  $effect(() => { void sub; void loadCardCounts() })

  let error = $state('')
  let trades = $state<wb.Trade[]>([])
  let tradeReview = $state<wb.TradeReview | null>(null)
  let shadow = $state<wb.ShadowView | null>(null)
  let weekly = $state<wb.WeeklyReview[] | null>(null)
  let monthly = $state<wb.MonthlyReview[] | null>(null)
  let account = $state<wb.AccountView | null>(null)
  let backchecks = $state<wb.Backcheck[] | null>(null)
  let tracks = $state<wb.TracksView | null>(null)
  let callDrawer = $state<{ open: boolean; calls: wb.AgentToolCall[]; call: wb.AgentToolCall | null }>({ open: false, calls: [], call: null })
  let pushResults = $state<Record<string, string>>({})
  let pushes = $state<wb.ReviewPush[]>([])
  let backcheckNote = $state('')
  let backcheckError = $state('')

  const emptyForm = () => ({ ticker: '', side: 'buy', quantity: '', price: '', fee: '0', executed: '', decisionId: '', note: '',
                             requestId: wb.newRequestId() })
  let form = $state(emptyForm())
  let formError = $state('')
  let voiding = $state<string | null>(null)
  let voidReason = $state('')

  function monday(d = new Date()): string {
    const copy = new Date(d)
    copy.setDate(copy.getDate() - ((copy.getDay() + 6) % 7))
    return copy.toISOString().slice(0, 10)
  }
  function summaryRows(view: wb.TracksView): { pool: string; track: string; s: wb.TrackStats }[] {
    const out: { pool: string; track: string; s: wb.TrackStats }[] = []
    const pools: [string, Record<'rule' | 'agent' | 'actual', wb.TrackStats>][] = [
      ['全部', view.summary.all], ['核心池', view.summary.core], ['扩展池', view.summary.extended]]
    for (const [pool, group] of pools)
      for (const [track, s] of [['规则', group.rule], ['Agent', group.agent], ['实际', group.actual]] as [string, wb.TrackStats][])
        out.push({ pool, track, s })
    return out
  }

  async function openRun(runId: string) {
    const detail = await wb.getAgentRun(runId)
    callDrawer = { open: true, calls: detail.tool_calls, call: detail.tool_calls[0] ?? null }
  }

  // §8.2: the latest recorded attempt (scheduled or manual) beside each card's push button
  async function loadPushes() {
    try { pushes = (await wb.getReviewPushes()).pushes ?? [] } catch { pushes = [] }
  }
  function lastPushText(kind: string, period: string): string {
    const p = pushes.find(x => x.kind === kind && x.period === period)   // newest first
    if (!p) return ''
    const outcome = p.sent ? '已推送' : '未推送：' + (p.reason ?? '未知原因')
    return `最近推送 ${wb.dateTime(p.created_at)} · ${outcome} · ${p.trigger_source === 'scheduled' ? '定时' : '手动'}`
  }

  async function push(kind: string, period: string) {
    const key = kind + ':' + period
    pushResults[key] = '推送中…'
    pushResults = pushResults
    try {
      const out = await wb.postReviewPush(kind as any, period)
      pushResults[key] = out.sent ? '已推送' : ('未推送：' + (out.reason ?? '未知原因'))
      pushResults = pushResults
      loadPushes()
    } catch (e) {
      pushResults[key] = wb.describeError(e)
      pushResults = pushResults
    }
  }

  let weekStart = $state(monday())
  let weekNotes = $state('')
  let weekError = $state('')

  async function load(which: string) {
    error = ''
    try {
      if (which === 'trades') {
        const [list, reviewed, decided] = await Promise.all([wb.getTrades(), wb.getTradeReview(), wb.getShadow()])
        trades = list.trades
        tradeReview = reviewed
        shadow = decided
      } else if (which === 'shadow') {
        shadow = await wb.getShadow()
      } else if (which === 'cards') {
        // the cards tab loads itself
      } else if (which === 'tracks') {
        tracks = await wb.getTracks()
      } else if (which === 'monthly') {
        monthly = (await wb.getMonthly()).reviews
        loadPushes()
      } else if (which === 'account') {
        account = await wb.getAccount()
      } else if (which === 'backchecks') {
        backchecks = (await wb.getBackchecks()).backchecks
      } else {
        weekly = (await wb.getWeekly()).reviews
        loadPushes()
      }
    } catch (e) {
      error = wb.describeError(e)
    }
  }

  $effect(() => { load(tab) })

  const linkable = $derived((shadow?.units ?? []).filter(
    u => u.ticker === form.ticker.trim().toUpperCase() && (u.final_action === 'buy' || u.final_action === 'sell')))

  async function recordTrade(e: Event) {
    e.preventDefault()
    formError = ''
    const executed = new Date(form.executed)
    if (Number.isNaN(executed.getTime())) { formError = '请填写成交时间'; return }
    try {
      await wb.postTrade({
        request_id: form.requestId, ticker: form.ticker.trim().toUpperCase(), side: form.side,
        quantity: String(form.quantity), price: String(form.price), fee: String(form.fee || '0'),
        executed_at: executed.toISOString(), decision_id: form.decisionId || null, note: form.note || null,
      })
      form = emptyForm()
      await load('trades')
    } catch (err) {
      formError = wb.describeError(err)
    }
  }

  async function runBackcheckNow() {
    backcheckError = ''; backcheckNote = ''
    try {
      const record = await wb.runBackcheck()
      backcheckNote = record.stats?.note ?? ''
      await load('backchecks')
    } catch (e) {
      backcheckError = wb.describeError(e)
    }
  }

  async function confirmVoid(id: string) {
    if (!voidReason.trim()) return
    try {
      await wb.voidTrade(id, voidReason.trim())
      voiding = null
      voidReason = ''
      await load('trades')
    } catch (err) {
      formError = wb.describeError(err)
    }
  }

  async function generateWeekly(e: Event) {
    e.preventDefault()
    weekError = ''
    const head = weekly?.find(r => r.week_start === weekStart)
    try {
      await wb.postWeekly({ week_start: weekStart, notes: weekNotes, supersedes_id: head?.id ?? null })
      weekNotes = ''
      await load('weekly')
    } catch (err) {
      weekError = wb.describeError(err)
    }
  }

  const monthForm = () => ({ month: '', notes: '', requestId: wb.newRequestId() })
  let monthFormState = $state(monthForm())
  let monthError = $state('')

  async function generateMonthly(e: Event) {
    e.preventDefault()
    monthError = ''
    if (!/^\d{4}-\d{2}-01$/.test(monthFormState.month)) { monthError = '月份须为当月 1 日（YYYY-MM-01）'; return }
    const head = monthly?.find(r => r.month === monthFormState.month)
    try {
      await wb.postMonthly({ month: monthFormState.month, notes: monthFormState.notes,
                             supersedes_id: head?.id ?? null })
      monthFormState = monthForm()
      await load('monthly')
    } catch (err) {
      monthError = wb.describeError(err)
    }
  }

  const snapshotForm = () => ({ as_of: '', equity: '', note: '', requestId: wb.newRequestId() })
  let snap = $state(snapshotForm())
  const flowForm = () => ({ flow_date: '', amount: '', note: '', requestId: wb.newRequestId() })
  let flow = $state(flowForm())
  let accountError = $state('')
  let voidingFlow = $state<string | null>(null)
  let flowVoidReason = $state('')

  async function recordSnapshot(e: Event) {
    e.preventDefault()
    accountError = ''
    try {
      await wb.postSnapshot({ request_id: snap.requestId, as_of: snap.as_of, equity: String(snap.equity),
                              note: snap.note || null })
      snap = snapshotForm()
      account = await wb.getAccount()
    } catch (err) {
      accountError = wb.describeError(err)
    }
  }

  async function recordFlow(e: Event) {
    e.preventDefault()
    accountError = ''
    try {
      await wb.postFlow({ request_id: flow.requestId, flow_date: flow.flow_date, amount: String(flow.amount),
                          note: flow.note || null })
      flow = flowForm()
      account = await wb.getAccount()
    } catch (err) {
      accountError = wb.describeError(err)
    }
  }

  async function voidAFlow(id: string) {
    if (!flowVoidReason.trim()) return
    try {
      await wb.voidFlow(id, flowVoidReason.trim())
      voidingFlow = null
      flowVoidReason = ''
      account = await wb.getAccount()
    } catch (err) {
      accountError = wb.describeError(err)
    }
  }

  const windowText = (w: wb.Window | undefined) =>
    !w || w.status === 'immature' ? '未成熟' : w.excess !== undefined ? wb.pct(w.excess) : `走势 ${wb.pct(w.move)}`

  onMount(() => () => { voiding = null })
</script>

<section class="space-y-4">
  <header class="flex items-center gap-4">
    <h1 class="text-lg font-semibold">复盘</h1>
    <nav class="flex gap-2 text-sm">
      {#each TABS as [id, label]}
        <a href={`#review/${id}`} aria-current={tab === id ? 'page' : undefined}
           class="px-2 py-1 rounded {tab === id ? 'bg-accent/10 text-accent' : 'text-muted hover:text-ink'}">{label}{#if id === 'cards' && toReview > 0}<span
             aria-label={`待审定 ${toReview} 张`} title={`待审定 ${toReview} 张`}
             class="ml-1 px-1.5 text-xs rounded-full bg-accent text-white">{toReview}</span>{/if}</a>
      {/each}
    </nav>
  </header>
  <p class="text-xs text-muted">描述性统计：股票少、样本重叠，不代表任何规则有效。</p>

  {#if error}<p role="alert" class="text-sm text-red-600">{error}</p>{/if}

  {#if tab === 'cards'}
    {#if cardId !== null}
      <ReviewCard id={cardId} />
    {:else}
      <ReviewCardList oncounts={counts => toReview = counts.to_review ?? 0} />
    {/if}
  {/if}

  {#if tab === 'trades' && !error}
    <form class="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm border border-border rounded p-3" onsubmit={recordTrade}>
      <label class="flex flex-col">代码<input aria-label="代码" class="border border-border rounded px-2 py-1 bg-bg" bind:value={form.ticker} /></label>
      <label class="flex flex-col">方向
        <select aria-label="方向" class="border border-border rounded px-2 py-1 bg-bg" bind:value={form.side}>
          <option value="buy">买入</option><option value="sell">卖出</option>
        </select>
      </label>
      <label class="flex flex-col">数量<input aria-label="数量" inputmode="decimal" class="border border-border rounded px-2 py-1 bg-bg" bind:value={form.quantity} /></label>
      <label class="flex flex-col">成交价<input aria-label="成交价" inputmode="decimal" class="border border-border rounded px-2 py-1 bg-bg" bind:value={form.price} /></label>
      <label class="flex flex-col">费用<input aria-label="费用" inputmode="decimal" class="border border-border rounded px-2 py-1 bg-bg" bind:value={form.fee} /></label>
      <label class="flex flex-col">成交时间（本机时区）<input aria-label="成交时间" type="datetime-local" class="border border-border rounded px-2 py-1 bg-bg" bind:value={form.executed} /></label>
      <label class="flex flex-col">关联决定
        <select aria-label="关联决定" class="border border-border rounded px-2 py-1 bg-bg" bind:value={form.decisionId}>
          <option value="">无（无信号交易）</option>
          {#each linkable as u}<option value={u.id}>{u.signal_date} {wb.ACTION_LABELS[u.final_action]}</option>{/each}
        </select>
      </label>
      <label class="flex flex-col">备注<input aria-label="备注" class="border border-border rounded px-2 py-1 bg-bg" bind:value={form.note} /></label>
      <div class="col-span-full flex items-center gap-2">
        <button type="submit" class="px-3 py-1 rounded bg-accent text-white">记录成交</button>
        {#if formError}<span class="text-xs text-red-600">{formError}</span>{/if}
      </div>
    </form>

    {#if tradeReview}
      <h2 class="font-semibold text-sm">当前持仓</h2>
      <ul class="text-sm">
        {#each tradeReview.open as p}
          <li>{p.ticker} {p.quantity} 股 · 成本 {Number(p.avg_cost).toFixed(2)} · 收盘 {p.last_close}（{p.as_of}）· 浮动盈亏 {Number(p.unrealized_pnl).toFixed(2)}（{wb.pct(p.unrealized_return)}）</li>
        {:else}<li class="text-muted">无持仓</li>{/each}
      </ul>
      <h2 class="font-semibold text-sm">已平仓</h2>
      <ul class="text-sm">
        {#each tradeReview.closed as s}
          <li>{s.ticker} {s.opened} → {s.closed}（{s.holding_sessions} 个交易日）· 盈亏 {Number(s.realized_pnl).toFixed(2)}（{wb.pct(s.return)}）· 同期 SPY {wb.pct(s.spy_return)} · 最大浮盈 {wb.pct(s.max_favorable)} / 最大浮亏 {wb.pct(s.max_adverse)}</li>
        {:else}<li class="text-muted">暂无</li>{/each}
      </ul>
    {/if}

    <h2 class="font-semibold text-sm">成交记录</h2>
    <ul class="text-sm space-y-1">
      {#each trades as t (t.id)}
        <li class={t.voided_at ? 'line-through text-muted' : ''}>
          {wb.dateTime(t.executed_at)} {t.ticker} {t.side === 'buy' ? '买入' : '卖出'} {t.quantity} @ {t.price}（费 {t.fee}）{t.decision_id ? '' : ' · 无信号'}
          {#if t.voided_at}<span class="no-underline">（已作废：{t.void_reason}）</span>
          {:else if voiding === t.id}
            <input aria-label="作废理由" class="border border-border rounded px-1 text-xs bg-bg" bind:value={voidReason} />
            <button class="text-xs text-red-600 disabled:opacity-50" disabled={!voidReason.trim()} onclick={() => confirmVoid(t.id)}>确认作废</button>
            <button class="text-xs" onclick={() => { voiding = null; voidReason = '' }}>取消</button>
          {:else}
            <button class="text-xs text-muted hover:text-red-600" onclick={() => { voiding = t.id; voidReason = '' }}>作废</button>
          {/if}
        </li>
      {:else}<li class="text-muted">暂无成交</li>{/each}
    </ul>
  {/if}

  {#if tab === 'shadow' && shadow && !error}
    <p class="text-xs text-muted">假设下一交易日开盘入场；数值为相对 SPY 的超额收益，卖出取反（避开的跌幅）。自 {shadow.since} 起，口径 {shadow.calc_version}。</p>
    <table class="text-sm w-full">
      <thead><tr class="text-left text-xs text-muted"><th>标的</th><th>信号日</th><th>规则</th><th>建议</th><th>决定</th><th>5 日</th><th>10 日</th><th>20 日</th></tr></thead>
      <tbody>
        {#each shadow.units as u (u.id)}
          <tr>
            <td>{u.ticker}</td><td>{u.signal_date}</td><td>{u.rule_ids.map(wb.ruleLabel).join('、')}</td>
            <td>{wb.ACTION_LABELS[u.proposed_action]}</td><td>{wb.CHOICE_LABELS[u.decision]}</td>
            {#if u.outcome.status === 'pending_entry'}
              <td colspan="3" class="text-muted">待入场</td>
            {:else}
              {#each ['5', '10', '20'] as n}<td>{windowText(u.outcome.windows[n])}</td>{/each}
            {/if}
          </tr>
        {:else}<tr><td colspan="8" class="text-muted">暂无已决定的信号</td></tr>{/each}
      </tbody>
    </table>
  {/if}

  {#if tab === 'tracks' && !error}
    {#if tracks}
      <p class="text-xs text-muted">同一批买入单元的三条轨道（R 按各自计划的止损计）；自 {tracks.since} 至 {tracks.until}，口径 {tracks.calc_version}。</p>
      <table class="text-xs w-full">
        <thead><tr class="text-left text-muted"><th>池</th><th>轨道</th><th>单元</th><th>已定</th><th>待定</th><th>缺失</th><th>均值</th><th>中位</th><th>合计</th><th>盈利</th></tr></thead>
        <tbody>
          {#each summaryRows(tracks) as row}
            <tr><td>{row.pool}</td><td>{row.track}</td><td>{row.s.units}</td><td>{row.s.determined}</td><td>{row.s.pending}</td><td>{row.s.missing}</td>
                <td>{wb.rText(row.s.mean)}</td><td>{wb.rText(row.s.median)}</td><td>{wb.rText(row.s.sum)}</td><td>{row.s.wins}</td></tr>
          {/each}
        </tbody>
      </table>
      <table class="text-sm w-full mt-3">
        <thead><tr class="text-left text-xs text-muted"><th>标的</th><th>信号日</th><th>池</th><th>规则</th><th>Agent</th><th>实际</th></tr></thead>
        <tbody>
          {#each tracks.units as u (u.ticker + u.signal_date)}
            <tr>
              <td><a class="text-accent" href={`#instrument/${u.ticker}`}>{u.ticker}</a></td>
              <td>{u.signal_date}</td>
              <td>{u.pool === 'core' ? '核心' : '扩展'}</td>
              <td>{wb.TRACK_STATUS_TEXT[u.rule.status]} {wb.rText(u.rule.r)}{#if u.rule.plan_id} · <a class="text-accent" href={`#plan/${u.rule.plan_id}`}>计划 {String(u.rule.plan_id).slice(0, 8)}</a>{/if}</td>
              <td>{wb.TRACK_STATUS_TEXT[u.agent.status]} {wb.rText(u.agent.r)}{#if u.agent.run_id} · <button class="text-accent underline" onclick={() => openRun(u.agent.run_id!)}>{String(u.agent.run_id).slice(0, 8)}</button>{/if}</td>
              <td>{wb.TRACK_STATUS_TEXT[u.actual.status]} {wb.rText(u.actual.r)}{#if u.actual.plan_kind} · 照{wb.KIND_TEXT[u.actual.plan_kind]}{/if}</td>
            </tr>
          {:else}<tr><td colspan="6" class="text-muted">窗口内没有可比单元</td></tr>{/each}
        </tbody>
      </table>

    {:else}
      <p class="text-sm text-muted">加载中…</p>
    {/if}
  {/if}

  {#if tab === 'weekly' && weekly && !error}
    <form class="flex flex-wrap items-end gap-2 text-sm border border-border rounded p-3" onsubmit={generateWeekly}>
      <label class="flex flex-col">周一<input aria-label="周一" type="date" class="border border-border rounded px-2 py-1 bg-bg" bind:value={weekStart} /></label>
      <label class="flex flex-col flex-1">复盘笔记<textarea aria-label="复盘笔记" rows="2" class="border border-border rounded px-2 py-1 bg-bg" bind:value={weekNotes}></textarea></label>
      <button type="submit" class="px-3 py-1 rounded bg-accent text-white">生成复盘</button>
      {#if weekError}<span class="text-xs text-red-600">{weekError}</span>{/if}
    </form>
    {#each weekly as r (r.id)}
      <article class="border border-border rounded p-3 text-sm space-y-2">
        <h2 class="font-semibold">{r.stats.week?.start ?? r.week_start} 周 · 已决定 {r.stats.units?.decided ?? 0} · 未处理 {r.stats.units?.undecided ?? 0}
          <button class="ml-2 px-2 py-0.5 rounded bg-accent text-white text-xs" onclick={() => push('weekly', r.week_start)}>推送到 Discord</button>
          {#if pushResults['weekly:' + r.week_start]}<span class="text-xs text-muted">{pushResults['weekly:' + r.week_start]}</span>
          {:else if lastPushText('weekly', r.week_start)}<span class="text-xs text-muted">{lastPushText('weekly', r.week_start)}</span>{/if}
        </h2>
        <p class="text-xs text-muted">{r.stats.note} 口径 {r.calc_version} · 生成于 {wb.dateTime(r.created_at)}{r.supersedes_id ? ' · 更正版' : ''}</p>
        {#if r.notes}<p>{r.notes}</p>{/if}
        {#each [['按规则', r.stats.by_rule], ['按决定', r.stats.by_decision]] as [title, groups]}
          {#if groups && Object.keys(groups).length}
            <p class="text-xs text-muted">{title}（超额收益：均值 / 中位数 · 成熟数/总数）</p>
            <ul>
              {#each Object.entries(groups) as [name, windows]}
                <li>{title === '按规则' ? wb.ruleLabel(name) : wb.CHOICE_LABELS[name as wb.Choice] ?? name}：
                  {#each ['5', '10', '20'] as n}{@const s = (windows as any)[n]}
                    {n} 日 {wb.pct(s?.mean)} / {wb.pct(s?.median)}（{s?.mature ?? 0}/{s?.count ?? 0}）{' '}
                  {/each}
                </li>
              {/each}
            </ul>
          {/if}
        {/each}
        {#if r.stats.by_pool && Object.keys(r.stats.by_pool).length}
          <p class="text-xs text-muted">分池视角（触发 / 计划 / 过期 / 成交 / R 均值 / 中位数）</p>
          <table class="text-xs w-full">
            <thead><tr class="text-left text-muted"><th>池</th><th>规则</th><th>触发</th><th>计划</th><th>过期</th><th>成交</th><th>R 均值</th><th>R 中位</th></tr></thead>
            <tbody>
              {#each Object.entries(r.stats.by_pool) as [pool, rules]}
                {#each Object.entries(rules as Record<string, { triggers: number; plans: number; expired: number; filled: number; r_mean: number | null; r_median: number | null }>) as [ruleId, row]}
                  <tr><td>{pool === 'core' ? '核心池' : '扩展池'}</td><td>{wb.ruleLabel(ruleId)}</td>
                      <td>{row.triggers}</td><td>{row.plans}</td><td>{row.expired}</td><td>{row.filled}</td>
                      <td>{row.r_mean ?? '—'}</td><td>{row.r_median ?? '—'}</td></tr>
                {/each}
              {/each}
            </tbody>
          </table>
        {/if}
        {#if r.stats.execution?.length}
          <p class="text-xs text-muted">执行偏差</p>
          <ul>{#each r.stats.execution as x}<li>{x.ticker} 成交价较 T+1 开盘 {wb.pct(x.slippage)} · 决定后 {Number(x.delay_hours).toFixed(1)} 小时成交</li>{/each}</ul>
        {/if}
        {#if r.stats.unsignaled_trades?.length}<p>无信号交易 {r.stats.unsignaled_trades.length} 笔</p>{/if}
        {#if r.stats.plans && Object.keys(r.stats.plans).length}
          <p class="text-xs text-muted">计划影子（数量 / 已过期 / R 均值 / 中位数）</p>
          <ul>{#each Object.entries(r.stats.plans as Record<string, { count: number; expired: number; r_mean: number | null; r_median: number | null }>) as [kind, p]}
            <li>{wb.planKindText(kind, r.calc_version)}：{p.count} · 已过期 {p.expired} · R {p.r_mean ?? '—'} / {p.r_median ?? '—'}</li>
          {/each}</ul>
        {/if}
        {#if r.stats.tracks}
          <p class="text-xs text-muted">轨道对比（单元 / 已定 / 均值 / 中位 / 合计）</p>
          <ul>
            {#each [['规则', r.stats.tracks.summary.all.rule], ['Agent', r.stats.tracks.summary.all.agent], ['实际', r.stats.tracks.summary.all.actual]] as [track, s]}
              <li>{track}：{s.units} 单元 · 已定 {s.determined} · 均值 {wb.rText(s.mean)} · 中位 {wb.rText(s.median)} · 合计 {wb.rText(s.sum)}</li>
            {/each}
          </ul>
        {:else}
          <p class="text-xs text-muted">轨道对比：该快照无轨道对比</p>
        {/if}
        {#if r.stats.discipline}
          {@const d = r.stats.discipline}
          <p class="text-xs text-muted">纪律</p>
          <p>计划内买入 {d.planned_buys ?? 0} · 遵守率 {d.compliance_rate == null ? '—' : `${Math.round(d.compliance_rate * 100)}%`}</p>
          <p class="text-xs text-muted">追高 {d.counts?.chase ?? 0} · 过早止盈 {d.counts?.early_take ?? 0} · 死扛亏损 {d.counts?.held_loser ?? 0} · 计划外 {d.counts?.unplanned ?? 0}</p>
        {/if}
        {#if r.stats.learning}
          {@const L = r.stats.learning as WeeklyLearning}
          <section aria-label="你学到了什么" class="space-y-1 border-t border-border pt-2">
            <h3 class="font-semibold">你学到了什么 <span class="text-xs font-normal"><ConceptTerm id={ATTACH.weeklyLearning.learning}>说明</ConceptTerm></span></h3>
            {#if L.discipline.cards === 0 && L.cards.length === 0 && L.knowledge.length === 0}
              <p>本周没有结束的交易，也没有被检验的知识</p>
            {:else}
              <p>纪律（本周结束的 {L.discipline.cards} 笔）：追高 {L.discipline.chase} · 过早止盈 {L.discipline.early_take} · 死扛亏损 {L.discipline.held_loser} · 计划外 {L.discipline.unplanned} · 待定 {L.discipline.pending}</p>
              <p>复盘卡 {L.counts.total} 张（已审定 {L.counts.reviewed} · 待审定 {L.counts.to_review}）</p>
              <ul class="text-xs space-y-0.5">
                {#each L.cards as c (c.card_id)}
                  <li><a class="text-accent underline" href={`#review/cards/${c.card_id}`}>{c.ticker} {c.end_text}</a>
                    · 实际 {actualRText(c)} · {c.decision_text}{c.headline ? ` · ${c.headline}` : ''}</li>
                {/each}
              </ul>
              <p>被检验的知识 {L.knowledge.length} 条</p>
              <ul class="text-xs space-y-0.5">
                {#each L.knowledge as k (k.ref)}
                  <li><a class="text-accent underline" href={knowHref(k.ref)}>{k.ref}</a> {k.title}
                    · 样本 {k.sample.count}（{k.sample.r_mean === null ? '少于 5 个不给均值' : `均值 ${wb.rText(k.sample.r_mean)}`}）</li>
                {/each}
              </ul>
            {/if}
          </section>
        {:else}
          <p class="text-xs text-muted">该快照没有『你学到了什么』（review-6 及更早）</p>
        {/if}
      </article>
    {:else}<p class="text-sm text-muted">尚无周度复盘</p>{/each}
  {/if}

  {#if tab === 'monthly' && !error}
    <form class="flex flex-wrap items-end gap-2 text-sm border border-border rounded p-3" onsubmit={generateMonthly}>
      <label class="flex flex-col">月份（当月 1 日）<input aria-label="月份（当月 1 日）" type="date" class="border border-border rounded px-2 py-1 bg-bg" bind:value={monthFormState.month} /></label>
      <label class="flex flex-col flex-1">复盘笔记<textarea aria-label="月度复盘笔记" rows="2" class="border border-border rounded px-2 py-1 bg-bg" bind:value={monthFormState.notes}></textarea></label>
      <button type="submit" class="px-3 py-1 rounded bg-accent text-white">生成月度复盘</button>
      {#if monthError}<span class="text-xs text-red-600">{monthError}</span>{/if}
    </form>
    {#each monthly ?? [] as r (r.id)}
      <article class="border border-border rounded p-3 text-sm space-y-2">
        <h2 class="font-semibold">{r.month} · {(r.stats.tier && wb.TIER_LABELS[r.stats.tier]) || '缺数据'}
          <button class="ml-2 px-2 py-0.5 rounded bg-accent text-white text-xs" onclick={() => push('monthly', r.month)}>推送到 Discord</button>
          {#if pushResults['monthly:' + r.month]}<span class="text-xs text-muted">{pushResults['monthly:' + r.month]}</span>
          {:else if lastPushText('monthly', r.month)}<span class="text-xs text-muted">{lastPushText('monthly', r.month)}</span>{/if}
        </h2>
        {#if r.stats.return?.status === 'ok'}
          <p>月度收益 {wb.pct(r.stats.return.return)} · 净出入金 {r.stats.return.net_flow ?? '—'}</p>
          {#if r.stats.spy}<p>SPY {wb.pct(r.stats.spy.return)} · 超额 {wb.pct(r.stats.spy.excess)}</p>{/if}
        {:else}
          <p class="text-amber-700">缺资金快照，无法计算</p>
        {/if}
        {#if r.stats.review_flag === 'review'}<p class="text-red-600">流程复查：连续 3 个月亏损且跑输 SPY</p>
        {:else if r.stats.review_flag === 'insufficient'}<p class="text-xs text-muted">流程复查：样本不足（不足 3 个月）</p>{/if}
        {#if r.stats.review}
          {@const rv = r.stats.review}
          <p class="text-xs text-muted">复查明细</p>
          <ul class="text-xs">
            {#each rv.months ?? [] as m}
              <li>{String(m.month).slice(0, 7)}：本月 {wb.pct(m.return)} · SPY {wb.pct(m.spy_return)}</li>
            {/each}
          </ul>
          <p class="text-xs">3 个月复合 {wb.pct(rv.compound)} · SPY {wb.pct(rv.spy_compound)}</p>
        {/if}
        {#if r.stats.sensitivity?.rows?.length}
          <p class="text-xs text-muted">敏感性（近似）</p>
          <ul class="text-xs">{#each r.stats.sensitivity.rows as row}
            <li>风险 {wb.pct(row.risk_pct)}：收益 ≈ {wb.pct(row.return)} · 最大回撤 ≈ {wb.pct(row.max_drawdown)}</li>
          {/each}</ul>
        {/if}
        {#if r.stats.plans && Object.keys(r.stats.plans).length}
          <p class="text-xs text-muted">计划影子</p>
          <ul>{#each Object.entries(r.stats.plans) as [kind, p]}
            <li>{wb.planKindText(kind, r.calc_version)}：{p.count} · 已过期 {p.expired} · R {p.r_mean ?? '—'} / {p.r_median ?? '—'}</li>
          {/each}</ul>
        {/if}
        {#if r.stats.discipline}
          <p class="text-xs text-muted">纪律 · 遵守率 {r.stats.discipline.compliance_rate == null ? '—' : `${Math.round(r.stats.discipline.compliance_rate * 100)}%`}</p>
          <p class="text-xs text-muted">追高 {r.stats.discipline.counts?.chase ?? 0} · 过早止盈 {r.stats.discipline.counts?.early_take ?? 0} · 死扛亏损 {r.stats.discipline.counts?.held_loser ?? 0} · 计划外 {r.stats.discipline.counts?.unplanned ?? 0}</p>
        {/if}
        {#if r.notes}<p>{r.notes}</p>{/if}
        <p class="text-xs text-muted">口径 {r.calc_version} · 生成于 {wb.dateTime(r.created_at)}{r.supersedes_id ? ' · 更正版' : ''}</p>
      </article>
    {:else}<p class="text-sm text-muted">尚无月度复盘</p>{/each}
  {/if}

  {#if tab === 'account' && !error}
    {#if account}
      <div class="text-sm border border-border rounded p-3">
        <h2 class="font-semibold text-sm">风险参数（只读，改配置文件）</h2>
        <p class="text-xs text-muted">单笔风险 {wb.pct(account.params.risk_pct)} · 单票上限 {Math.round(account.params.single_cap * 100)}% · 总持仓上限 {Math.round(account.params.total_cap * 100)}%</p>
      </div>
      {#if accountError}<p class="text-xs text-red-600">{accountError}</p>{/if}
      <div class="grid md:grid-cols-2 gap-3">
        <form class="space-y-2 text-sm border border-border rounded p-3" onsubmit={recordSnapshot}>
          <h2 class="font-semibold text-sm">录入资金快照</h2>
          <label class="flex flex-col">资金日期<input aria-label="资金日期" type="date" class="border border-border rounded px-2 py-1 bg-bg" bind:value={snap.as_of} /></label>
          <label class="flex flex-col">总资金<input aria-label="总资金" inputmode="decimal" class="border border-border rounded px-2 py-1 bg-bg" bind:value={snap.equity} /></label>
          <label class="flex flex-col">备注<input aria-label="快照备注" class="border border-border rounded px-2 py-1 bg-bg" bind:value={snap.note} /></label>
          <button type="submit" class="px-3 py-1 rounded bg-accent text-white" disabled={!snap.as_of || !snap.equity}>录入资金快照</button>
        </form>
        <form class="space-y-2 text-sm border border-border rounded p-3" onsubmit={recordFlow}>
          <h2 class="font-semibold text-sm">录入出入金</h2>
          <label class="flex flex-col">出入金日期<input aria-label="出入金日期" type="date" class="border border-border rounded px-2 py-1 bg-bg" bind:value={flow.flow_date} /></label>
          <label class="flex flex-col">金额（入金为正）<input aria-label="金额" inputmode="decimal" class="border border-border rounded px-2 py-1 bg-bg" bind:value={flow.amount} /></label>
          <label class="flex flex-col">备注<input aria-label="出入金备注" class="border border-border rounded px-2 py-1 bg-bg" bind:value={flow.note} /></label>
          <button type="submit" class="px-3 py-1 rounded bg-accent text-white" disabled={!flow.flow_date || !flow.amount}>录入出入金</button>
        </form>
      </div>
      <h2 class="font-semibold text-sm">资金快照</h2>
      <ul class="text-sm space-y-1">
        {#each account.snapshots as s (s.id)}
          <li>{s.as_of} · {s.equity}{s.note ? `（${s.note}）` : ''}{s.supersedes_id ? ' · 更正版' : ''} · 录入于 {wb.dateTime(s.recorded_at)}</li>
        {:else}<li class="text-muted">暂无快照</li>{/each}
      </ul>
      <h2 class="font-semibold text-sm">出入金</h2>
      <ul class="text-sm space-y-1">
        {#each account.flows as f (f.id)}
          <li class={f.voided_at ? 'line-through text-muted' : ''}>
            {f.flow_date} · {f.amount > 0 ? '入金' : '出金'} {Math.abs(f.amount)}{f.note ? `（${f.note}）` : ''}
            {#if f.voided_at}<span>（已作废：{f.void_reason}）</span>
            {:else if voidingFlow === f.id}
              <input aria-label="作废理由" class="border border-border rounded px-1 text-xs bg-bg" bind:value={flowVoidReason} />
              <button class="text-xs text-red-600 disabled:opacity-50" disabled={!flowVoidReason.trim()} onclick={() => voidAFlow(f.id)}>确认作废</button>
              <button class="text-xs" onclick={() => { voidingFlow = null; flowVoidReason = '' }}>取消</button>
            {:else}
              <button class="text-xs text-muted hover:text-red-600" onclick={() => { voidingFlow = f.id; flowVoidReason = '' }}>作废</button>
            {/if}
          </li>
        {:else}<li class="text-muted">暂无出入金</li>{/each}
      </ul>
    {/if}
  {/if}

  {#if tab === 'backchecks' && !error}
    <section class="space-y-2">
      <h2 class="font-semibold text-sm">上线前检查 · 历史回放</h2>
      <p class="text-xs text-muted">新规则上线前手动运行，回答「触发是否过频、止损是否总被扫掉」。只读已存 K 线与 SEC 文件，不联网、不补采。也可用命令行：python -m investment_assistant.workbench.backcheck。</p>
      <div class="flex items-center gap-2">
        <button class="text-sm px-3 py-1 rounded bg-accent text-white" onclick={runBackcheckNow}>运行历史检查</button>
        {#if backcheckError}<span class="text-xs text-red-600">{backcheckError}</span>{/if}
      </div>
      {#if backcheckNote}<p class="text-xs text-muted">{backcheckNote}</p>{/if}
      {#if backchecks?.length}
        <div class="table-scroll"><table class="text-sm">
          <thead><tr><th>时间</th><th>版本</th><th>标的</th><th>触发</th><th>成交</th><th>超额 5 日</th><th>超额 10 日</th><th>超额 20 日</th><th>标记</th></tr></thead>
          <tbody>
            {#each backchecks as b (b.id)}
              <tr>
                <td>{wb.dateTime(b.created_at)}</td>
                <td>{b.calc_version}</td>
                <td>{(b.params?.tickers as string[] | undefined)?.join('、') ?? '当前观察池'}</td>
                <td>{b.stats?.all?.triggers ?? 0}</td>
                <td>{b.stats?.all?.filled ?? 0}</td>
                {#each (['5', '10', '20'] as const) as h}
                  {@const excess = b.stats?.all?.excess?.[h]}
                  <td>{excess
                    ? `n=${excess.n} · 均 ${fmtPct(excess.mean)} · 中 ${fmtPct(excess.median)} · 正 ${fmtPct(excess.positive_share)}`
                    : '—'}</td>
                {/each}
                <td>{(b.stats?.all?.flags ?? []).join('、') || '无'}</td>
              </tr>
            {/each}
          </tbody>
        </table></div>
        {#each backchecks as b (b.id)}
          <small class="block text-xs text-muted">{b.stats?.note}</small>
        {/each}
      {:else if backchecks}
        <p class="text-sm text-muted">尚无历史检查记录</p>
      {/if}
    </section>
  {/if}

  <Drawer open={callDrawer.open} onclose={() => callDrawer = { open: false, calls: [], call: null }}>
    {#if callDrawer.calls.length}
      <p class="text-xs mb-2">{#each callDrawer.calls as tc}<button class="text-accent underline mr-2" onclick={() => callDrawer = { ...callDrawer, call: tc }}>call:{tc.seq}</button>{/each}</p>
    {/if}
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
</section>
