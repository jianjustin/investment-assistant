<script lang="ts">
  import { Button } from '$lib/ui/button/index'
  import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '$lib/ui/collapsible/index'
  import ConfirmDialog from '$lib/ui/confirm-dialog/ConfirmDialog.svelte'
  import CalcVersion from '$lib/ui/domain/CalcVersion.svelte'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import PageHeader from '$lib/ui/domain/PageHeader.svelte'
  import AgentReasoning from '../lib/components/AgentReasoning.svelte'
  import ConceptTerm from '../lib/components/ConceptTerm.svelte'
  import DiscussButton from '../lib/components/DiscussButton.svelte'
  import PlanDerivation from '../lib/components/PlanDerivation.svelte'
  import PlanNotes from '../lib/components/PlanNotes.svelte'
  import PlanTimeline from '../lib/components/PlanTimeline.svelte'
  import UserInputs from '../lib/components/UserInputs.svelte'
  import * as api from '../lib/api'
  import type { Derivation } from '../lib/derivation'
  import { ATTACH } from '../lib/knowledge'
  import { growthError, truncate } from '../lib/growth'
  import type { DiscussionListItem } from '../lib/growth'
  import { fmtBeijing } from '../lib/format'
  import { AGENT_REASON_TEXT, describeError, getPlanNotes, newRequestId, postPlanNote } from '../lib/workbench'
  import type { PlanNote } from '../lib/workbench'

  // 整页渲染 PlanDerivation（spec 2026-10-27 §10）。标题取推导里的标的与日期，
  // 所以页面自己再请求一次；取不到（404/400/503）时退化为 id，错误文案交给组件呈现，不白屏。
  // agent-2 计划另显示版本链、复查记录与「我的补充」（v2.5 spec §11）。
  // agent-1 计划没有版本链与计划卡，另给一段「看推理过程」，按生成它的运行取推理视图（v2.6 spec §8.5）。
  let { sub }: { sub: string } = $props()
  let title = $state('')
  let calcVersion = $state('')
  let ticker = $state('')
  let unit = $state<{ ticker: string; signal_date: string } | null>(null)
  let legacyRunId = $state<string | null>(null)
  let reasoningOpen = $state(false)
  // v2.7 §8.1：这个计划已有的讨论；读不到（如迁移 027 未执行）只影响这一段
  let discussions = $state<DiscussionListItem[] | null>(null)
  let discussionsError = $state('')
  // v2.8 D26：这个单元最近一次 Agent 运行（按 mode）是 max_attempts 或 error 时，给「重新运行 Agent」
  type RerunRow = { mode: 'propose' | 'interpret'; status: string; reason: string | null }
  let rerunUnit = $state<{ ticker: string; signal_date: string } | null>(null)
  let rerunRows = $state<RerunRow[]>([])
  let rerunBusy = $state<Record<string, boolean>>({})
  let rerunText = $state<Record<string, string>>({})
  let rerunDone = $state<Record<string, boolean>>({})
  let rerunAsk = $state<RerunRow | null>(null)          // the row waiting for the confirm dialog
  let rerunOpen = $state(false)
  const rerunIds: Record<string, string> = {}
  const RERUN_MODE_TEXT: Record<string, string> = { propose: 'Agent 建议', interpret: 'Agent 简报解读' }
  const RERUN_STATUS_TEXT: Record<string, string> = { error: '出错', skipped: '跳过' }
  // v2.9 §6.5：备注作用于一条链（agent-2 / agent-3 计划）或一份非链计划（规则基线 / 自定）；agent-1 不挂备注
  type NoteTarget = { ticker: string; chain_signal_date: string } | { plan_id: string }
  let noteTarget = $state<NoteTarget | null>(null)
  let notes = $state<PlanNote[] | null>(null)
  let notesError = $state('')
  let noteSeq = 0     // bumps whenever the page's plan changes: a late notes read of the old plan is dropped
  const isChainVersion = (v: string | null | undefined) => v === 'agent-2' || v === 'agent-3'
  const noteQuery = (t: NoteTarget) => ('plan_id' in t ? { plan_id: t.plan_id } : t)

  async function loadNotes(target: NoteTarget, alive: () => boolean) {
    try {
      const res = await getPlanNotes(noteQuery(target))
      if (!alive()) return
      notes = Array.isArray(res?.notes) ? res.notes : []
      notesError = ''
    } catch (e) {
      if (alive()) { notes = null; notesError = describeError(e) }
    }
  }
  async function addNote(body: string, requestId: string) {
    const target = noteTarget
    if (!target) return
    const seq = noteSeq
    await postPlanNote({ request_id: requestId, body, ...target })
    await loadNotes(target, () => noteSeq === seq)
  }

  $effect(() => {
    const id = sub
    let alive = true
    unit = null
    ticker = ''
    calcVersion = ''
    legacyRunId = null
    reasoningOpen = false
    discussions = null
    discussionsError = ''
    rerunUnit = null
    rerunRows = []
    rerunText = {}
    rerunDone = {}
    noteTarget = null
    notes = null
    notesError = ''
    const seq = ++noteSeq
    void api.getDiscussions({ plan_id: id })
      .then(res => { if (alive) discussions = Array.isArray(res?.discussions) ? res.discussions : [] })
      .catch((e: unknown) => { if (alive) discussionsError = growthError(e) })
    void api.getPlanDerivation(id)
      .then((d: Derivation) => {
        if (!alive) return
        title = `${d.plan.ticker ?? '—'} · ${d.plan.signal_date ?? '—'}`
        ticker = d.plan.ticker ?? ''
        calcVersion = d.plan.plan_version ?? ''
        unit = isChainVersion(d.plan.plan_version) && d.plan.ticker && d.plan.signal_date
          ? { ticker: d.plan.ticker, signal_date: d.plan.signal_date } : null
        const target: NoteTarget | null = unit ? { ticker: unit.ticker, chain_signal_date: unit.signal_date }
          : d.plan.plan_version === 'agent-1' ? null : { plan_id: id }
        noteTarget = target
        if (target) void loadNotes(target, () => alive && noteSeq === seq)
        if (d.plan.ticker && d.plan.signal_date) {
          const found = { ticker: d.plan.ticker, signal_date: d.plan.signal_date }
          void api.getAgentRuns(found.signal_date).then(res => {
            if (!alive) return
            rerunUnit = found
            rerunRows = rerunnable(res?.runs ?? [], found)
          }).catch(() => { /* the entry is optional: a failing list just hides it */ })
        }
        const runId = d.inputs.agent_run?.id
        legacyRunId = d.plan.plan_version === 'agent-1' && typeof runId === 'string' ? runId : null
      })
      .catch(() => { if (alive) title = id })
    return () => { alive = false }
  })

  /** The latest run of each mode for the unit; only propose / interpret that ended in max_attempts or error qualify. */
  function rerunnable(runs: api.AgentRunRow[], unit: { ticker: string; signal_date: string }): RerunRow[] {
    const rows: RerunRow[] = []
    for (const mode of ['propose', 'interpret'] as const) {
      const mine = runs.filter(r => r.ticker === unit.ticker && r.signal_date === unit.signal_date && r.mode === mode)
      const last = mine[mine.length - 1]
      if (last && (last.status === 'error' || (last.status === 'skipped' && last.reason === 'max_attempts')))
        rows.push({ mode, status: last.status, reason: last.reason })
    }
    return rows
  }

  async function rerun(row: RerunRow) {
    if (!rerunUnit || rerunBusy[row.mode]) return
    rerunBusy[row.mode] = true
    rerunText[row.mode] = ''
    rerunIds[row.mode] ??= newRequestId()   // 失败后重试沿用同一个 request_id
    try {
      const res = await api.rerunAgent({
        ticker: rerunUnit.ticker, signal_date: rerunUnit.signal_date, mode: row.mode, request_id: rerunIds[row.mode], origin: 'plan_page',
      })
      delete rerunIds[row.mode]
      rerunDone[row.mode] = true
      rerunText[row.mode] = res.run_id ? '已重置尝试次数，并已重新运行' : '已重置尝试次数，同一交易日的续跑或手动运行时执行'
    } catch (e) {
      rerunText[row.mode] = e instanceof api.ApiError && e.status === 409
        ? (e.code === 'not_needed' ? '这个单元不需要重跑' : e.message) : describeError(e)
    } finally {
      rerunBusy[row.mode] = false
      rerunOpen = false
    }
  }

  // 有历史就后退；没有历史（直链打开）时不拦截，沿 href 落到「今日」。
  function goBack(e: MouseEvent) {
    if (history.length > 1) { e.preventDefault(); history.back() }
  }
