<script lang="ts">
  import { onMount } from 'svelte'
  import { registerNavigationGuard } from '../lib/navigation-guard'
  import * as wb from '../lib/workbench'

  type Basis = 'rule' | 'own'
  type Draft = { choice: wb.Choice; reason: string; requestId: string; error: string; busy: boolean
                 basis: Basis; own: { entry_low: string; entry_high: string; stop: string; target1: string }
                 ownRequestId: string }

  let view = $state<wb.TodayView | null>(null)
  let error = $state('')
  let loading = $state(true)
  let notice = $state('')
  let drafts = $state<Record<string, Draft>>({})
  let generation = 0

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
                                basis: u.plan != null && u.plan.status !== 'ok' ? 'own' : 'rule',
                                own: { entry_low: '', entry_high: '', stop: '', target1: '' },
                                ownRequestId: wb.newRequestId() }
      }
      view = next
      error = ''
    } catch (e) {
      if (token === generation) { error = wb.describeError(e); view = null }
    } finally {
      if (token === generation) loading = false
    }
  }

  const basisLocked = (u: wb.Unit) => u.plan != null && u.plan.status !== 'ok'   // 规则计划作废时只能自定
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
      await wb.postDecision(wb.decisionPayload(u, draft.choice, draft.reason, draft.requestId, own))
      delete drafts[key]
      await load()
    } catch (e) {
      draft.error = wb.describeError(e)
    } finally {
      if (drafts[key]) drafts[key].busy = false
    }
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

  const regimeText = (label?: string | null) => label ? (wb.REGIME_LABELS[label] ?? label) : '未知'
  const sectorText = (ctx: wb.PlanContext | undefined) => ctx?.sector
    ? `${ctx.sector.etf} ${ctx.sector.state ? (wb.SECTOR_STATE_LABELS[ctx.sector.state] ?? '数据不足') : '数据不足'}`
    : '未映射'
  const pctText = (value: number | null | undefined) =>
    value == null ? '—' : `${(value * 100).toFixed(1)}%`
  const fredText = (m: wb.MarketContext) =>
    Object.values(m.macro ?? {}).every(v => v == null)
      ? 'FRED 未配置'
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
    <div class="flex gap-2">
      <button class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2" onclick={runNow}>立即运行批处理</button>
      <button class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2" onclick={repush}>重新推送今日计划</button>
    </div>
  </header>
  {#if notice}<p class="text-xs text-muted">{notice}</p>{/if}

  {#if view}
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
        {#each u.labels as label}<span class="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">{wb.UNIT_LABELS[label] ?? label}</span>{/each}
        {#if u.entry_passed}<span class="text-xs text-amber-700">已过入场时点（T+1 开盘）</span>{/if}
        {#if u.market_status}<span class="text-xs text-muted">大盘 {u.market_status}（仅背景）</span>{/if}
        {#if u.position}<span class="text-xs text-muted">持仓 {u.position.quantity} · 成本 {Number(u.position.avg_cost).toFixed(2)}</span>{/if}
      </div>

      <ul class="text-sm space-y-1">
        {#each u.candidates as c (c.id)}
          <li><span class="font-medium">{wb.ruleLabel(c.rule_id)}</span> → {wb.ACTION_LABELS[c.action]} <span class="text-xs text-muted">{values(c)}</span></li>
        {/each}
      </ul>

      <div class="text-sm border-l-2 border-border pl-2 space-y-1">
        {#if !u.brief}
          <p class="text-muted">尚无解读</p>
        {:else if u.brief.status === 'error'}
          <p class="text-red-600">解读无效，已隐藏：{u.brief.error}</p>
        {:else}
          {#if u.brief.status === 'fallback'}<p class="text-xs text-muted">规则版解读（LLM 未参与：{u.brief.error}）</p>{/if}
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

      {#if u.plan}
        {@const p = u.plan}
        <div class="text-sm border-l-2 border-accent/40 pl-2 space-y-1">
          <p class="font-medium">计划（{p.kind === 'rule' ? '规则' : '自定'} · {p.plan_version}{p.status === 'invalid' ? ' · 已作废' : ''}）</p>
          <p>入场区间 {p.entry_low}–{p.entry_high} · 止损 {p.stop} · T1 {p.target1} · 有效期至 {p.valid_until}</p>
          <p class="text-xs text-muted">区制 {regimeText(p.inputs?.context?.regime?.label)} · 下次财报 {p.inputs?.context?.next_earnings ?? '未知'} · 行业 {sectorText(p.inputs?.context)}</p>
          {#if p.sizing?.status === 'no_equity'}
            <p class="text-amber-700">缺资金快照，无法计算建议股数</p>
          {:else if p.sizing?.shares != null}
            <p>建议 {p.sizing.shares} 股 · 风险 {p.sizing.risk_amount}（资金日 {p.sizing.snapshot_as_of}）</p>
          {/if}
          {#each p.invalid_reasons as r}<p class="text-red-600">作废：{r}</p>{/each}
          {#each p.warnings as w}<p class="text-xs text-muted">提示：{w}</p>{/each}
          <p class="text-xs text-muted">证据：未验证</p>
        </div>
      {/if}

      {#if draft}
        <form class="space-y-2" onsubmit={e => { e.preventDefault(); submit(u) }}>
          {#if draft.choice === 'accept' && u.proposed_action === 'buy' && u.plan}
            <fieldset class="flex gap-3 text-sm">
              <legend class="text-xs text-muted">执行依据</legend>
              <label class="flex items-center gap-1">
                <input type="radio" name={`basis-${keyOf(u)}`} value="rule" bind:group={draft.basis}
                       disabled={basisLocked(u)} />
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
          </div>
        </form>
      {/if}
    </article>
  {/each}

  {#if view?.extended_units?.length}
    <details class="border border-border rounded p-3 bg-surface text-sm">
      <summary class="cursor-pointer font-medium">扩展池（只影子跟踪）· {view.extended_units.length} 个单元</summary>
      <ul class="mt-2 space-y-1">
        {#each view.extended_units as u (`${u.ticker}|${u.signal_date}`)}
          <li>{u.ticker} · {u.signal_date} · 建议{wb.ACTION_LABELS[u.proposed_action]} · {u.rule_ids.map(wb.ruleLabel).join('、')}
            {#if u.plan}· 入场 {u.plan.entry_low}–{u.plan.entry_high} · 止损 {u.plan.stop} · T1 {u.plan.target1} · 有效期至 {u.plan.valid_until}{/if}
          </li>
        {/each}
      </ul>
    </details>
  {/if}

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
        </li>
      {/each}
    </ul>
  {/if}
</section>
