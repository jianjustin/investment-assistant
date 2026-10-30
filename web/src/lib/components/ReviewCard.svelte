<script lang="ts">
  import AgentReasoning from './AgentReasoning.svelte'
  import CardVerdictForm from './CardVerdictForm.svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import DiscussButton from './DiscussButton.svelte'
  import RefList from './RefList.svelte'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import { ATTACH } from '../knowledge'
  import {
    actualRText, CARD_STATUS_TEXT, DISCIPLINE_FLAGS, DISCIPLINE_TEXT, endText, growthError, knowHref, PENDING_TEXT, REDRAFT_PENDING_TEXT,
    REDRAFT_POLL_MS, ROLE_TEXT, truncate, VERSION_BASIS_TEXT_V2,
  } from '../growth'
  import type { CardDraftRow, FactDiscipline, FactHolding, FactTrack, ReviewCardView } from '../growth'
  import { AGENT_REASON_TEXT, EXIT_REASON_TEXT, KIND_TEXT, rText } from '../workbench'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import { DataTable } from '$lib/ui/data-table/index'
  import type { Column } from '$lib/ui/data-table/types'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import PageHeader from '$lib/ui/domain/PageHeader.svelte'
  import PlanLevels from '$lib/ui/domain/PlanLevels.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'

  // 复盘卡页（spec §4.7）：页头 → 预期 vs 实际（冻结事实表在前，Agent 叙述在后，引用可点开）→ 三条轨道 →
  // 你的执行与纪律（retro-2；retro-1 的旧卡原样显示「你的决定与纪律」）（检测时 / 现在）→ 教训草稿与审定 → 看起草过程；草稿作废 / 出错时显示原因与「重新起草」。
  // 数字都来自冻结的 facts；叙述与教训一律按纯文本显示。
  let { id }: { id: number } = $props()

  const D = ATTACH.retroCard
  let view = $state<ReviewCardView | null>(null)
  let error = $state('')
  let highlight = $state<string | null>(null)
  let reasoningOpen = $state(false)
  let redraft = $state<{ busy: boolean; text: string }>({ busy: false, text: '' })
  let root: HTMLElement | undefined
  let generation = 0

  async function load() {
    const token = ++generation
    try {
      const next = await api.getReviewCard(id)
      if (token !== generation) return
      view = next
      error = ''
    } catch (e) {
      if (token !== generation) return
      view = null
      error = growthError(e)
    }
  }
  $effect(() => {
    void id
    view = null
    reasoningOpen = false
    redraft = { busy: false, text: '' }
    void load()
  })

  const facts = $derived(view?.facts ?? null)
  const reviewed = $derived(view?.status === 'reviewed')
  const okDraft = $derived<CardDraftRow | null>(view?.drafts.find(d => d.status === 'ok') ?? null)
  const lastDraft = $derived<CardDraftRow | null>(view && view.drafts.length ? view.drafts[view.drafts.length - 1] : null)
  const failedLast = $derived(!!lastDraft && (lastDraft.status === 'rejected' || lastDraft.status === 'error'))
  const runId = $derived(okDraft?.agent_run_id ?? lastDraft?.agent_run_id ?? null)
  const narrative = $derived(okDraft?.output ?? null)
  const referencePlan = $derived(facts?.plans.find(p => p.roles.includes('reference')) ?? facts?.plans[0] ?? null)
  const planId = (key: string) => key.replace(/^plan:/, '')
  const canRedraft = $derived(!reviewed && !okDraft && (view?.status === 'draft_failed' || failedLast))
  const reasonText = (reason: string | null | undefined) => AGENT_REASON_TEXT[reason ?? ''] ?? reason ?? '未知原因'

  const SHADOW_TEXT: Record<string, string> = { pending: '待成交', expired: '到期未成交', open: '持仓中', closed: '已平仓', voided: '开盘作废' }
  const hl = (...keys: string[]) => (highlight && keys.includes(highlight) ? 'bg-warn/10' : '')

  function scrollToFact(key: string) {
    const el = root?.querySelector(`[data-fact~="${key}"]`)
    if (!el) return
    highlight = key
    ;(el as HTMLElement).scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }

  // 持仓：持有 n 个交易日 · 退出指令 <日期>（原因） · 实际卖出 <日期>（没有卖出写「尚未卖出」）
  const holdingText = (h: FactHolding) => {
    const parts = [h.held_sessions != null ? `持有 ${h.held_sessions} 个交易日` : '持有天数未知']
    if (h.exit?.session)
      parts.push(`退出指令 ${h.exit.session}${h.exit.reason ? `（${EXIT_REASON_TEXT[h.exit.reason] ?? h.exit.reason}）` : ''}`)
    if (h.sell_date) parts.push(`实际卖出 ${h.sell_date}`)
    else if (h.exit?.session) parts.push('尚未卖出')
    return `持仓：${parts.join(' · ')}`
  }

  const touched = (key: string) => {
    const t = facts?.bars_after.per_plan.find(p => p.key === key)
    const parts = [t?.entry_touched && `入场 ${t.entry_touched}`, t?.stop_touched_on && `止损 ${t.stop_touched_on}`,
                   t?.t1_touched_on && `T1 ${t.t1_touched_on}`].filter(Boolean)
    return parts.length ? parts.join(' · ') : '未触及'
  }
  const shadowText = (key: string) => {
    const s = facts?.shadow[key]
    return s ? `${SHADOW_TEXT[s.status] ?? s.status} ${rText(s.r)}` : null
  }
  const trackLine = (label: string, t: FactTrack) =>
    `${label} · ${t.status_text} ${rText(t.r)}`
  const actualLine = (t: FactTrack) =>
    t.r === null && bought ? `实际 · ${t.status_text} ${actualRText({ actual_r: null, filled: true })}` : trackLine('实际', t)

  // 纪律：每个标记在一次判定里是「成立 / 待定 / 未触发」
  function cell(d: FactDiscipline, flag: string): string {
    if (d.trades.some(t => t.flags.includes(flag))) return '成立'
    if (d.trades.some(t => t.immature.includes(flag))) return PENDING_TEXT[flag] ?? DISCIPLINE_TEXT.pending
    return '未触发'
  }
  const signature = (d: FactDiscipline) =>
    JSON.stringify(DISCIPLINE_FLAGS.map(f => cell(d, f)))
  const disciplineChanged = $derived(!!view && signature(view.facts.discipline) !== signature(view.discipline_now))
  // the backend's `filled` (any live buy) decides; an older payload without it falls back to the trade list
  const bought = $derived(view?.card.filled ?? (!!facts && facts.trades.trades.some(t => t.side === 'buy')))
  const FLAG_CONCEPT: Record<string, string> = {
    chase: D.chase, early_take: D.earlyTake, held_loser: D.heldLoser, unplanned: D.unplanned,
  }

  async function runRedraft() {
    if (redraft.busy) return
    redraft = { busy: true, text: '起草中…' }
    try {
      const started = await api.redraftCard(id)
      const done = await api.pollRun(started.run_id, { timeoutMs: REDRAFT_POLL_MS })
      redraft = { busy: false, text: done.status === 'done' ? '' : `起草失败：${done.error ?? '未知原因'}` }
      await load()
    } catch (e) {
      redraft = e instanceof Error && e.message === 'run timeout'
        ? { busy: true, text: REDRAFT_PENDING_TEXT }
        : { busy: false, text: growthError(e) }
    }
  }

  type PlanFact = ReviewCardView['facts']['plans'][number]
  const levelNum = (v: string | number | null | undefined) => (v == null ? null : Number(v))
  const planColumns: Column<PlanFact>[] = [
    { key: 'plan', header: '计划', cell: planCell },
    { key: 'roles', header: '角色', value: p => p.roles.map(r => ROLE_TEXT[r] ?? r).join('、') },
    { key: 'levels', header: '价位', cell: levelsCell },
    { key: 'valid', header: '有效期', value: p => `${p.valid_from} 至 ${p.valid_until}` },
    { key: 'shadow', header: '影子结果', cell: shadowCell },
    { key: 'touched', header: '首次触及', value: p => touched(p.key) },
  ]
  const disciplineColumns = $derived<Column<string>[]>([
    { key: 'flag', header: '', cell: flagCell },
    { key: 'then', header: '检测时', value: flag => view ? cell(view.facts.discipline, flag) : '' },
    ...(disciplineChanged ? [{ key: 'now', header: '现在', value: (flag: string) => view ? cell(view.discipline_now, flag) : '' }] : []),
  ])
