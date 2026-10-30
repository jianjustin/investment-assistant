<script lang="ts">
  import { onMount } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import * as Card from '$lib/ui/card/index'
  import { DataTable } from '$lib/ui/data-table/index'
  import type { Column } from '$lib/ui/data-table/types'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import MetricValue from '$lib/ui/domain/MetricValue.svelte'
  import PlanLevels from '$lib/ui/domain/PlanLevels.svelte'
  import Section from '$lib/ui/domain/Section.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import VersionChip from '$lib/ui/domain/VersionChip.svelte'
  import * as Sheet from '$lib/ui/sheet/index'
  import AgentPlanCard from './AgentPlanCard.svelte'
  import AgentReasoning from './AgentReasoning.svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import { ATTACH } from '../knowledge'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // spec §11 计划页：版本链（v0…vn）、复查记录、「重新复查」。挂载时读一次链视图；数字照后端字符串显示。
  let { ticker, signalDate, currentPlanId }: { ticker: string; signalDate: string; currentPlanId: string } = $props()

  const SHADOW_TEXT: Record<string, string> = { pending: '待成交', expired: '到期未成交', open: '持仓中', closed: '已平仓', voided: '开盘作废' }
  const LIST_TEXT: Record<string, string> = { invalidation: '失效', review_when: '复查' }

  let chain = $state<tl.Chain | null>(null)
  let error = $state('')
  let loading = $state(true)
  let expanded = $state(new Set<string | number>())          // plan ids whose Agent card is open
  let recheck = $state<{ busy: boolean; text: string }>({ busy: false, text: '' })
  let recheckSince = $state<number | null>(null)
  let tick = $state(Date.now())
  let callOpen = $state(false)
  let callDrawer = $state<{ seq: number | null; call: wb.AgentToolCall | null }>({ seq: null, call: null })
  let callError = $state('')
  // The sheet is opened from code, so there is no trigger to give focus back to: remember the call button that opened it.
  let opener: HTMLElement | null = null
  function restoreFocus(event: Event) {
    event.preventDefault()
    opener?.focus()
    opener = null
  }
  let reasoningOpen = $state<Record<string, boolean>>({})
  const T = ATTACH.timeline

  async function load() {
    loading = true
    try {
      chain = await api.getChain(ticker, signalDate)
      error = ''
    } catch (e) {
      error = e instanceof wb.WorkbenchError && e.status === 404 ? '这一单元没有 Agent 版本链' : wb.describeError(e)
    } finally {
      loading = false
    }
  }
  onMount(() => { void load() })

  // How long the recheck has been running: only ticks while it runs.
  $effect(() => {
    if (!recheck.busy) return
    tick = Date.now()
    const timer = setInterval(() => { tick = Date.now() }, 1000)
    return () => clearInterval(timer)
  })
  const waited = $derived(recheckSince == null ? 0 : Math.max(0, Math.floor((tick - recheckSince) / 1000)))

  const current = $derived(chain?.versions.find(v => v.plan_id === currentPlanId) ?? null)
  // R10: only entry / holding chains are rechecked; an exiting chain has issued its exit instruction.
  const active = $derived(chain ? tl.REVIEWABLE_STATES.includes(chain.state.state) : false)
  const exiting = $derived(chain?.state.state === 'exiting')

  async function runRecheck() {
    if (!chain || recheck.busy) return
    recheck = { busy: true, text: '复查中…' }
    recheckSince = Date.now()
    try {
      const started = await api.recheckChain(ticker, signalDate)
      const done = await api.pollRun(started.run_id, { timeoutMs: tl.RECHECK_POLL_MS })
      recheck = { busy: false, text: tl.recheckDoneText(done) }
      if (done.status === 'done') await load()
    } catch (e) {
      // 轮询超时不是失败：后台仍在复查，按钮保持不可点，提示稍后刷新。
      recheck = tl.isRunTimeout(e) ? { busy: true, text: tl.RECHECK_PENDING_TEXT }
        : { busy: false, text: e instanceof wb.WorkbenchError && e.status === 409
            ? `不能重新复查：${tl.recheckConflictText(e.message)}` : wb.describeError(e) }
    }
  }

  async function showCall(v: tl.Version, ref: string) {
    callError = ''
    const active = document.activeElement
    opener = active instanceof HTMLElement && active !== document.body ? active : null
    try {
      const detail = await wb.getAgentRun(v.run.id)
      const seq = Number(ref.split(':')[1])
      callDrawer = { seq, call: detail.tool_calls.find(c => c.seq === seq) ?? null }
      callOpen = true
    } catch (e) {
      callError = wb.describeError(e)
    }
  }

  const versionAgent = (v: tl.Version): tl.AgentView => tl.versionAgentView(chain!, v)

  // v2.9 §10.2: 入场类型、最长持有、执行状态三列；agent-2 版本没有执行字段，按默认值显示并注明（§5.5）
  const executionParts = (v: tl.Version) => {
    const defaulted = v.plan.entry_type == null
    return [
      `入场类型 ${wb.ENTRY_TYPE_TEXT[v.plan.entry_type ?? 'zone_limit']}`,
      `最长持有 ${v.plan.max_hold_sessions ?? 10} 个交易日`,
      `执行 ${v.execution ? wb.executionText(v.execution.status, v.execution) || '—' : '—'}`,   // 文案由测试钉住（含「—」）
      ...(defaulted ? [wb.DEFAULTS_APPLIED_TEXT] : []),
    ]
  }
  const num = (v: unknown) => (v == null || v === '' ? null : Number(v))
  const stateOf = (v: tl.Version) => [
    v.plan.status === 'invalid' ? `已作废（${v.plan.invalid_reasons.join('、')}）` : '有效',
    ...(v.plan_id === currentPlanId ? ['当前查看'] : []),
  ].join(' · ')

  const versionColumns: Column<tl.Version>[] = [
    { key: 'version', header: '版本', cell: versionCell },
    { key: 'origin', header: '来源', cell: originCell },
    { key: 'times', header: '时点', cell: timesCell },
    { key: 'levels', header: '价位', cell: levelsCell },
    { key: 'valid', header: '有效期', value: v => `有效期至 ${v.plan.valid_until}` },
    { key: 'shadow', header: '影子', cell: shadowCell },
    { key: 'execution', header: '入场与执行', value: v => executionParts(v).join(' · ') },
    { key: 'diff', header: '相对上版', value: v => (v.diff?.length ? `差异：${diffLine(v)}` : '无差异') },
    { key: 'state', header: '状态', value: v => stateOf(v) },
  ]
  type Hold = NonNullable<tl.Chain['holding_status']>[number]
  const holdColumns: Column<Hold>[] = [
    { key: 'session', header: '日期', value: h => h.session ?? '', cell: holdSession },
    { key: 'held', header: '持有', cell: holdHeld },
    { key: 'close', header: '收盘', align: 'num', cell: holdClose },
    { key: 'stop', header: '止损', align: 'num', cell: holdStop },
    { key: 'to_stop', header: '距止损', align: 'num', cell: holdToStop },
    { key: 'to_t1', header: '距 T1', align: 'num', cell: holdToT1 },
    { key: 'r', header: '现', align: 'num', cell: holdR },
    { key: 'instruction', header: '指令', cell: holdInstruction },
    { key: 'reason', header: '理由', value: h => h.reason ?? '' },
  ]
  const diffLine = (v: tl.Version) => (v.diff ?? []).map(d =>
    `${tl.CHANGE_FIELD_TEXT[d.field] ?? d.field} ${tl.diffValueText(d.field, d.before)} → ${tl.diffValueText(d.field, d.after)}`).join('；')

  // 持仓期作废在 timeline-2 下是退出指令（spec §10.2），不再叫「作废」
  const outcomeText = (r: tl.PlanReview) => {
    if (!tl.isExitReview(r)) return tl.OUTCOME_TEXT[r.outcome] ?? r.outcome
    const why = r.detail?.exit_reason as string | undefined
    return why ? `退出指令（${wb.EXIT_REASON_TEXT[why] ?? why}）` : '退出指令'
  }
  const isRetrigger = (r: tl.PlanReview) => r.detail?.via === 'retrigger'
  const reviewHead = (r: tl.PlanReview) => [
    r.session, tl.TRIGGER_TEXT[r.trigger] ?? r.trigger, outcomeText(r),
    ...(r.decided_by ? [tl.DECIDED_BY_TEXT[r.decided_by] ?? r.decided_by] : []),
    `第 ${r.head_version_no ?? '?'} 版${r.new_version_no != null ? ` → 第 ${r.new_version_no} 版` : ''}`,
    fmtBeijing(r.created_at),
  ].join(' · ')
  // skipped / error 行的 reason 是原因代码。
  const reviewReason = (r: tl.PlanReview) =>
    r.outcome === 'skipped' || r.outcome === 'error' ? (wb.AGENT_REASON_TEXT[r.reason ?? ''] ?? r.reason ?? '') : (r.reason ?? '')
  const firedText = (r: tl.PlanReview) =>
    (r.signals ?? []).filter(s => s.fired).map(s => tl.SIGNAL_TEXT[s.kind] ?? s.kind).join('、') || '无触发'
  const conditionsText = (r: tl.PlanReview) => (r.conditions ?? []).map(c =>
    `${LIST_TEXT[c.list] ?? c.list} ${tl.conditionText(c.kind, c.params)}：${tl.CONDITION_RESULT_TEXT[c.result] ?? c.result}`).join('；')
  const userRefs = (r: tl.PlanReview) => (r.refs ?? []).filter(ref => ref.startsWith('user:'))
  const revisionStatus = (r: tl.PlanReview) => (r.detail?.revision_status as string | undefined) ?? null
