<script lang="ts">
  import { onMount } from 'svelte'
  import AgentPlanCard from './AgentPlanCard.svelte'
  import Drawer from './Drawer.svelte'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // spec §11 计划页：版本链（v0…vn）、复查记录、「重新复查」。挂载时读一次链视图；数字照后端字符串显示。
  let { ticker, signalDate, currentPlanId }: { ticker: string; signalDate: string; currentPlanId: string } = $props()

  const SHADOW_TEXT: Record<string, string> = { pending: '待成交', expired: '到期未成交', open: '持仓中', closed: '已平仓' }
  const LIST_TEXT: Record<string, string> = { invalidation: '失效', review_when: '复查' }
  const VALID_OUTCOMES = ['maintain', 'revise', 'invalidate']

  let chain = $state<tl.Chain | null>(null)
  let error = $state('')
  let loading = $state(true)
  let open = $state<Record<number, boolean>>({})
  let recheck = $state<{ busy: boolean; text: string }>({ busy: false, text: '' })
  let callDrawer = $state<{ open: boolean; call: wb.AgentToolCall | null }>({ open: false, call: null })
  let callError = $state('')

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
  const active = $derived(chain ? tl.ACTIVE_STATES.includes(chain.state.state) : false)

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

  /** The last valid review that judged this version (its conditions belong to this version). */
  const reviewOf = (v: tl.Version) =>
    [...(chain?.reviews ?? [])].reverse().find(r => r.head_plan_id === v.plan_id && VALID_OUTCOMES.includes(r.outcome)) ?? null

  function versionAgent(v: tl.Version): tl.AgentView {
    const r = reviewOf(v)
    return {
      id: v.run.id, status: v.run.status === 'pass' ? 'pass' : 'ok', model: v.run.model,
      agent_version: v.run.agent_version, output: v.run.output, counter: v.run.counter, plan: v.plan,
      input_tokens: v.run.input_tokens, output_tokens: v.run.output_tokens, created_at: v.created_at,
      chain: {
        version_no: v.version_no, head_plan_id: chain!.head_plan_id,
        // 只有最新版带链状态（作废只作用于最新版）；旧版按入场期展示。
        state: v.is_head ? chain!.state.state : 'entry', mode: chain!.state.mode, basis: chain!.state.basis,
        latest_review: r ? { ...r, revision_status: (r.detail?.revision_status as string | undefined) ?? null,
                             conditions: r.conditions ?? [] } : null,
        cutoff_at: v.cutoff_at, diff: v.diff,
      },
    } as tl.AgentView
  }

  const versionLine = (v: tl.Version) => [
    tl.ORIGIN_TEXT[v.origin] ?? v.origin, `生成 ${fmtBeijing(v.created_at)}`, `截止 ${fmtBeijing(v.cutoff_at)}`,
    `入场 ${v.plan.entry_low}–${v.plan.entry_high}`, `止损 ${v.plan.stop}`, `T1 ${v.plan.target1}`,
    `有效期至 ${v.plan.valid_until}`, `影子 ${v.shadow ? SHADOW_TEXT[v.shadow.status] ?? v.shadow.status : '—'}`,
    ...(v.plan.status === 'invalid' ? [`已作废（${v.plan.invalid_reasons.join('、')}）`] : []),
    ...(v.is_head ? ['最新'] : []), ...(v.plan_id === currentPlanId ? ['当前查看'] : []),
  ].join(' · ')
  const diffLine = (v: tl.Version) => (v.diff ?? []).map(d =>
    `${tl.CHANGE_FIELD_TEXT[d.field] ?? d.field} ${tl.diffValueText(d.field, d.before)} → ${tl.diffValueText(d.field, d.after)}`).join('；')

  const reviewHead = (r: tl.PlanReview) => [
    r.session, tl.TRIGGER_TEXT[r.trigger] ?? r.trigger, tl.OUTCOME_TEXT[r.outcome] ?? r.outcome,
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

<section aria-label="版本链" class="border border-border rounded p-3 bg-surface text-sm space-y-3">
  {#if error}
    <h2 class="font-semibold">版本链</h2>
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if loading && !chain}
    <h2 class="font-semibold">版本链</h2>
    <p class="text-xs text-muted">加载中…</p>
  {:else if chain}
    {#if current && !current.is_head}
      <p class="text-sm text-amber-700"><span>这是第 {current.version_no} 版，最新为第 {chain.version_no} 版</span>
        <a class="text-accent underline ml-2" href={`#plan/${chain.head_plan_id}`}>查看最新版</a></p>
    {/if}
    <div class="flex flex-wrap items-center gap-2">
      <h2 class="font-semibold">版本链</h2>
      <span class="text-xs px-1.5 py-0.5 rounded bg-accent/10 text-accent">{tl.CHAIN_STATE_TEXT[chain.state.state] ?? chain.state.state}</span>
      <span class="text-xs text-muted">{chain.state.basis}</span>
      <button class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2 disabled:opacity-50"
              disabled={!active || recheck.busy}
              title={active ? '' : '只有入场期或持仓期的链可以重新复查'} onclick={runRecheck}>重新复查</button>
      {#if recheck.text}<span class="text-xs">{recheck.text}</span>{/if}
    </div>

    <ol aria-label="版本" class="space-y-2">
      {#each chain.versions as v (v.plan_id)}
        <li class="border-l-2 border-border pl-2 space-y-1">
          <p><button class="font-medium text-accent underline" aria-expanded={!!open[v.version_no]}
                     onclick={() => open[v.version_no] = !open[v.version_no]}>第 {v.version_no} 版</button>
            <span> · {versionLine(v)}</span></p>
          {#if v.diff?.length}<p class="text-xs">差异：{diffLine(v)}</p>{/if}
          {#if open[v.version_no]}
            <AgentPlanCard agent={versionAgent(v)} onCall={ref => showCall(v, ref)} />
          {/if}
        </li>
      {/each}
    </ol>
    {#if callError}<p class="text-xs text-red-600">{callError}</p>{/if}

    <h3 class="font-semibold">复查记录</h3>
    {#if chain.reviews.length}
      <ol aria-label="复查记录" class="space-y-2">
        {#each chain.reviews as r (r.id)}
          <li class="border-l-2 border-border pl-2 space-y-0.5">
            <p class="font-medium">{reviewHead(r)}</p>
            {#if reviewReason(r)}<p>{reviewReason(r)}</p>{/if}
            {#if r.outcome !== 'skipped'}
              <p class="text-xs text-muted">信号：{firedText(r)}</p>
              {#if r.conditions?.length}<p class="text-xs text-muted">条件：{conditionsText(r)}</p>{/if}
            {/if}
            {#if r.user_input_ids?.length}
              <p class="text-xs text-muted">给模型的新输入：{r.user_input_ids.map(id => `user:${id}`).join('、')}</p>
            {/if}
            {#if userRefs(r).length}<p class="text-xs text-muted">引用：{userRefs(r).join('、')}</p>{/if}
            {#if revisionStatus(r)}<p class="text-xs text-amber-700">修订未通过：{tl.revisionReasonText(revisionStatus(r)!)}</p>{/if}
          </li>
        {/each}
      </ol>
    {:else}
      <p class="text-xs text-muted">还没有复查记录</p>
    {/if}
  {/if}
</section>

<Drawer open={callDrawer.open} onclose={() => callDrawer = { open: false, call: null }}>
  {#if callDrawer.call}
    {@const c = callDrawer.call}
    <h2 class="font-semibold">工具调用 call:{c.seq}</h2>
    <p class="text-xs text-muted">工具 {c.tool} · 阶段 {c.phase} · {wb.dateTime(c.called_at)}</p>
    <p class="text-xs break-all">参数 {JSON.stringify(c.args)}</p>
    <p class="text-xs break-all">哈希 {c.result_sha256.slice(0, 8)}</p>
    <pre class="text-xs mt-2 whitespace-pre-wrap break-all">{JSON.stringify(c.result, null, 2)}</pre>
  {:else}
    <p class="text-sm text-muted">未找到该编号的工具调用</p>
  {/if}
</Drawer>
