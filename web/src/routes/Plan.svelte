<script lang="ts">
  import AgentReasoning from '../lib/components/AgentReasoning.svelte'
  import ConceptTerm from '../lib/components/ConceptTerm.svelte'
  import DiscussButton from '../lib/components/DiscussButton.svelte'
  import PlanDerivation from '../lib/components/PlanDerivation.svelte'
  import PlanTimeline from '../lib/components/PlanTimeline.svelte'
  import UserInputs from '../lib/components/UserInputs.svelte'
  import * as api from '../lib/api'
  import type { Derivation } from '../lib/derivation'
  import { ATTACH } from '../lib/knowledge'
  import { growthError, truncate } from '../lib/growth'
  import type { DiscussionListItem } from '../lib/growth'
  import { fmtBeijing } from '../lib/format'

  // 整页渲染 PlanDerivation（spec 2026-10-27 §10）。标题取推导里的标的与日期，
  // 所以页面自己再请求一次；取不到（404/400/503）时退化为 id，错误文案交给组件呈现，不白屏。
  // agent-2 计划另显示版本链、复查记录与「我的补充」（v2.5 spec §11）。
  // agent-1 计划没有版本链与计划卡，另给一段「看推理过程」，按生成它的运行取推理视图（v2.6 spec §8.5）。
  let { sub }: { sub: string } = $props()
  let title = $state('')
  let ticker = $state('')
  let unit = $state<{ ticker: string; signal_date: string } | null>(null)
  let legacyRunId = $state<string | null>(null)
  let reasoningOpen = $state(false)
  // v2.7 §8.1：这个计划已有的讨论；读不到（如迁移 027 未执行）只影响这一段
  let discussions = $state<DiscussionListItem[] | null>(null)
  let discussionsError = $state('')

  $effect(() => {
    const id = sub
    let alive = true
    unit = null
    ticker = ''
    legacyRunId = null
    reasoningOpen = false
    discussions = null
    discussionsError = ''
    void api.getDiscussions({ plan_id: id })
      .then(res => { if (alive) discussions = Array.isArray(res?.discussions) ? res.discussions : [] })
      .catch((e: unknown) => { if (alive) discussionsError = growthError(e) })
    void api.getPlanDerivation(id)
      .then((d: Derivation) => {
        if (!alive) return
        title = `${d.plan.ticker ?? '—'} · ${d.plan.signal_date ?? '—'}`
        ticker = d.plan.ticker ?? ''
        unit = d.plan.plan_version === 'agent-2' && d.plan.ticker && d.plan.signal_date
          ? { ticker: d.plan.ticker, signal_date: d.plan.signal_date } : null
        const runId = d.inputs.agent_run?.id
        legacyRunId = d.plan.plan_version === 'agent-1' && typeof runId === 'string' ? runId : null
      })
      .catch(() => { if (alive) title = id })
    return () => { alive = false }
  })

  // 有历史就后退；没有历史（直链打开）时不拦截，沿 href 落到「今日」。
  function goBack(e: MouseEvent) {
    if (history.length > 1) { e.preventDefault(); history.back() }
  }
</script>

<section class="space-y-4">
  <header class="flex items-center gap-3">
    <a href="#today" onclick={goBack} class="text-sm text-accent underline">返回</a>
    <h1 class="text-lg font-semibold">{title || '加载中…'}</h1>
    {#if ticker}<a href={`#instrument/${encodeURIComponent(ticker)}`} class="text-sm text-accent underline">标的页</a>{/if}
    {#if ticker}<DiscussButton context={{ kind: 'plan', plan_id: sub }} />{/if}
  </header>
  {#key sub}
    {#if unit}
      <PlanTimeline ticker={unit.ticker} signalDate={unit.signal_date} currentPlanId={sub} />
    {/if}
    {#if legacyRunId}
      <section aria-label="Agent 推理" class="space-y-2">
        <p class="text-xs text-amber-700">agent-1（旧版，不参与复查） <ConceptTerm id={ATTACH.agentCard.legacy}>旧版说明</ConceptTerm></p>
        <button type="button" class="text-xs text-accent underline" aria-expanded={reasoningOpen}
                onclick={() => reasoningOpen = !reasoningOpen}>看推理过程</button>
        {#if reasoningOpen}<AgentReasoning runId={legacyRunId} />{/if}
      </section>
    {/if}
    <PlanDerivation planId={sub} />
    {#if unit}
      <UserInputs ticker={unit.ticker} signalDate={unit.signal_date} />
    {/if}
    {#if ticker}
      <section aria-label="讨论" class="space-y-1 text-sm">
        <p class="font-medium">讨论 <span class="text-xs font-normal"><ConceptTerm id={ATTACH.discussion.about}>说明</ConceptTerm></span></p>
        {#if discussionsError}
          <p class="text-xs text-muted">{`讨论不可用：${discussionsError}`}</p>
        {:else if discussions === null}
          <p class="text-xs text-muted">加载中…</p>
        {:else if discussions.length === 0}
          <p class="text-xs text-muted">还没有讨论</p>
        {:else}
          <ul class="text-xs space-y-0.5">
            {#each discussions as d (d.id)}
              <li><a class="text-accent underline" href={`#discuss/${d.id}`}>{fmtBeijing(d.created_at)} · {d.turn_count} 轮{d.first_question ? ` · ${truncate(d.first_question, 40)}` : ''}</a></li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}
  {/key}
</section>