</script>

{#snippet versionCell(v: tl.Version)}
  <VersionChip version={v.version_no} latest={chain?.version_no ?? null} latestHref={chain ? `#plan/${chain.head_plan_id}` : undefined} />
{/snippet}
{#snippet originCell(v: tl.Version)}
  {tl.ORIGIN_TEXT[v.origin] ?? v.origin} <span class="text-xs"><ConceptTerm id={T.origin}>来源</ConceptTerm></span>
{/snippet}
{#snippet timesCell(v: tl.Version)}
  <span class="block">生成 {fmtBeijing(v.created_at)}</span><span class="block">截止 {fmtBeijing(v.cutoff_at)}</span>
{/snippet}
{#snippet levelsCell(v: tl.Version)}
  <PlanLevels low={num(v.plan.entry_low)} high={num(v.plan.entry_high)} stop={num(v.plan.stop)} target1={num(v.plan.target1)} />
{/snippet}
{#snippet shadowCell(v: tl.Version)}
  影子 {v.shadow ? SHADOW_TEXT[v.shadow.status] ?? v.shadow.status : '—'} <span class="text-xs"><ConceptTerm id={T.shadow}>影子</ConceptTerm></span>
{/snippet}
{#snippet expandable(v: tl.Version)}
  <AgentPlanCard agent={versionAgent(v)} onCall={ref => showCall(v, ref)} />
{/snippet}

{#snippet pct(value: number | string | null | undefined)}
  {#if value == null || value === ''}<StatusPill domain="block" value="not_computed" />{:else}{wb.signedPct(value)}{/if}
{/snippet}
{#snippet holdSession(h: Hold)}<span class="whitespace-nowrap">{h.session}</span>{/snippet}
{#snippet holdHeld(h: Hold)}{h.held_sessions ?? '?'}/{h.max_hold_sessions ?? '?'} 天{/snippet}
{#snippet holdClose(h: Hold)}<MetricValue value={num(h.last_close)} />{/snippet}
{#snippet holdStop(h: Hold)}<MetricValue value={num(h.stop)} />{h.stop_mode ? `（${wb.STOP_MODE_TEXT[h.stop_mode] ?? h.stop_mode}）` : ''}{/snippet}
{#snippet holdToStop(h: Hold)}{@render pct(h.to_stop_pct)}{/snippet}
{#snippet holdToT1(h: Hold)}{#if h.t1_reached}已触 T1{:else}{@render pct(h.to_t1_pct)}{/if}{/snippet}
{#snippet holdR(h: Hold)}
  {#if h.r_now == null}<StatusPill domain="block" value="not_computed" />{:else}{`${Number(h.r_now) < 0 ? '−' : '+'}${Math.abs(Number(h.r_now)).toFixed(1)}R`}{/if}{h.reached_1r ? '（已到 1R，时间止损解除）' : ''}
{/snippet}
{#snippet holdInstruction(h: Hold)}
  <StatusPill domain="instruction" value={h.instruction} text={`${wb.INSTRUCTION_TEXT[h.instruction] ?? h.instruction}${h.exit_reason ? `（${wb.EXIT_REASON_TEXT[h.exit_reason] ?? h.exit_reason}）` : ''}`} />
{/snippet}

<Card.Root size="sm" role="region" aria-label="版本链" class="gap-3 px-3 text-sm">
  {#if error}
    <h2 class="text-base font-medium">版本链</h2>
    <DataBlock state="error" message={error} />
  {:else if loading && !chain}
    <h2 class="text-base font-medium">版本链</h2>
    <DataBlock state="loading" skeleton="table" />
  {:else if chain}
    {#if current && !current.is_head}
      <Alert variant="warn" role="status"><AlertDescription><span>这是第 {current.version_no} 版，最新为第 {chain.version_no} 版</span>
        <a class="ml-2 text-primary underline" href={`#plan/${chain.head_plan_id}`}>查看最新版</a></AlertDescription></Alert>
    {/if}
    <div class="flex flex-wrap items-center gap-2">
      <h2 class="text-base font-medium">版本链</h2>
      <StatusPill domain="chain" value={chain.state.state} />
      <ConceptTerm id={T.chainState}>链状态</ConceptTerm>
      <span class="text-xs text-muted-foreground">{chain.state.basis}</span>
      <Button size="sm" disabled={!active} busy={recheck.busy}
              title={exiting ? wb.CHAIN_EXITING_TEXT : active ? '' : '只有入场期或持仓期的链可以重新复查'} onclick={runRecheck}>重新复查</Button>
      {#if recheck.busy}
        <StatusPill domain="run" value="running" text={recheck.text} />
        <span class="text-xs text-muted-foreground">已等待 {waited} 秒</span>
      {:else if recheck.text}
        <span class="text-xs">{recheck.text}</span>
      {/if}
    </div>

    {#if chain.retriggers?.length}
      <p class="text-xs text-muted-foreground">并入的单元：{chain.retriggers.map(r => `${r.unit_signal_date}（${r.rule_ids.map(wb.ruleLabel).join('、')}）`).join('；')}</p>
    {/if}

    <DataTable columns={versionColumns} rows={chain.versions} rowKey={v => v.plan_id} cards="narrow" bind:expanded {expandable} sticky={false} ariaLabel="版本"
               expandLabel={v => `第 ${v.version_no} 版`}
               muted={v => v.plan.status === 'invalid'} />
    {#if callError}<p class="text-xs text-destructive">{callError}</p>{/if}

    {#if chain.holding_status?.length}
      <Section level={3} title="持仓状态">
        <DataTable columns={holdColumns} rows={chain.holding_status} rowKey={(h) => `${h.session}|${chain!.holding_status!.indexOf(h)}`} sticky={false}
                   cards="narrow" ariaLabel="持仓状态" />
      </Section>
    {/if}

    <h3 class="text-base font-medium">复查记录</h3>
    {#if chain.reviews.length}
      <ol aria-label="复查记录" class="grid gap-2">
        {#each chain.reviews as r (r.id)}
          <li class="grid gap-0.5 border-l-2 border-border pl-2">
            <p class="font-medium">{reviewHead(r)} <span class="text-xs font-normal"><ConceptTerm id={T.outcome}>复查结论</ConceptTerm></span></p>
            {#if isRetrigger(r)}<p class="text-xs text-warn">{tl.retriggerText(r, chain?.retriggers, wb.ruleLabel)}</p>{/if}
            {#if reviewReason(r)}<p>{reviewReason(r)}</p>{/if}
            {#if r.outcome !== 'skipped'}
              <p class="text-xs text-muted-foreground">信号：{firedText(r)} <ConceptTerm id={T.signals}>信号说明</ConceptTerm></p>
              {#if r.conditions?.length}<p class="text-xs text-muted-foreground">条件：{conditionsText(r)} <ConceptTerm id={T.conditions}>条件说明</ConceptTerm></p>{/if}
            {/if}
            {#if r.user_input_ids?.length}
              <p class="text-xs text-muted-foreground">给模型的新输入：{r.user_input_ids.map(id => `user:${id}`).join('、')} <ConceptTerm id={T.userInput}>用户输入</ConceptTerm></p>
            {/if}
            {#if userRefs(r).length}<p class="text-xs text-muted-foreground">引用：{userRefs(r).join('、')}</p>{/if}
            {#if revisionStatus(r)}<p class="text-xs text-warn">修订未通过：{tl.revisionReasonText(revisionStatus(r)!)}</p>{/if}
            {#if r.review_agent_run_id || r.revision_agent_run_id}
              <p class="flex flex-wrap gap-x-3 text-xs">
                {#if r.review_agent_run_id}
                  <Button variant="link" size="sm" class="text-xs" aria-expanded={!!reasoningOpen[`${r.id}|review`]}
                          onclick={() => reasoningOpen[`${r.id}|review`] = !reasoningOpen[`${r.id}|review`]}>看复查推理</Button>
                {/if}
                {#if r.revision_agent_run_id}
                  <Button variant="link" size="sm" class="text-xs" aria-expanded={!!reasoningOpen[`${r.id}|revision`]}
                          onclick={() => reasoningOpen[`${r.id}|revision`] = !reasoningOpen[`${r.id}|revision`]}>看修订推理</Button>
                {/if}
              </p>
              {#if r.review_agent_run_id && reasoningOpen[`${r.id}|review`]}<AgentReasoning runId={r.review_agent_run_id} />{/if}
              {#if r.revision_agent_run_id && reasoningOpen[`${r.id}|revision`]}<AgentReasoning runId={r.revision_agent_run_id} />{/if}
            {/if}
          </li>
        {/each}
      </ol>
    {:else}
      <DataBlock state="empty" message="还没有复查记录" />
    {/if}
  {/if}
</Card.Root>

<Sheet.Root bind:open={callOpen}>
  <Sheet.Content side="right" width="sm" onCloseAutoFocus={restoreFocus}>
    <Sheet.Header>
      <Sheet.Title>工具调用 call:{callDrawer.seq}</Sheet.Title>
      <Sheet.Description class="sr-only">这次 Agent 运行里的一次工具调用</Sheet.Description>
    </Sheet.Header>
    <div class="grid gap-1 px-4 pb-4">
      {#if callDrawer.call}
        {@const c = callDrawer.call}
        <p class="text-xs text-muted-foreground">工具 {c.tool} · 阶段 {c.phase} · {wb.dateTime(c.called_at)}</p>
        <p class="break-all text-xs">参数 {JSON.stringify(c.args)}</p>
        <p class="break-all text-xs">哈希 {c.result_sha256.slice(0, 8)}</p>
        <pre class="mt-2 whitespace-pre-wrap break-all text-xs">{JSON.stringify(c.result, null, 2)}</pre>
      {:else}
        <p class="text-sm text-muted-foreground">未找到该编号的工具调用</p>
      {/if}
    </div>
  </Sheet.Content>
</Sheet.Root>