</script>
{#snippet planCell(p: PlanFact)}
  <span data-fact="plans shadow" class={hl('plans', 'shadow')}>{KIND_TEXT[p.kind] ?? p.kind}{p.kind === 'agent' && p.version_no != null ? ` 第 ${p.version_no} 版` : ''}</span>
  {#if p.status === 'invalid'}<span class="text-destructive">（已作废）</span>{/if}
{/snippet}
{#snippet levelsCell(p: PlanFact)}<PlanLevels lead="" low={levelNum(p.levels.entry_low)} high={levelNum(p.levels.entry_high)} stop={levelNum(p.levels.stop)} target1={levelNum(p.levels.target1)} />{/snippet}
{#snippet shadowCell(p: PlanFact)}{@const text = shadowText(p.key)}{#if text}{text}{:else}<StatusPill domain="block" value="not_computed" />{/if}{/snippet}
{#snippet flagCell(flag: string)}<ConceptTerm id={FLAG_CONCEPT[flag]}>{DISCIPLINE_TEXT[flag]}</ConceptTerm>{/snippet}

<section bind:this={root} class="grid min-w-0 gap-4">
  <p><a class="text-xs text-primary underline" href="#review/cards">返回复盘卡列表</a></p>
  {#if error}
    <Alert variant="danger"><AlertDescription>复盘卡加载失败：<span>{error}</span></AlertDescription></Alert>
  {:else if !view || !facts}
    <DataBlock state="loading" skeleton="block" />
  {:else}
    <div data-testid="card-header" data-fact="subject" class="grid gap-1 {hl('subject')}">
      <PageHeader level={2} title={`${facts.subject.ticker} · ${endText(facts.subject.end_kind, facts.subject.exit_basis)} · ${view.card.end_session}`}>
        {#snippet meta()}
          <StatusPill domain="card" value={view!.status} />
          <span>结束类型 <ConceptTerm id={D.end}>{endText(facts!.subject.end_kind, facts!.subject.exit_basis)}</ConceptTerm></span>
          <a class="text-primary underline" href={`#instrument/${encodeURIComponent(facts!.subject.ticker)}`}>标的页</a>
          {#if referencePlan}<a class="text-primary underline" href={`#plan/${planId(referencePlan.key)}`}>参考计划</a>{/if}
          <DiscussButton context={{ kind: 'card', card_id: id }} />
          <ConceptTerm id={D.card}>复盘卡说明</ConceptTerm>
        {/snippet}
      </PageHeader>
      <p class="text-xs text-muted-foreground">证据：未验证 <ConceptTerm id={ATTACH.agentCard.evidence}>证据状态</ConceptTerm></p>
    </div>

    <section class="grid gap-2">
      <h3 class="text-sm font-medium">预期 vs 实际</h3>
      {#if facts.plans.length}
        <DataTable columns={planColumns} rows={facts.plans} rowKey={p => p.key} ariaLabel="预期与实际" sticky={false} />
      {:else}
        <DataBlock state="empty" message="没有相关计划" />
      {/if}
      <p data-fact="bars_after" class="text-xs {hl('bars_after')}">日线摘要：{#if facts.bars_after.first_day}{facts.bars_after.first_day} 至 {facts.bars_after.last_day}（{facts.bars_after.sessions} 个交易日）· 最高 {facts.bars_after.high}（{facts.bars_after.high_date}）· 最低 {facts.bars_after.low}（{facts.bars_after.low_date}）· 结束收盘 {facts.bars_after.close_end}{:else}没有日线{/if}</p>
      {#if facts.reviews}
        <p data-fact="reviews" class="text-xs {hl('reviews')}">复查摘要：共 {facts.reviews.count} 次{#if facts.reviews.invalidated}；已作废（{facts.reviews.invalidated.session}{facts.reviews.invalidated.reason ? `：${facts.reviews.invalidated.reason}` : ''}）{/if}</p>
      {/if}
      <p data-fact="knowledge" class="text-xs {hl('knowledge')}">计划当时引用过的知识：{#each facts.knowledge as k, i (k.ref)}{#if i}、{/if}<a class="text-primary underline" href={knowHref(k.ref)}>{k.ref}</a> {k.title_at_version}{:else}没有{/each}</p>

      <section aria-label="复盘叙述" class="grid gap-1 border-l-2 border-info/50 pl-2 text-sm">
        {#if narrative}
          <p class="font-medium whitespace-pre-wrap">{narrative.headline}</p>
          <ol class="ml-5 grid list-decimal gap-1">
            {#each narrative.expected_vs_actual as line, i (i)}
              <li><span class="whitespace-pre-wrap">{line.text}</span><RefList refs={line.refs} runId={okDraft?.agent_run_id} onFact={scrollToFact} /></li>
            {/each}
          </ol>
          {#if narrative.execution_review}
            <p><span class="text-xs text-muted-foreground">执行回顾</span> <span class="whitespace-pre-wrap">{narrative.execution_review.text}</span><RefList refs={narrative.execution_review.refs} runId={okDraft?.agent_run_id} onFact={scrollToFact} /></p>
          {:else if narrative.decision_review}
            <p><span class="text-xs text-muted-foreground">{facts.execution ? '执行回顾' : '决定回顾'}</span> <span class="whitespace-pre-wrap">{narrative.decision_review.text}</span><RefList refs={narrative.decision_review.refs} runId={okDraft?.agent_run_id} onFact={scrollToFact} /></p>
          {/if}
        {:else}
          <p class="text-xs text-muted-foreground">还没有叙述草稿。</p>
        {/if}
      </section>
    </section>

    <section aria-label="三条轨道" data-fact="tracks" class="grid gap-1 {hl('tracks')}">
      <h3 class="text-sm font-medium">三条轨道 <span class="text-xs font-normal"><ConceptTerm id={D.tracks}>说明</ConceptTerm></span></h3>
      <ul class="grid gap-0.5 text-sm">
        {#if facts.tracks.rule}
          <li>{trackLine('规则', facts.tracks.rule)}{#if facts.tracks.rule.plan_id} · <a class="text-primary underline" href={`#plan/${facts.tracks.rule.plan_id}`}>看计划</a>{/if}</li>
        {/if}
        {#if facts.tracks.agent}
          <li>{trackLine(`Agent${facts.tracks.agent.version_no != null ? ` 第 ${facts.tracks.agent.version_no} 版` : ''}`, facts.tracks.agent)}{#if facts.tracks.agent.version_basis}（{VERSION_BASIS_TEXT_V2[facts.tracks.agent.version_basis] ?? facts.tracks.agent.version_basis}）{/if}{#if facts.tracks.agent.plan_id} · <a class="text-primary underline" href={`#plan/${facts.tracks.agent.plan_id}`}>看计划</a>{/if}</li>
        {/if}
        <li>{actualLine(facts.tracks.actual)}{#if facts.tracks.actual.plan_kind} · 照{KIND_TEXT[facts.tracks.actual.plan_kind] ?? facts.tracks.actual.plan_kind}计划{/if}</li>
      </ul>
    </section>

    <section aria-label={facts.execution ? '你的执行与纪律' : '你的决定与纪律'} class="grid gap-2 text-sm">
      {#if facts.execution}
        {@const ex = facts.execution}
        <h3 class="font-medium">你的执行与纪律 <span class="text-xs font-normal"><ConceptTerm id={ATTACH.today.basis}>执行状态说明</ConceptTerm></span></h3>
        <p data-fact="execution" class={hl('execution')}>执行：{ex.text}
          {#if ex.plan_id} · <a class="text-primary underline" href={`#plan/${ex.plan_id}`}>看计划</a>{/if}
          {#each ex.notes ?? [] as n (n.id)}<span class="block text-xs text-muted-foreground whitespace-pre-wrap">备注（{fmtBeijing(n.created_at)}）：{n.body}</span>{/each}
          {#if ex.legacy_decision}<span class="block text-xs text-muted-foreground whitespace-pre-wrap">旧决定：{ex.legacy_decision.text}{ex.legacy_decision.reason ? `（理由：${ex.legacy_decision.reason}）` : ''}</span>{/if}</p>
        {#if facts.holding}
          {@const h = facts.holding}
          <p data-fact="holding" class="text-xs {hl('holding')}">{holdingText(h)}</p>
        {/if}
      {:else if facts.decision}
        <h3 class="font-medium">你的决定与纪律</h3>
        <p data-fact="decision" class={hl('decision')}>决定：{facts.decision.text}{#if facts.decision.reason}<span class="block text-xs text-muted-foreground whitespace-pre-wrap">理由：{facts.decision.reason}</span>{/if}</p>
      {/if}
      <ul data-fact="trades" class="grid gap-0.5 text-xs {hl('trades')}">
        {#each facts.trades.trades as t (t.id)}
          <li>{t.side === 'buy' ? '买入' : '卖出'} {t.quantity} @ {t.price}（费 {t.fee}）· {fmtBeijing(t.executed_at)}</li>
        {:else}
          <li class="text-muted-foreground">没有成交</li>
        {/each}
      </ul>
      <div data-fact="discipline" class="grid gap-1 {hl('discipline')}">
        {#if !bought}
          <p>未成交，纪律四项不适用</p>
        {:else}
          <DataTable columns={disciplineColumns} rows={[...DISCIPLINE_FLAGS]} rowKey={flag => flag} ariaLabel="纪律判定" sticky={false} />
          <p class="text-xs text-muted-foreground">
            {#if disciplineChanged}检测时 = {view.facts.discipline.as_of} 的判定（冻结）；现在 = {view.discipline_now.as_of} 的只读重算，不改卡。
            {:else}判定于 {view.facts.discipline.as_of}（冻结）。{/if}
          </p>
        {/if}
      </div>
    </section>

    {#if !okDraft && !reviewed}
      <section aria-label="起草状态" class="grid gap-1 rounded-md border border-border p-3 text-sm">
        {#if canRedraft}
          <p>{CARD_STATUS_TEXT.draft_failed}</p>
          {#if lastDraft}<p class="text-xs text-muted-foreground">最近一次（第 {lastDraft.attempt} 次）：{reasonText(lastDraft.reason)}</p>{/if}
          <div class="flex flex-wrap items-center gap-2">
            <Button size="sm" busy={redraft.busy} onclick={runRedraft}>重新起草</Button>
            {#if redraft.text && redraft.busy}
              <StatusPill domain="node" value="running" text={redraft.text} />
            {:else if redraft.text}
              <Alert variant="danger" class="w-auto py-1"><AlertDescription class="text-xs">{redraft.text}</AlertDescription></Alert>
            {/if}
          </div>
        {:else}
          <p class="text-xs text-muted-foreground">这张卡还在起草，稍后刷新查看；现在也可以直接审定。</p>
        {/if}
      </section>
    {/if}

    <section aria-label="教训草稿与审定" class="grid gap-2">
      <h3 class="text-sm font-medium">教训草稿与审定</h3>
      <CardVerdictForm cardId={id} drafts={view.lesson_drafts} verdict={view.verdict} {runId} onFact={scrollToFact} onSubmitted={() => load()} />
    </section>

    {#if runId}
      <div class="grid gap-1">
        <div><Button variant="link" size="sm" class="text-xs" aria-expanded={reasoningOpen}
                onclick={() => reasoningOpen = !reasoningOpen}>看起草过程</Button></div>
        {#if reasoningOpen}<AgentReasoning {runId} />{/if}
      </div>
    {/if}

    <section aria-label="讨论" class="grid gap-1 text-sm">
      <h3 class="font-medium">讨论</h3>
      <ul class="grid gap-0.5 text-xs">
        {#each view.discussions as d (d.id)}
          <li><a class="text-primary underline" href={`#discuss/${d.id}`}>{fmtBeijing(d.created_at)} · {d.turn_count} 轮{d.first_question ? ` · ${truncate(d.first_question, 40)}` : ''}</a></li>
        {:else}
          <li class="text-muted-foreground">还没有讨论</li>
        {/each}
      </ul>
    </section>
  {/if}
</section>
