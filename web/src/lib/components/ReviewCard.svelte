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
    CARD_STATUS_TEXT, DISCIPLINE_FLAGS, DISCIPLINE_TEXT, endText, growthError, knowHref, PENDING_TEXT, REDRAFT_PENDING_TEXT,
    REDRAFT_POLL_MS, ROLE_TEXT, truncate, VERSION_BASIS_TEXT,
  } from '../growth'
  import type { CardDraftRow, FactDiscipline, FactTrack, ReviewCardView } from '../growth'
  import { AGENT_REASON_TEXT, KIND_TEXT, rText } from '../workbench'

  // 复盘卡页（spec §4.7）：页头 → 预期 vs 实际（冻结事实表在前，Agent 叙述在后，引用可点开）→ 三条轨道 →
  // 你的决定与纪律（检测时 / 现在）→ 教训草稿与审定 → 看起草过程；草稿作废 / 出错时显示原因与「重新起草」。
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

  const SHADOW_TEXT: Record<string, string> = { pending: '待成交', expired: '到期未成交', open: '持仓中', closed: '已平仓' }
  const hl = (...keys: string[]) => (highlight && keys.includes(highlight) ? 'bg-amber-100' : '')

  function scrollToFact(key: string) {
    const el = root?.querySelector(`[data-fact~="${key}"]`)
    if (!el) return
    highlight = key
    ;(el as HTMLElement).scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }

  const touched = (key: string) => {
    const t = facts?.bars_after.per_plan.find(p => p.key === key)
    const parts = [t?.entry_touched && `入场 ${t.entry_touched}`, t?.stop_touched_on && `止损 ${t.stop_touched_on}`,
                   t?.t1_touched_on && `T1 ${t.t1_touched_on}`].filter(Boolean)
    return parts.length ? parts.join(' · ') : '—'
  }
  const shadowText = (key: string) => {
    const s = facts?.shadow[key]
    return s ? `${SHADOW_TEXT[s.status] ?? s.status} ${rText(s.r)}` : '—'
  }
  const trackLine = (label: string, t: FactTrack) =>
    `${label} · ${t.status_text} ${rText(t.r)}`

  // 纪律：每个标记在一次判定里是「成立 / 待定 / 未触发」
  function cell(d: FactDiscipline, flag: string): string {
    if (d.trades.some(t => t.flags.includes(flag))) return '成立'
    if (d.trades.some(t => t.immature.includes(flag))) return PENDING_TEXT[flag] ?? DISCIPLINE_TEXT.pending
    return '未触发'
  }
  const signature = (d: FactDiscipline) =>
    JSON.stringify(DISCIPLINE_FLAGS.map(f => cell(d, f)))
  const disciplineChanged = $derived(!!view && signature(view.facts.discipline) !== signature(view.discipline_now))
  const bought = $derived(!!facts && facts.trades.trades.some(t => t.side === 'buy'))
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
</script>