</script>

<div class="grid gap-4">
  <PageHeader level={1} title={title || '加载中…'}>
    {#snippet meta()}
      <a href="#today" onclick={goBack} class="text-primary underline">返回</a>
      {#if ticker}<a href={`#instrument/${encodeURIComponent(ticker)}`} class="text-primary underline">标的页</a>{/if}
      {#if calcVersion}<CalcVersion version={calcVersion} />{/if}
    {/snippet}
    {#snippet actions()}
      {#if ticker}<DiscussButton context={{ kind: 'plan', plan_id: sub }} />{/if}
    {/snippet}
  </PageHeader>
  {#key sub}
    {#if rerunRows.length}
      <section aria-label="Agent 重新运行" class="grid gap-1 text-sm">
        {#each rerunRows as row (row.mode)}
          <p class="flex flex-wrap items-center gap-2">
            <span>{RERUN_MODE_TEXT[row.mode]}：最近一次{RERUN_STATUS_TEXT[row.status] ?? row.status}{row.reason ? `（${AGENT_REASON_TEXT[row.reason] ?? row.reason}）` : ''}</span>
            {#if !rerunDone[row.mode]}
              <Button size="sm" busy={rerunBusy[row.mode]} onclick={() => { rerunAsk = row; rerunOpen = true }}>重新运行 Agent</Button>
            {/if}
            {#if rerunText[row.mode]}<span class="text-xs {rerunDone[row.mode] ? 'text-muted-foreground' : 'text-destructive'}">{rerunText[row.mode]}</span>{/if}
          </p>
        {/each}
      </section>
    {/if}
    {#if unit}
      <PlanTimeline ticker={unit.ticker} signalDate={unit.signal_date} currentPlanId={sub} />
    {/if}
    {#if legacyRunId}
      <section aria-label="Agent 推理" class="grid gap-2">
        <p class="text-xs text-warn">agent-1（旧版，不参与复查） <ConceptTerm id={ATTACH.agentCard.legacy}>旧版说明</ConceptTerm></p>
        <Collapsible bind:open={reasoningOpen} class="grid gap-2">
          <div>
            <CollapsibleTrigger>
              {#snippet child({ props })}<Button variant="link" size="sm" class="text-xs" {...props}>看推理过程</Button>{/snippet}
            </CollapsibleTrigger>
          </div>
          <CollapsibleContent forceMount>
            {#if reasoningOpen}<AgentReasoning runId={legacyRunId} />{/if}
          </CollapsibleContent>
        </Collapsible>
      </section>
    {/if}
    <PlanDerivation planId={sub} />
    {#if unit}
      <UserInputs ticker={unit.ticker} signalDate={unit.signal_date} />
    {/if}
    {#if noteTarget}
      {#if notesError}
        <section aria-label="备注" class="grid gap-1 text-sm">
          <p class="font-medium">备注</p>
          <p class="text-xs text-muted-foreground">备注暂不可用：{notesError}</p>
        </section>
      {:else if notes !== null}
        <PlanNotes {notes} onNote={addNote} />
      {/if}
    {/if}
    {#if ticker}
      <section aria-label="讨论" class="grid gap-1 text-sm">
        <p class="font-medium">讨论 <span class="text-xs font-normal"><ConceptTerm id={ATTACH.discussion.about}>说明</ConceptTerm></span></p>
        {#if discussionsError}
          <p class="text-xs text-muted-foreground">{`讨论不可用：${discussionsError}`}</p>
        {:else if discussions === null}
          <DataBlock state="loading" skeleton="row" />
        {:else if discussions.length === 0}
          <DataBlock state="empty" message="还没有讨论" />
        {:else}
          <ul class="grid gap-0.5 text-xs">
            {#each discussions as d (d.id)}
              <li><a class="text-primary underline" href={`#discuss/${d.id}`}>{fmtBeijing(d.created_at)} · {d.turn_count} 轮{d.first_question ? ` · ${truncate(d.first_question, 40)}` : ''}</a></li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}
  {/key}
</div>

<ConfirmDialog bind:open={rerunOpen} title="重新运行 Agent" busy={!!rerunAsk && !!rerunBusy[rerunAsk.mode]}
               consequence={`将重置「${rerunAsk ? RERUN_MODE_TEXT[rerunAsk.mode] : ''}」的尝试次数，并重新运行一次 Agent。`}
               actionLabel="重新运行 Agent" onConfirm={async () => { if (rerunAsk) await rerun(rerunAsk) }} />
