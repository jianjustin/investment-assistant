<script lang="ts">
  import AgentReasoning from './AgentReasoning.svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import DiscussButton from './DiscussButton.svelte'
  import KnowledgeRefs from './KnowledgeRefs.svelte'
  import PlanDerivation from './PlanDerivation.svelte'
  import { ATTACH } from '../knowledge'
  import { fmtBeijing } from '../format'
  import { isKnowRef, knowHref } from '../growth'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // §10.1 的 Agent 块，「今日」与计划页共用。数字照后端字符串原样显示；「证据：未验证」常驻。
  let { agent, onCall, onRerun }: { agent: tl.AgentView; onCall: (ref: string) => void; onRerun?: () => void } = $props()

  let derivationOpen = $state(false)
  let reasoningOpen = $state(false)
  const A = ATTACH.agentCard

  const LEVEL_TEXT = [['entry_low', '入场下限'], ['entry_high', '入场上限'], ['stop', '止损'], ['target1', 'T1']] as const

  const run = $derived(agent.status === 'ok' || agent.status === 'pass' ? (agent as wb.AgentRunOk) : null)
  const failed = $derived(run ? null : (agent as wb.AgentRunFailed))
  const legacy = $derived(!!agent.legacy || ('agent_version' in agent && agent.agent_version === 'agent-1'))
  const chain = $derived(agent.chain ?? null)
  const versionNo = $derived(chain?.version_no ?? null)
  const review = $derived(chain?.latest_review ?? null)
  const output = $derived(run?.output ?? null)
  const plan = $derived(run?.plan ?? null)
  const invalidated = $derived(chain?.state === 'invalidated')

  const title = $derived.by(() => {
    const parts = ['Agent 计划']
    if (versionNo != null) parts.push(`第 ${versionNo} 版`)
    if (run) parts.push(`生成于 ${fmtBeijing(run.created_at)}`)
    if (chain?.cutoff_at) parts.push(`截止 ${fmtBeijing(chain.cutoff_at)}`)
    return parts.join(' · ')
  })
  const levelsLine = $derived(output?.levels
    ? `${output.action === 'buy' ? '买入' : '不建议买入'} · 入场区间 ${output.levels.entry_low.value}–${output.levels.entry_high.value}`
      + ` · 止损 ${output.levels.stop.value} · T1 ${output.levels.target1.value}`
    : '')
  // 没有复查、或最近复查产生的正是本版（它判定的是上一版的条件）→「尚未复查」；
  // 复查行没带 conditions（今日视图尚未提供）→ 不标；带了 → 按 list/index 取判定。
  const judgedThisVersion = $derived(!!review && !(review.new_plan_id && plan && review.new_plan_id === plan.id))
  const resultOf = (list: 'invalidation' | 'review_when', index: number): string | null => {
    if (!judgedThisVersion) return '尚未复查'
    if (!review?.conditions) return null
    const hit = review.conditions.find(c => c.list === list && c.index === index)
    return hit ? tl.CONDITION_RESULT_TEXT[hit.result] ?? hit.result : null
  }
  const countersOf = (n: number) => (run?.counter?.counter ?? []).filter(c => c.thesis === n)
  const reviewLine = $derived(review
    ? `最近复查：${tl.OUTCOME_TEXT[review.outcome] ?? review.outcome}`
      + `${review.decided_by ? ` · ${tl.DECIDED_BY_TEXT[review.decided_by] ?? review.decided_by}` : ''}`
      + `${review.reason ? ` · ${review.reason}` : ''} · ${fmtBeijing(review.created_at)}`
    : '')
  const revisionFailure = $derived(versionNo != null ? tl.revisionFailureText(review, versionNo) : null)
  const reasonText = (reason: string | null | undefined) => wb.AGENT_REASON_TEXT[reason ?? ''] ?? reason ?? '未知原因'
  const changeField = (field: string) => tl.CHANGE_FIELD_TEXT[field] ?? field
</script>