<section bind:this={root} class="space-y-4 min-w-0">
  <p><a class="text-xs text-accent underline" href="#review/cards">返回复盘卡列表</a></p>
  {#if error}
    <p role="alert" class="text-sm text-red-600">复盘卡加载失败：<span>{error}</span></p>
  {:else if !view || !facts}
    <p class="text-sm text-muted">加载中…</p>
  {:else}
    <header data-testid="card-header" data-fact="subject" class="space-y-1 {hl('subject')}">
      <h2 class="text-lg font-semibold">{facts.subject.ticker} · {endText(facts.subject.end_kind, facts.subject.exit_basis)}
        · {view.card.end_session}</h2>
      <p class="text-xs text-muted flex flex-wrap items-center gap-x-3 gap-y-1">
        <span class="px-1.5 py-0.5 rounded bg-accent/10 text-accent">{CARD_STATUS_TEXT[view.status] ?? view.status}</span>
        <span>结束类型 <ConceptTerm id={D.end}>{endText(facts.subject.end_kind, facts.subject.exit_basis)}</ConceptTerm></span>
        <a class="text-accent underline" href={`#instrument/${encodeURIComponent(facts.subject.ticker)}`}>标的页</a>
        {#if referencePlan}<a class="text-accent underline" href={`#plan/${planId(referencePlan.key)}`}>参考计划</a>{/if}
        <DiscussButton context={{ kind: 'card', card_id: id }} />
        <ConceptTerm id={D.card}>复盘卡说明</ConceptTerm>
      </p>
      <p class="text-xs text-muted">证据：未验证 <ConceptTerm id={ATTACH.agentCard.evidence}>证据状态</ConceptTerm></p>
    </header>

    <section class="space-y-2">
      <h3 class="font-semibold text-sm">预期 vs 实际</h3>
      <table aria-label="预期与实际" class="text-xs w-full">
        <thead><tr class="text-left text-muted"><th>计划</th><th>角色</th><th>价位</th><th>有效期</th><th>影子结果</th><th>首次触及</th></tr></thead>
        <tbody>
          {#each facts.plans as p (p.key)}
            <tr data-fact="plans shadow" class="align-top border-t border-border {hl('plans', 'shadow')}">
              <td>{KIND_TEXT[p.kind] ?? p.kind}{p.kind === 'agent' && p.version_no != null ? ` 第 ${p.version_no} 版` : ''}
                {#if p.status === 'invalid'}<span class="text-red-600">（已作废）</span>{/if}</td>
              <td>{p.roles.map(r => ROLE_TEXT[r] ?? r).join('、')}</td>
              <td>{p.levels.entry_low}–{p.levels.entry_high} · 止损 {p.levels.stop} · T1 {p.levels.target1}</td>
              <td>{p.valid_from} 至 {p.valid_until}</td>
              <td>{shadowText(p.key)}</td>
              <td>{touched(p.key)}</td>
            </tr>
          {:else}
            <tr><td colspan="6" class="text-muted">没有相关计划</td></tr>
          {/each}
        </tbody>
      </table>
      <p data-fact="bars_after" class="text-xs {hl('bars_after')}">日线摘要：{#if facts.bars_after.first_day}{facts.bars_after.first_day} 至 {facts.bars_after.last_day}（{facts.bars_after.sessions} 个交易日）· 最高 {facts.bars_after.high}（{facts.bars_after.high_date}）· 最低 {facts.bars_after.low}（{facts.bars_after.low_date}）· 结束收盘 {facts.bars_after.close_end}{:else}没有日线{/if}</p>
      {#if facts.reviews}
        <p data-fact="reviews" class="text-xs {hl('reviews')}">复查摘要：共 {facts.reviews.count} 次{#if facts.reviews.invalidated}；已作废（{facts.reviews.invalidated.session}{facts.reviews.invalidated.reason ? `：${facts.reviews.invalidated.reason}` : ''}）{/if}</p>
      {/if}
      <p data-fact="knowledge" class="text-xs {hl('knowledge')}">计划当时引用过的知识：{#each facts.knowledge as k, i (k.ref)}{#if i}、{/if}<a class="text-accent underline" href={knowHref(k.ref)}>{k.ref}</a> {k.title_at_version}{:else}没有{/each}</p>

      <section aria-label="复盘叙述" class="border-l-2 border-sky-400/50 pl-2 space-y-1 text-sm">
        {#if narrative}
          <p class="font-medium whitespace-pre-wrap">{narrative.headline}</p>
          <ol class="list-decimal ml-5 space-y-1">
            {#each narrative.expected_vs_actual as line, i (i)}
              <li><span class="whitespace-pre-wrap">{line.text}</span><RefList refs={line.refs} runId={okDraft?.agent_run_id} onFact={scrollToFact} /></li>
            {/each}
          </ol>
          <p><span class="text-xs text-muted">决定回顾</span> <span class="whitespace-pre-wrap">{narrative.decision_review.text}</span><RefList refs={narrative.decision_review.refs} runId={okDraft?.agent_run_id} onFact={scrollToFact} /></p>
        {:else}
          <p class="text-xs text-muted">还没有叙述草稿。</p>
        {/if}
      </section>
    </section>

    <section aria-label="三条轨道" data-fact="tracks" class="space-y-1 {hl('tracks')}">
      <h3 class="font-semibold text-sm">三条轨道 <span class="text-xs font-normal"><ConceptTerm id={D.tracks}>说明</ConceptTerm></span></h3>
      <ul class="text-sm space-y-0.5">
        {#if facts.tracks.rule}
          <li>{trackLine('规则', facts.tracks.rule)}{#if facts.tracks.rule.plan_id} · <a class="text-accent underline" href={`#plan/${facts.tracks.rule.plan_id}`}>看计划</a>{/if}</li>
        {/if}
        {#if facts.tracks.agent}
          <li>{trackLine(`Agent${facts.tracks.agent.version_no != null ? ` 第 ${facts.tracks.agent.version_no} 版` : ''}`, facts.tracks.agent)}{#if facts.tracks.agent.version_basis}（{VERSION_BASIS_TEXT[facts.tracks.agent.version_basis] ?? facts.tracks.agent.version_basis}）{/if}{#if facts.tracks.agent.plan_id} · <a class="text-accent underline" href={`#plan/${facts.tracks.agent.plan_id}`}>看计划</a>{/if}</li>
        {/if}
        <li>{trackLine('实际', facts.tracks.actual)}{#if facts.tracks.actual.plan_kind} · 照{KIND_TEXT[facts.tracks.actual.plan_kind] ?? facts.tracks.actual.plan_kind}计划{/if}</li>
      </ul>
    </section>

    <section aria-label="你的决定与纪律" class="space-y-2 text-sm">
      <h3 class="font-semibold">你的决定与纪律</h3>
      <p data-fact="decision" class={hl('decision')}>决定：{facts.decision.text}{#if facts.decision.reason}<span class="block text-xs text-muted whitespace-pre-wrap">理由：{facts.decision.reason}</span>{/if}</p>
      <ul data-fact="trades" class="text-xs space-y-0.5 {hl('trades')}">
        {#each facts.trades.trades as t (t.id)}
          <li>{t.side === 'buy' ? '买入' : '卖出'} {t.quantity} @ {t.price}（费 {t.fee}）· {fmtBeijing(t.executed_at)}</li>
        {:else}
          <li class="text-muted">没有成交</li>
        {/each}
      </ul>
      <div data-fact="discipline" class={hl('discipline')}>
        {#if !bought}
          <p>未成交，纪律四项不适用</p>
        {:else}
          <table aria-label="纪律判定" class="text-xs">
            <thead><tr class="text-left text-muted"><th></th><th>检测时</th>{#if disciplineChanged}<th>现在</th>{/if}</tr></thead>
            <tbody>
              {#each DISCIPLINE_FLAGS as flag (flag)}
                <tr>
                  <td class="pr-3"><ConceptTerm id={FLAG_CONCEPT[flag]}>{DISCIPLINE_TEXT[flag]}</ConceptTerm></td>
                  <td class="pr-3">{cell(view.facts.discipline, flag)}</td>
                  {#if disciplineChanged}<td>{cell(view.discipline_now, flag)}</td>{/if}
                </tr>
              {/each}
            </tbody>
          </table>
          <p class="text-xs text-muted">
            {#if disciplineChanged}检测时 = {view.facts.discipline.as_of} 的判定（冻结）；现在 = {view.discipline_now.as_of} 的只读重算，不改卡。
            {:else}判定于 {view.facts.discipline.as_of}（冻结）。{/if}
          </p>
        {/if}
      </div>
    </section>

    {#if !okDraft && !reviewed}
      <section aria-label="起草状态" class="border border-border rounded p-3 text-sm space-y-1">
        {#if canRedraft}
          <p>{CARD_STATUS_TEXT.draft_failed}</p>
          {#if lastDraft}<p class="text-xs text-muted">最近一次（第 {lastDraft.attempt} 次）：{reasonText(lastDraft.reason)}</p>{/if}
          <div class="flex items-center gap-2">
            <button type="button" class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2 disabled:opacity-50"
                    disabled={redraft.busy} onclick={runRedraft}>重新起草</button>
            {#if redraft.text}<span role={redraft.busy ? undefined : 'alert'} class="text-xs">{redraft.text}</span>{/if}
          </div>
        {:else}
          <p class="text-xs text-muted">这张卡还在起草，稍后刷新查看；现在也可以直接审定。</p>
        {/if}
      </section>
    {/if}

    <section aria-label="教训草稿与审定" class="space-y-2">
      <h3 class="font-semibold text-sm">教训草稿与审定</h3>
      <CardVerdictForm cardId={id} drafts={view.lesson_drafts} verdict={view.verdict} {runId} onFact={scrollToFact} onSubmitted={() => load()} />
    </section>

    {#if runId}
      <div class="space-y-1">
        <button type="button" class="text-xs text-accent underline" aria-expanded={reasoningOpen}
                onclick={() => reasoningOpen = !reasoningOpen}>看起草过程</button>
        {#if reasoningOpen}<AgentReasoning {runId} />{/if}
      </div>
    {/if}

    <section aria-label="讨论" class="space-y-1 text-sm">
      <h3 class="font-semibold">讨论</h3>
      <ul class="text-xs space-y-0.5">
        {#each view.discussions as d (d.id)}
          <li><a class="text-accent underline" href={`#discuss/${d.id}`}>{fmtBeijing(d.created_at)} · {d.turn_count} 轮{d.first_question ? ` · ${truncate(d.first_question, 40)}` : ''}</a></li>
        {:else}
          <li class="text-muted">还没有讨论</li>
        {/each}
      </ul>
    </section>
  {/if}
</section>
