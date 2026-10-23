<script lang="ts">
  import { onMount } from 'svelte'
  import * as wb from '../lib/workbench'

  let { sub }: { sub?: string } = $props()
  const TABS = [['trades', '交易与持仓'], ['shadow', '对照组'], ['weekly', '周度复盘']] as const
  let tab = $derived(TABS.some(([id]) => id === sub) ? sub! : 'trades')

  let error = $state('')
  let trades = $state<wb.Trade[]>([])
  let tradeReview = $state<wb.TradeReview | null>(null)
  let shadow = $state<wb.ShadowView | null>(null)
  let weekly = $state<wb.WeeklyReview[] | null>(null)

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
      } else {
        weekly = (await wb.getWeekly()).reviews
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

  const windowText = (w: wb.Window | undefined) =>
    !w || w.status === 'immature' ? '未成熟' : w.excess !== undefined ? wb.pct(w.excess) : `走势 ${wb.pct(w.move)}`

  onMount(() => () => { voiding = null })
</script>

<section class="space-y-4">
  <header class="flex items-center gap-4">
    <h1 class="text-lg font-semibold">复盘</h1>
    <nav class="flex gap-2 text-sm">
      {#each TABS as [id, label]}
        <a href={`#review/${id}`} class="px-2 py-1 rounded {tab === id ? 'bg-accent/10 text-accent' : 'text-muted hover:text-ink'}">{label}</a>
      {/each}
    </nav>
  </header>
  <p class="text-xs text-muted">描述性统计：股票少、样本重叠，不代表任何规则有效。</p>

  {#if error}<p role="alert" class="text-sm text-red-600">{error}</p>{/if}

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

  {#if tab === 'weekly' && weekly && !error}
    <form class="flex flex-wrap items-end gap-2 text-sm border border-border rounded p-3" onsubmit={generateWeekly}>
      <label class="flex flex-col">周一<input aria-label="周一" type="date" class="border border-border rounded px-2 py-1 bg-bg" bind:value={weekStart} /></label>
      <label class="flex flex-col flex-1">复盘笔记<textarea aria-label="复盘笔记" rows="2" class="border border-border rounded px-2 py-1 bg-bg" bind:value={weekNotes}></textarea></label>
      <button type="submit" class="px-3 py-1 rounded bg-accent text-white">生成复盘</button>
      {#if weekError}<span class="text-xs text-red-600">{weekError}</span>{/if}
    </form>
    {#each weekly as r (r.id)}
      <article class="border border-border rounded p-3 text-sm space-y-2">
        <h2 class="font-semibold">{r.stats.week?.start ?? r.week_start} 周 · 已决定 {r.stats.units?.decided ?? 0} · 未处理 {r.stats.units?.undecided ?? 0}</h2>
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
        {#if r.stats.execution?.length}
          <p class="text-xs text-muted">执行偏差</p>
          <ul>{#each r.stats.execution as x}<li>{x.ticker} 成交价较 T+1 开盘 {wb.pct(x.slippage)} · 决定后 {Number(x.delay_hours).toFixed(1)} 小时成交</li>{/each}</ul>
        {/if}
        {#if r.stats.unsignaled_trades?.length}<p>无信号交易 {r.stats.unsignaled_trades.length} 笔</p>{/if}
      </article>
    {:else}<p class="text-sm text-muted">尚无周度复盘</p>{/each}
  {/if}
</section>
