<script lang="ts">
  import { onMount } from 'svelte'
  import AgentReasoning from './AgentReasoning.svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import * as api from '../api'
  import { CONSISTENCY_TEXT } from '../derivation'
  import { fmtBeijing } from '../format'
  import { TOOL_TEXT, type ReasoningCall, type ReasoningStep, type ReasoningView } from '../knowledge'
  import * as tl from '../timeline'

  // Agent 推理阅读视图（spec §8.6）：展开时才挂载，挂载时请求一次；步骤顺序、概念、校验结果都来自接口。
  let { runId }: { runId: string } = $props()

  let data = $state<ReasoningView | null>(null)
  let error = $state('')
  let root: HTMLElement | undefined
  let highlighted = $state<number | null>(null)
  let shownResult = $state<Record<number, boolean>>({})
  let fullList = $state<Record<string, boolean>>({})
  let nested = $state<Record<string, boolean>>({})

  onMount(() => {
    const id = runId
    api.getReasoning(id).then(next => { data = next }).catch((e: unknown) => {
      error = String((e as Error)?.message ?? e)
    })
  })

  const MODE_TEXT: Record<string, string> = { propose: '提议', revise: '修订', review: '复查', interpret: '解读' }
  const RUN_STATUS_TEXT: Record<string, string> = {
    ok: '成功', pass: '不建议买入', rejected: '已作废', error: '出错', skipped: '跳过',
  }
  const LEVEL_TEXT: Record<string, string> = { entry_low: '入场下限', entry_high: '入场上限', stop: '止损', target1: 'T1' }
  const CHECK_TEXT: Record<string, string> = {
    pass: '通过', implicated: '可能未通过', not_recorded: '未单独记录', not_run: '未运行',
  }
  const CHECK_CLASS: Record<string, string> = {
    pass: 'text-muted', implicated: 'text-amber-700', not_recorded: 'text-muted', not_run: 'text-muted',
  }
  const ACTION_TEXT: Record<string, string> = { buy: '买入', pass: '不建议买入' }

  // 提议 / 复查 / 修订里没有存下来的步骤：接口把它们省掉或不给内容，页面只说明整次运行的结局。
  // 后端对没存下来的步骤给 available: false 与说明；万一整个内容步骤都没有，页面自己补一句。
  const CONTENT_KINDS = ['proposal', 'verdict', 'interpretation']
  const rejectedWithoutContent = $derived(
    !!data && !['ok', 'pass'].includes(data.run.status)
    && !data.steps.some(step => CONTENT_KINDS.includes(step.kind)))
  const toolName = (call: ReasoningCall) => call.tool_text ?? TOOL_TEXT[call.tool] ?? call.tool
  const text = (value: unknown): string =>
    typeof value === 'string' ? value : value == null ? '—' : JSON.stringify(value)
  const implicatedNote = (step: ReasoningStep): string | null => {
    if (step.note) return step.note
    const names = (step.items ?? []).filter(item => item.result === 'implicated').map(item => String(item.text))
    return names.length
      ? `未通过的检查在这几项之中：${names.join('、')}；校验器遇到第一处失败就停，不记录是哪一项` : null
  }

  function jump(ref: string) {
    const seq = Number(ref.split(':')[1])
    if (!Number.isFinite(seq)) return
    highlighted = seq
    const row = root?.querySelector(`[data-call="${seq}"]`)
    row?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }
  const consistencyOf = (value: ReasoningStep['consistency']): string | null =>
    value == null ? null : typeof value === 'string' ? value : value.status ?? null
  const thesisLabel = (value: unknown) => typeof value === 'number' ? `T${value}` : String(value)
  // fields keyed by something that is not a top-level key of the result: macro series, rule ids of get_trigger
  const extraFields = (call: ReasoningCall): [string, string][] => {
    const top = new Set(resultEntries(call.result).map(([key]) => key))
    return Object.entries(call.fields ?? {}).filter(([key]) => !top.has(key))
  }
  const resultEntries = (result: unknown): [string, unknown][] =>
    Array.isArray(result) ? [['结果', result]]
      : result && typeof result === 'object' ? Object.entries(result as Record<string, unknown>)
      : [['结果', result]]
  const listKey = (seq: number, key: string) => `${seq}|${key}`
</script>

