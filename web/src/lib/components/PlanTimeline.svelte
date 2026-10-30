<script lang="ts">
  import { onMount } from 'svelte'
  import AgentPlanCard from './AgentPlanCard.svelte'
  import AgentReasoning from './AgentReasoning.svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import Drawer from './Drawer.svelte'
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
  let open = $state<Record<number, boolean>>({})
  let recheck = $state<{ busy: boolean; text: string }>({ busy: false, text: '' })
  let callDrawer = $state<{ open: boolean; call: wb.AgentToolCall | null }>({ open: false, call: null })
  let callError = $state('')
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

  const current = $derived(chain?.versions.find(v => v.plan_id === currentPlanId) ?? null)
  // R10: only entry / holding chains are rechecked; an exiting chain has issued its exit instruction.
  const active = $derived(chain ? tl.REVIEWABLE_STATES.includes(chain.state.state) : false)
  const exiting = $derived(chain?.state.state === 'exiting')

  async function runRecheck() {
    if (!chain || recheck.busy) return
    recheck = { busy: true, text: '复查中…' }
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
    try {
      const detail = await wb.getAgentRun(v.run.id)
      const seq = Number(ref.split(':')[1])
      callDrawer = { open: true, call: detail.tool_calls.find(c => c.seq === seq) ?? null }
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
      `执行 ${v.execution ? wb.executionText(v.execution.status, v.execution) || '—' : '—'}`,
      ...(defaulted ? [wb.DEFAULTS_APPLIED_TEXT] : []),
    ]
  }
  const versionLine = (v: tl.Version) => [
    tl.ORIGIN_TEXT[v.origin] ?? v.origin, `生成 ${fmtBeijing(v.created_at)}`, `截止 ${fmtBeijing(v.cutoff_at)}`,
    `入场 ${v.plan.entry_low}–${v.plan.entry_high}`, `止损 ${v.plan.stop}`, `T1 ${v.plan.target1}`,
    `有效期至 ${v.plan.valid_until}`, `影子 ${v.shadow ? SHADOW_TEXT[v.shadow.status] ?? v.shadow.status : '—'}`,
    ...executionParts(v),
    ...(v.plan.status === 'invalid' ? [`已作废（${v.plan.invalid_reasons.join('、')}）`] : []),
    ...(v.is_head ? ['最新'] : []), ...(v.plan_id === currentPlanId ? ['当前查看'] : []),
  ].join(' · ')
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