{#snippet refList(list: string[] | undefined)}{#if list?.length}（{#each list as ref, i}{#if i}、{/if}{#if tl.isCallRef(ref)}<button class="underline" onclick={() => onCall(ref)}>{ref}</button>{:else if isKnowRef(ref)}<a class="text-accent underline" href={knowHref(ref)}>{ref}</a>{:else}<span>{ref}</span>{/if}{/each}）{/if}{/snippet}

{#snippet derivation()}
  {#if plan}
    <div class="space-y-1">
      <button class="text-xs text-accent underline" aria-expanded={derivationOpen}
              onclick={() => derivationOpen = !derivationOpen}>展开推导</button>
      {#if derivationOpen}<PlanDerivation planId={plan.id} />{/if}
    </div>
  {/if}
{/snippet}

<div role="region" aria-label="Agent 计划" class="text-sm border-l-2 border-sky-400/50 pl-2 space-y-1">
  {#if failed}
    <p class="font-medium">Agent 未给出计划：{reasonText(failed.reason)} <ConceptTerm id={A.rejectReasons}>作废原因</ConceptTerm></p>
    {#if legacy}<p class="text-xs text-amber-700">agent-1（旧版，不参与复查） <ConceptTerm id={A.legacy}>旧版说明</ConceptTerm></p>{/if}
    {#if onRerun}
      <button class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2" onclick={onRerun}>重新运行 Agent</button>
    {/if}
  {:else if run && legacy}
    <!-- agent-1：原样展示（v2.4 的块），只加旧版标注。 -->
    <p class="font-medium">Agent 建议（{run.model} · {run.agent_version}）{run.status === 'ok' ? '买入' : '不建议买入'}</p>
    <p class="text-xs text-amber-700">agent-1（旧版，不参与复查） <ConceptTerm id={A.legacy}>旧版说明</ConceptTerm></p>
    {#if output?.levels}
      {@const levels = output.levels}
      <p>入场区间 {levels.entry_low.value}–{levels.entry_high.value} · 止损 {levels.stop.value} · T1 {levels.target1.value}</p>
      <p class="text-xs text-muted">价位引用：{#each LEVEL_TEXT as [key, label], k}{#if k} · {/if}{label}（{#each levels[key].refs as ref, i}{#if i}、{/if}<button class="underline" onclick={() => onCall(ref)}>{ref}</button>{/each}）{/each} <ConceptTerm id={A.citation}>引用编号</ConceptTerm></p>
    {/if}
    {#if plan?.sizing?.shares != null}<p>建议 {plan.sizing.shares} 股</p>{/if}
    {#if output?.summary}<p>{output.summary}</p>{/if}
    {#if output?.thesis?.length}
      <ul class="list-disc ml-5 text-xs text-muted">
        {#each output.thesis as t}<li>{t.text}{@render refList(t.refs)}</li>{/each}
      </ul>
    {/if}
    {#if run.counter?.risks?.length}
      <p class="text-xs">反方：{#each run.counter.risks as risk, i}{#if i}；{/if}{risk.text}{@render refList(risk.refs)}{/each}</p>
    {/if}
    {#if plan?.status === 'invalid'}<p class="text-red-600">Agent 计划已作废：{plan.invalid_reasons.join('、')}</p>{/if}
    {@render derivation()}
  {:else if run && invalidated}
    <p class="font-medium">Agent 已作废此计划（第 {versionNo} 版）：{review?.reason ?? ''}</p>
  {:else if run && run.status === 'pass'}
    <p class="font-medium">Agent 不建议买入：{output?.summary ?? ''}</p>
  {:else if run}
    <p class="font-medium">{title} <span class="text-xs font-normal"><ConceptTerm id={A.version}>版本链</ConceptTerm> <ConceptTerm id={A.cutoff}>截止时间</ConceptTerm></span></p>
    <p class="text-xs text-muted">模型 {run.model} · {run.agent_version}{chain?.mode ? ` · ${tl.MODE_TEXT[chain.mode]}` : ''}</p>
    {#if output?.levels}
      {@const levels = output.levels}
      <p>{levelsLine} <ConceptTerm id={A.levels}>动作与价位</ConceptTerm></p>
      <p class="text-xs text-muted">价位引用：{#each LEVEL_TEXT as [key, label], k}{#if k} · {/if}{label}{@render refList(levels[key].refs)}{/each} <ConceptTerm id={A.citation}>引用编号</ConceptTerm></p>
    {/if}
    {#if plan?.sizing?.shares != null}<p>建议 {plan.sizing.shares} 股</p>{/if}
    {#if output?.summary}<p>{output.summary}</p>{/if}

    {#if output?.thesis?.length}
      <p class="text-xs text-muted"><ConceptTerm id={A.thesis}>论点</ConceptTerm> · <ConceptTerm id={A.counter}>反方</ConceptTerm></p>
      <ol aria-label="论点" class="ml-1 space-y-1">
        {#each output.thesis as t, i}
          <li>
            <span class="text-xs px-1 rounded bg-surface-2">{t.id ?? `T${i + 1}`}</span> {t.text}{@render refList(t.refs)}
            <ul class="ml-5 text-xs">
              {#each countersOf(i + 1) as c}
                <li>反证：{c.text}{@render refList(c.refs)}</li>
              {:else}
                <li class="text-muted">反方未对此论点给出反证</li>
              {/each}
            </ul>
          </li>
        {/each}
      </ol>
    {/if}
    {#if run.counter?.risks?.length}
      <p class="text-xs">其他风险：{#each run.counter.risks as risk, i}{#if i}；{/if}{risk.text}{@render refList(risk.refs)}{/each}</p>
    {/if}

    {#if output?.invalidation?.length}
      <p class="text-xs text-muted"><ConceptTerm id={A.invalidation}>失效条件</ConceptTerm></p>
      <ul aria-label="失效条件" class="list-disc ml-5 text-xs">
        {#each output.invalidation as cond, i}
          {@const result = resultOf('invalidation', i)}
          <li>{tl.conditionText(cond.kind, cond.params)}{result ? ` · 最近判定：${result}` : ''}{@render refList(cond.refs)}</li>
        {/each}
      </ul>
    {/if}
    <p class="text-xs text-muted"><ConceptTerm id={A.reviewWhen}>下次复查条件</ConceptTerm></p>
    <ul aria-label="下次复查条件" class="list-disc ml-5 text-xs">
      {#each output?.review_when ?? [] as cond}
        <li>{tl.conditionText(cond.kind, cond.params)}</li>
      {:else}
        <li>{tl.conditionText('next_session', {})}</li>
      {/each}
    </ul>

    {#if versionNo != null && versionNo >= 1}
      <div role="region" aria-label={`相对第 ${versionNo - 1} 版`} class="text-xs grid md:grid-cols-2 gap-2">
        <div>
          <p class="text-muted"><ConceptTerm id={A.changes}>相对第 {versionNo - 1} 版 · 宿主差异</ConceptTerm></p>
          {#if chain?.diff}
            <ul class="list-disc ml-5">
              {#each chain.diff as d}
                <li>{changeField(d.field)} {tl.diffValueText(d.field, d.before)} → {tl.diffValueText(d.field, d.after)}</li>
              {:else}
                <li class="text-muted">无</li>
              {/each}
            </ul>
          {:else if plan}
            <p><a class="text-accent underline" href={`#plan/${plan.id}`}>见计划页版本链</a></p>
          {/if}
        </div>
        <div>
          <p class="text-muted">模型说明</p>
          <ul class="list-disc ml-5">
            {#each output?.changes ?? [] as c}
              <li>{changeField(c.field)}：{c.text}{@render refList(c.refs)}</li>
            {:else}
              <li class="text-muted">无</li>
            {/each}
          </ul>
        </div>
      </div>
    {/if}

    {#if reviewLine}<p class="text-xs">{reviewLine} <ConceptTerm id={A.review}>复查结论</ConceptTerm></p>{/if}
    {#if revisionFailure}<p class="text-xs text-amber-700">{revisionFailure} <ConceptTerm id={A.rejectReasons}>作废原因</ConceptTerm></p>{/if}
    {#if plan?.status === 'invalid'}
      {#if chain?.mode === 'holding'}
        <!-- §5.2：持仓期新版按仓位规则作废（如 no_room）只说明不能再加仓，链照常有效、照常复查。 -->
        <p class="text-amber-700">本版按仓位规则不能加仓（{plan.invalid_reasons.join('、')}） <ConceptTerm id={A.noAdd}>仓位规则</ConceptTerm></p>
      {:else}
        <p class="text-red-600">Agent 计划已作废：{plan.invalid_reasons.join('、')}</p>
      {/if}
    {/if}
    {@render derivation()}
  {/if}
  <KnowledgeRefs refs={agent.knowledge_refs ?? []} />
  <p class="text-xs text-muted">证据：未验证 <ConceptTerm id={A.evidence}>证据状态</ConceptTerm></p>
  <!-- v2.6 §8.6：看生成这一版的那次运行；展开时才请求 -->
  <div class="space-y-1">
    <div class="flex flex-wrap items-center gap-3">
      <button type="button" class="text-xs text-accent underline" aria-expanded={reasoningOpen}
              onclick={() => reasoningOpen = !reasoningOpen}>看推理过程</button>
      {#if plan}<DiscussButton context={{ kind: 'plan', plan_id: plan.id }} />{/if}
    </div>
    {#if reasoningOpen}<AgentReasoning runId={agent.id} />{/if}
  </div>
</div>