{#snippet refList(list: string[] | undefined)}{#if list?.length}（{#each list as ref, i}{#if i}、{/if}{#if tl.isCallRef(ref)}<button type="button" class="underline" onclick={() => jump(ref)}>{ref}</button>{:else}<span>{ref}</span>{/if}{/each}）{/if}{/snippet}

{#snippet conditionList(label: string, list: any[] | undefined)}
  {#if list?.length}
    <ul aria-label={label} class="list-disc ml-5 text-xs">
      {#each list as cond}<li>{cond.text ?? tl.conditionText(cond.kind, cond.params)}{@render refList(cond.refs)}</li>{/each}
    </ul>
  {/if}
{/snippet}

<section bind:this={root} aria-label="推理过程" class="text-sm border-l-2 border-border pl-2 space-y-3">
  {#if error}
    <p role="alert" class="text-xs text-red-600">{error}</p>
  {:else if !data}
    <p class="text-xs text-muted">推理过程加载中…</p>
  {:else}
    {@const run = data.run}
    <p class="text-xs text-muted">
      {run.ticker} · {run.signal_date} · {MODE_TEXT[run.mode] ?? run.mode} · {run.agent_version}{run.model ? ` · ${run.model}` : ''}
      {#if run.cutoff_at} · 截止 {fmtBeijing(run.cutoff_at)}{/if}
    </p>
    {#if data.version}
      <p class="text-xs text-muted">这次运行产出第 {data.version.version_no} 版 · {tl.ORIGIN_TEXT[data.version.origin as tl.Origin] ?? data.version.origin}
        · <a class="text-accent underline" href={`#plan/${data.version.plan_id}`}>看计划页</a></p>
    {/if}
    {#each data.notes as note}<p class="text-xs text-amber-700">{note}</p>{/each}
    {#if !['ok', 'pass'].includes(run.status)}
      <p class="text-xs text-amber-700">本次运行状态：{RUN_STATUS_TEXT[run.status] ?? run.status}（{run.reason_text ?? run.reason ?? '未知原因'}）</p>
    {/if}
    {#if rejectedWithoutContent}
      <p class="text-xs">这次运行作废：{run.reason_text ?? run.reason ?? '未知原因'}，只保留工具调用</p>
    {/if}

    {#each data.steps as step, index (index)}
      <section aria-label={step.title} class="space-y-1">
        <h4 aria-label={step.title} class="font-medium text-xs">
          {#if step.concept}<ConceptTerm id={step.concept}>{step.title}</ConceptTerm>{:else}{step.title}{/if}
        </h4>
        {#if step.note && step.kind !== 'check'}<p class="text-xs text-muted">{step.note}</p>{/if}

        {#if step.kind === 'read'}
          <ul class="space-y-1">
            {#each step.calls ?? [] as call (call.seq)}
              <li data-call={call.seq} data-highlighted={highlighted === call.seq ? 'true' : undefined}
                  class="text-xs rounded px-1 {highlighted === call.seq ? 'bg-amber-100 ring-1 ring-amber-400' : ''}">
                <p class="break-all">
                  <span class="font-medium">{call.ref}</span> ·
                  {#if call.concept}<ConceptTerm id={call.concept}>{toolName(call)}</ConceptTerm>{:else}{toolName(call)}{/if}
                  · <code>{text(call.args)}</code> · 哈希 {call.result_sha256_8}
                  <button type="button" class="text-accent underline" aria-expanded={!!shownResult[call.seq]}
                          onclick={() => shownResult[call.seq] = !shownResult[call.seq]}>{shownResult[call.seq] ? '收起返回值' : '看返回值'}</button>
                </p>
                {#if call.cutoff_exempt}
                  <p class="text-amber-700">{call.cutoff_note ?? '概念卡随代码版本走，不受截止时间约束'}</p>
                {/if}
                {#if call.error}<p class="text-red-600">工具返回错误：{text(call.error)}</p>{/if}
                {#if shownResult[call.seq]}
                  <div class="ml-3 space-y-0.5">
                    {#if extraFields(call).length}
                      <p class="text-muted">涉及：{#each extraFields(call) as [name, concept], i (name)}{#if i}、{/if}<ConceptTerm id={concept}>{name}</ConceptTerm>{/each}</p>
                    {/if}
                    {#each resultEntries(call.result) as [key, value] (key)}
                      {#if Array.isArray(value)}
                        {@const all = !!fullList[listKey(call.seq, key)]}
                        {@const shown = all || value.length <= 4 ? value : [...value.slice(0, 2), ...value.slice(-2)]}
                        <p>
                          {#if call.fields[key]}<ConceptTerm id={call.fields[key]}>{key}</ConceptTerm>{:else}{key}{/if}（{value.length} 条）
                          {#if value.length > 4}
                            <button type="button" class="text-accent underline"
                                    onclick={() => fullList[listKey(call.seq, key)] = !all}>{all ? '只看首尾' : '展开全部'}</button>
                          {/if}
                        </p>
                        <ul class="ml-3 break-all">
                          {#each shown as item, i}
                            <li>{text(item)}</li>
                            {#if !all && value.length > 4 && i === 1}<li class="text-muted">…</li>{/if}
                          {/each}
                        </ul>
                      {:else}
                        <p class="break-all">
                          {#if call.fields[key]}<ConceptTerm id={call.fields[key]}>{key}</ConceptTerm>{:else}{key}{/if}：{text(value)}
                        </p>
                      {/if}
                    {/each}
                  </div>
                {/if}
              </li>
            {/each}
          </ul>

        {:else if step.kind === 'proposal'}
          {#if step.available === false}
            <p class="text-xs">{step.text}</p>
          {/if}
          {#if step.action || step.summary}
            <p>{step.action ? (step.action_text ?? ACTION_TEXT[step.action] ?? step.action) : ''}{step.action && step.summary ? ' · ' : ''}{step.summary ?? ''}</p>
          {/if}
          {#if step.levels?.length}
            <ul aria-label="价位" class="text-xs">
              {#each step.levels as level (level.key)}
                <li>{level.label ?? LEVEL_TEXT[level.key] ?? level.key} {level.value}{@render refList(level.refs)}
                  {#if level.concept}<ConceptTerm id={level.concept} />{/if}</li>
              {/each}
            </ul>
          {/if}
          {#if step.thesis?.length || step.reasons?.length}
            {@const entries = step.thesis ?? step.reasons ?? []}
            <p class="text-xs text-muted">{data.legacy ? '理由' : '论点'}</p>
            <ol aria-label={data.legacy ? '理由' : '论点'} class="ml-1 space-y-0.5 text-xs">
              {#each entries as t, i}
                <li>{#if !data.legacy}<span class="px-1 rounded bg-surface-2">{(t as any).id ?? `T${i + 1}`}</span> {/if}{t.text}{@render refList(t.refs)}</li>
              {/each}
            </ol>
          {/if}
          {@render conditionList('失效条件', step.invalidation)}
          {@render conditionList('下次复查条件', step.review_when)}
          {#if step.diff?.length}
            <p class="text-xs text-muted">相对上版 · 宿主差异</p>
            <ul class="list-disc ml-5 text-xs">
              {#each step.diff as d}
                <li>{tl.CHANGE_FIELD_TEXT[d.field] ?? d.field} {tl.diffValueText(d.field, d.before)} → {tl.diffValueText(d.field, d.after)}</li>
              {/each}
            </ul>
          {/if}
          {#if step.changes?.length}
            <p class="text-xs text-muted">模型说明</p>
            <ul class="list-disc ml-5 text-xs">
              {#each step.changes as c}<li>{tl.CHANGE_FIELD_TEXT[c.field] ?? c.field}：{c.text}{@render refList(c.refs)}</li>{/each}
            </ul>
          {/if}

        {:else if step.kind === 'check'}
          <ul class="text-xs space-y-0.5">
            {#each step.items ?? [] as item, i (item.id ?? i)}
              <li>{item.text} · <span class={CHECK_CLASS[item.result] ?? 'text-muted'}>{CHECK_TEXT[item.result] ?? item.result}</span></li>
            {/each}
          </ul>
          {#if implicatedNote(step)}<p class="text-xs text-amber-700">{implicatedNote(step)}</p>{/if}
          {#if step.reason_text && (step.items ?? []).some(item => item.result === 'not_run')}
            <p class="text-xs text-muted">{step.reason_text}</p>
          {/if}

        {:else if step.kind === 'counter'}
          {#if step.available === false}<p class="text-xs">{step.text}</p>{/if}
          {#if step.items?.length}
            <ul aria-label="反证" class="text-xs space-y-0.5">
              {#each step.items as c}
                <li><span class="px-1 rounded bg-surface-2">{thesisLabel(c.thesis)}</span> {c.text}{@render refList(c.refs)}</li>
              {/each}
            </ul>
          {/if}
          {#if step.risks?.length}
            <p class="text-xs">其他风险：{#each step.risks as risk, i}{#if i}；{/if}{risk.text}{@render refList(risk.refs)}{/each}</p>
          {/if}
          {#if step.uncountered?.length}
            <p class="text-xs text-muted">反方未对这些论点给出反证：{step.uncountered.map(thesisLabel).join('、')}</p>
          {/if}
          {#if step.available !== false && step.dropped != null}<p class="text-xs text-muted">丢弃 {step.dropped} 条无效反证</p>{/if}

        {:else if step.kind === 'response'}
          {#each (step as any).items ?? [] as item (item.review_id)}
            <div class="text-xs space-y-0.5">
              <p>{item.session} · {tl.TRIGGER_TEXT[item.trigger] ?? item.trigger} · {tl.OUTCOME_TEXT[item.outcome as tl.Outcome] ?? item.outcome}
                {#if item.decided_by} · {tl.DECIDED_BY_TEXT[item.decided_by as tl.DecidedBy] ?? item.decided_by}{/if}
                {#if item.new_plan_id} → <a class="text-accent underline" href={`#plan/${item.new_plan_id}`}>第 {item.new_version_no} 版</a>{/if}</p>
              {#if item.reason}<p>{item.reason}</p>{/if}
              {#if item.signals_fired?.length}
                <p class="text-muted">信号：{item.signals_fired.map((k: string) => tl.SIGNAL_TEXT[k] ?? k).join('、')}</p>
              {/if}
              {#if item.changes?.length}
                <ul class="list-disc ml-5">
                  {#each item.changes as d}<li>{tl.CHANGE_FIELD_TEXT[d.field] ?? d.field} {tl.diffValueText(d.field, d.before)} → {tl.diffValueText(d.field, d.after)}</li>{/each}
                </ul>
              {/if}
            </div>
          {/each}

        {:else if step.kind === 'outcome'}
          <p class="text-xs">
            {#if step.plan_id}
              计划行：{step.status === 'invalid' ? `已作废（${(step.invalid_reasons ?? []).join('、')}）` : '有效'}
              {#if consistencyOf(step.consistency)} · {CONSISTENCY_TEXT[consistencyOf(step.consistency) as keyof typeof CONSISTENCY_TEXT] ?? consistencyOf(step.consistency)}{/if}
              · <a class="text-accent underline" href={`#plan/${step.plan_id}`}>看推导</a>
            {:else}
              这次运行没有生成计划行
            {/if}
          </p>

        {:else if step.kind === 'evidence'}
          <div class="text-xs space-y-0.5">
            {#if step.text}<p>{step.text}</p>{/if}
            {#if step.session}<p>复查交易日 {step.session} · {tl.TRIGGER_TEXT[step.trigger ?? ''] ?? step.trigger ?? ''}</p>{/if}
            {#if step.signals?.length}
              <p>触发的信号：{step.signals.filter(s => s.fired).map(s => `${tl.SIGNAL_TEXT[s.kind] ?? s.kind}${s.detail ? `（${s.detail}）` : ''}`).join('、') || '无'}</p>
            {/if}
            {#if step.conditions?.length}
              <p>条件判定：{step.conditions.map(c => `${tl.conditionText(c.kind, c.params)}：${tl.CONDITION_RESULT_TEXT[c.result as tl.ConditionResultValue] ?? c.result}`).join('；')}</p>
            {/if}
            {#if step.user_input_ids?.length}<p>给模型的用户输入：{step.user_input_ids.map(i => `user:${i}`).join('、')}</p>{/if}
            {#if step.review_agent_run_id && step.review_agent_run_id !== runId}
              <button type="button" class="text-accent underline" aria-expanded={!!nested[step.review_agent_run_id]}
                      onclick={() => nested[step.review_agent_run_id!] = !nested[step.review_agent_run_id!]}>看复查推理</button>
              {#if nested[step.review_agent_run_id]}<AgentReasoning runId={step.review_agent_run_id} />{/if}
            {/if}
            {#if step.revision_agent_run_id && step.revision_agent_run_id !== runId}
              <button type="button" class="text-accent underline" aria-expanded={!!nested[step.revision_agent_run_id]}
                      onclick={() => nested[step.revision_agent_run_id!] = !nested[step.revision_agent_run_id!]}>看修订推理</button>
              {#if nested[step.revision_agent_run_id]}<AgentReasoning runId={step.revision_agent_run_id} />{/if}
            {/if}
          </div>

        {:else if step.kind === 'verdict'}
          {#if step.available === false}<p class="text-xs">{step.text}</p>{/if}
          <p class="text-xs">{step.outcome_text ?? tl.OUTCOME_TEXT[step.outcome as tl.Outcome] ?? step.outcome ?? ''}
            {#if step.decided_by} · {tl.DECIDED_BY_TEXT[step.decided_by as tl.DecidedBy] ?? step.decided_by}{/if}</p>
          {#if step.reason}<p class="text-xs">{step.reason}{@render refList(step.refs)}</p>{/if}

        {:else if step.kind === 'interpretation'}
          {#if step.available === false}<p class="text-xs">{step.text}</p>{/if}
          {#if step.summary}<p>{step.summary}</p>{/if}
          {#each [['支持', step.support], ['反证', step.contra], ['冲突与缺口', step.conflicts]] as [label, list]}
            {#if Array.isArray(list) && list.length}
              <p class="text-xs text-muted">{label}</p>
              <ul class="list-disc ml-5 text-xs">{#each list as item}<li>{item.text}{@render refList(item.refs)}</li>{/each}</ul>
            {/if}
          {/each}
        {/if}
      </section>
    {/each}
  {/if}
</section>