<section aria-label="版本链" class="border border-border rounded-sm p-3 bg-card text-sm space-y-3">
  {#if error}
    <h2 class="font-semibold">版本链</h2>
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if loading && !chain}
    <h2 class="font-semibold">版本链</h2>
    <p class="text-xs text-muted-foreground">加载中…</p>
  {:else if chain}
    {#if current && !current.is_head}
      <p class="text-sm text-amber-700"><span>这是第 {current.version_no} 版，最新为第 {chain.version_no} 版</span>
        <a class="text-primary underline ml-2" href={`#plan/${chain.head_plan_id}`}>查看最新版</a></p>
    {/if}
    <div class="flex flex-wrap items-center gap-2">
      <h2 class="font-semibold">版本链</h2>
      <span class="text-xs px-1.5 py-0.5 rounded-sm bg-primary/10 text-primary">{tl.CHAIN_STATE_TEXT[chain.state.state] ?? chain.state.state}</span>
      <ConceptTerm id={T.chainState}>链状态</ConceptTerm>
      <span class="text-xs text-muted-foreground">{chain.state.basis}</span>
      <button class="text-xs px-2 py-1 border border-border rounded-sm hover:bg-muted disabled:opacity-50"
              disabled={!active || recheck.busy}
              title={exiting ? wb.CHAIN_EXITING_TEXT : active ? '' : '只有入场期或持仓期的链可以重新复查'} onclick={runRecheck}>重新复查</button>
      {#if recheck.text}<span class="text-xs">{recheck.text}</span>{/if}
    </div>

    {#if chain.retriggers?.length}
      <p class="text-xs text-muted-foreground">并入的单元：{chain.retriggers.map(r => `${r.unit_signal_date}（${r.rule_ids.map(wb.ruleLabel).join('、')}）`).join('；')}</p>
    {/if}

    <ol aria-label="版本" class="space-y-2">
      {#each chain.versions as v (v.plan_id)}
        <li class="border-l-2 border-border pl-2 space-y-1">
          <p><button class="font-medium text-primary underline" aria-expanded={!!open[v.version_no]}
                     onclick={() => open[v.version_no] = !open[v.version_no]}>第 {v.version_no} 版</button>
            <span> · {versionLine(v)}</span>
            <span class="text-xs"><ConceptTerm id={T.origin}>来源</ConceptTerm> <ConceptTerm id={T.shadow}>影子</ConceptTerm></span></p>
          {#if v.diff?.length}<p class="text-xs">差异：{diffLine(v)}</p>{/if}
          {#if open[v.version_no]}
            <AgentPlanCard agent={versionAgent(v)} onCall={ref => showCall(v, ref)} />
          {/if}
        </li>
      {/each}
    </ol>
    {#if callError}<p class="text-xs text-red-600">{callError}</p>{/if}

    {#if chain.holding_status?.length}
      <h3 class="font-semibold">持仓状态</h3>
      <div class="overflow-x-auto">
        <table aria-label="持仓状态" class="text-xs w-full min-w-[640px]">
          <thead><tr class="text-left text-muted-foreground">
            <th>日期</th><th>持有</th><th>收盘</th><th>止损</th><th>距止损</th><th>距 T1</th><th>现</th><th>指令</th><th>理由</th>
          </tr></thead>
          <tbody>
            {#each chain.holding_status as h, i (`${h.session}|${i}`)}
              <tr class="align-top border-t border-border" data-instruction={h.instruction}>
                <td class="whitespace-nowrap">{h.session ?? '—'}</td>
                <td>{h.held_sessions ?? '—'}/{h.max_hold_sessions ?? '—'} 天</td>
                <td>{h.last_close ?? '—'}</td>
                <td>{h.stop ?? '—'}{h.stop_mode ? `（${wb.STOP_MODE_TEXT[h.stop_mode] ?? h.stop_mode}）` : ''}</td>
                <td>{wb.signedPct(h.to_stop_pct)}</td>
                <td>{h.t1_reached ? '已触 T1' : wb.signedPct(h.to_t1_pct)}</td>
                <td>{h.r_now == null ? '—' : `${Number(h.r_now) < 0 ? '−' : '+'}${Math.abs(Number(h.r_now)).toFixed(1)}R`}{h.reached_1r ? '（已到 1R，时间止损解除）' : ''}</td>
                <td class={h.instruction === 'exit' ? 'text-red-600 font-semibold' : h.instruction === 'sell_half' ? 'text-orange-600 font-semibold' : ''}>{wb.INSTRUCTION_TEXT[h.instruction] ?? h.instruction}{h.exit_reason ? `（${wb.EXIT_REASON_TEXT[h.exit_reason] ?? h.exit_reason}）` : ''}</td>
                <td>{h.reason ?? ''}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}

    <h3 class="font-semibold">复查记录</h3>
    {#if chain.reviews.length}
      <ol aria-label="复查记录" class="space-y-2">
        {#each chain.reviews as r (r.id)}
          <li class="border-l-2 border-border pl-2 space-y-0.5">
            <p class="font-medium">{reviewHead(r)} <span class="text-xs font-normal"><ConceptTerm id={T.outcome}>复查结论</ConceptTerm></span></p>
            {#if isRetrigger(r)}<p class="text-xs text-amber-700">{tl.retriggerText(r, chain?.retriggers, wb.ruleLabel)}</p>{/if}
            {#if reviewReason(r)}<p>{reviewReason(r)}</p>{/if}
            {#if r.outcome !== 'skipped'}
              <p class="text-xs text-muted-foreground">信号：{firedText(r)} <ConceptTerm id={T.signals}>信号说明</ConceptTerm></p>
              {#if r.conditions?.length}<p class="text-xs text-muted-foreground">条件：{conditionsText(r)} <ConceptTerm id={T.conditions}>条件说明</ConceptTerm></p>{/if}
            {/if}
            {#if r.user_input_ids?.length}
              <p class="text-xs text-muted-foreground">给模型的新输入：{r.user_input_ids.map(id => `user:${id}`).join('、')} <ConceptTerm id={T.userInput}>用户输入</ConceptTerm></p>
            {/if}
            {#if userRefs(r).length}<p class="text-xs text-muted-foreground">引用：{userRefs(r).join('、')}</p>{/if}
            {#if revisionStatus(r)}<p class="text-xs text-amber-700">修订未通过：{tl.revisionReasonText(revisionStatus(r)!)}</p>{/if}
            {#if r.review_agent_run_id || r.revision_agent_run_id}
              <p class="text-xs flex flex-wrap gap-x-3">
                {#if r.review_agent_run_id}
                  <button type="button" class="text-primary underline" aria-expanded={!!reasoningOpen[`${r.id}|review`]}
                          onclick={() => reasoningOpen[`${r.id}|review`] = !reasoningOpen[`${r.id}|review`]}>看复查推理</button>
                {/if}
                {#if r.revision_agent_run_id}
                  <button type="button" class="text-primary underline" aria-expanded={!!reasoningOpen[`${r.id}|revision`]}
                          onclick={() => reasoningOpen[`${r.id}|revision`] = !reasoningOpen[`${r.id}|revision`]}>看修订推理</button>
                {/if}
              </p>
              {#if r.review_agent_run_id && reasoningOpen[`${r.id}|review`]}<AgentReasoning runId={r.review_agent_run_id} />{/if}
              {#if r.revision_agent_run_id && reasoningOpen[`${r.id}|revision`]}<AgentReasoning runId={r.revision_agent_run_id} />{/if}
            {/if}
          </li>
        {/each}
      </ol>
    {:else}
      <p class="text-xs text-muted-foreground">还没有复查记录</p>
    {/if}
  {/if}
</section>

<Drawer open={callDrawer.open} onclose={() => callDrawer = { open: false, call: null }}>
  {#if callDrawer.call}
    {@const c = callDrawer.call}
    <h2 class="font-semibold">工具调用 call:{c.seq}</h2>
    <p class="text-xs text-muted-foreground">工具 {c.tool} · 阶段 {c.phase} · {wb.dateTime(c.called_at)}</p>
    <p class="text-xs break-all">参数 {JSON.stringify(c.args)}</p>
    <p class="text-xs break-all">哈希 {c.result_sha256.slice(0, 8)}</p>
    <pre class="text-xs mt-2 whitespace-pre-wrap break-all">{JSON.stringify(c.result, null, 2)}</pre>
  {:else}
    <p class="text-sm text-muted-foreground">未找到该编号的工具调用</p>
  {/if}
</Drawer>
