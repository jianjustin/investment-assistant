<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import CutoffTime from '$lib/ui/domain/CutoffTime.svelte'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import PageHeader from '$lib/ui/domain/PageHeader.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import VersionChip from '$lib/ui/domain/VersionChip.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import { Textarea } from '$lib/ui/textarea/index'
  import AgentReasoning from './AgentReasoning.svelte'
  import RefList from './RefList.svelte'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import {
    DISCUSS_INTERRUPTED_TEXT, DISCUSS_POLL_INTERVAL_MS, DISCUSS_POLL_MS, DISCUSS_TIMEOUT_TEXT, endText, growthError,
    idempotentRequests, knowHref, userInputRequestId,
  } from '../growth'
  import type { Discussion, DiscussionAttachment, DiscussionTurn, KnowledgeDraft, KnowledgeEntry } from '../growth'
  import { AGENT_REASON_TEXT } from '../workbench'
  import { USER_INPUT_KIND_TEXT } from '../timeline'
  import type { UserInputKind } from '../timeline'

  // 讨论页（spec §8）：上下文摘要 → 每一轮（你问 / 它答）→ 输入框。提问后每 2 秒读一次 GET /discussions/{id}（只读这一个接口），
  // 直到这一轮有回答、被标「中断」，或超过 DISCUSS_POLL_MS；超时写「回答仍在后台生成，稍后刷新查看」。
  // 回答与经验草稿一律按纯文本显示。
  let { id }: { id: number } = $props()

  const MAX_QUESTION = 4000
  const KINDS: UserInputKind[] = ['research', 'news', 'judgment', 'other']

  let disc = $state<Discussion | null>(null)
  let loadError = $state('')
  let question = $state('')
  let attachment = $state<(DiscussionAttachment & { label: string }) | null>(null)
  let askError = $state('')        // the submit was refused or failed (Alert in the form)
  let questionError = $state('')   // validation (under the field)
  let waited = $state(0)           // seconds since the current wait started
  const uid = $props.id()
  const SELECT = 'h-7 rounded-md border border-input bg-card px-2 text-xs text-foreground'
  let busy = $state(false)
  let timedOut = $state(false)
  let pickerOpen = $state(false)
  let picker = $state<{ entries: KnowledgeEntry[]; drafts: KnowledgeDraft[] } | null>(null)
  let saveKind = $state<Record<number, UserInputKind>>({})
  let savedInput = $state<Record<number, number>>({})
  let saveError = $state<Record<number, string>>({})
  let reasoningOpen = $state<Record<number, boolean>>({})
  let header = $state<HTMLElement | undefined>()
  const requests = idempotentRequests()

  // ---- loading and polling ----
  let timer: ReturnType<typeof setTimeout> | null = null
  let pollStart = 0
  /** Set on unmount: a read still in flight must not arm a new timer (app.svelte swaps discussions with {#key}). */
  let destroyed = false

  /** The last turn is the user's with no answer after it. */
  const waitingTurn = (d: Discussion | null): DiscussionTurn | null => {
    const last = d?.turns[d.turns.length - 1]
    return last && last.role === 'user' ? last : null
  }
  function stop() { if (timer) clearTimeout(timer); timer = null }
  function schedule() { stop(); if (destroyed) return; timer = setTimeout(tick, DISCUSS_POLL_INTERVAL_MS) }

  /** After every read: answered → done; interrupted → done; past the limit → timed out; otherwise read again. */
  function evaluate() {
    const waiting = waitingTurn(disc)
    waited = Math.max(0, Math.floor((Date.now() - pollStart) / 1000))
    if (!waiting || waiting.state === 'interrupted') { stop(); timedOut = false; return }
    if (Date.now() - pollStart >= DISCUSS_POLL_MS) { stop(); timedOut = true; return }
    schedule()
  }
  async function tick() {
    try {
      const next = await api.getDiscussion(id)
      if (destroyed) return
      disc = next
    } catch { /* a missed read is retried on the next tick */ }
    if (destroyed) return
    evaluate()
  }
  function startPolling() { if (destroyed) return; timedOut = false; pollStart = Date.now(); evaluate() }

  onMount(async () => {
    try {
      const first = await api.getDiscussion(id)
      if (destroyed) return
      disc = first
      loadError = ''
      startPolling()
    } catch (e) {
      if (!destroyed) loadError = growthError(e)
    }
  })
  onDestroy(() => { destroyed = true; stop() })

  // ---- asking ----
  async function ask() {
    if (busy) return
    const text = question.trim()
    const n = [...text].length
    askError = ''
    if (n === 0) { questionError = '问题不能为空'; return }
    if (n > MAX_QUESTION) { questionError = `问题最多 ${MAX_QUESTION} 字（现在 ${n} 字）`; return }
    questionError = ''
    busy = true
    const payload = { body: text, ...(attachment ? { attachment: { kind: attachment.kind, id: attachment.id,
                      ...(attachment.version != null ? { version: attachment.version } : {}) } } : {}) }
    try {
      await api.postDiscussionTurn(id, { request_id: requests.idFor(payload), ...payload })
      requests.done()
      question = ''
      attachment = null
      try {
        const next = await api.getDiscussion(id)
        if (!destroyed) disc = next
      } catch (e) { if (!destroyed) askError = growthError(e) }
      startPolling()
    } catch (e) {
      askError = growthError(e)
    } finally {
      busy = false
    }
  }

  async function togglePicker() {
    pickerOpen = !pickerOpen
    if (!pickerOpen) return
    const [entries, drafts] = await Promise.all([
      api.getMyKnowledge({ status: 'active' }).then(r => r.items).catch(() => [] as KnowledgeEntry[]),
      api.getKnowledgeDrafts('open').then(r => r.drafts).catch(() => [] as KnowledgeDraft[]),
    ])
    picker = { entries, drafts }
  }
  function pickKnowledge(e: KnowledgeEntry) {
    attachment = { kind: 'knowledge', id: e.id, version: e.current_version, label: `${e.title}（第 ${e.current_version} 版）` }
    pickerOpen = false
  }
  function pickDraft(d: KnowledgeDraft) {
    attachment = { kind: 'draft', id: d.id, label: `草稿 ${d.title}` }
    pickerOpen = false
  }
  const attachmentLabel = (a: DiscussionAttachment & { title?: string }) =>
    a.kind === 'knowledge' ? `${a.title ?? `know:${a.id}`}${a.version != null ? `（第 ${a.version} 版）` : ''}`
      : `草稿 ${a.title ?? `#${a.id}`}`

  // ---- 存为补充信息: the user input of this turn, with the request id derived from the turn's own ----
  async function saveAsInput(turn: DiscussionTurn) {
    if (!disc || !turn.request_id) return
    saveError[turn.id] = ''
    try {
      const out = await api.postUserInput({
        request_id: await userInputRequestId(turn.request_id), ticker: disc.ticker, signal_date: disc.signal_date,
        kind: saveKind[turn.id] ?? 'judgment', body: turn.body,
      })
      savedInput[turn.id] = out.record.id
    } catch (e) {
      saveError[turn.id] = growthError(e)
    }
  }

  function scrollToContext(key: string) {
    if (key === 'context') header?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }
  const reasonText = (reason: string | null | undefined) => AGENT_REASON_TEXT[reason ?? ''] ?? reason ?? '未知原因'
</script>

{#if loadError}
  <DataBlock page state="error" message={`讨论加载失败：${loadError}`} />
{:else if !disc}
  <DataBlock page state="loading" skeleton="block" />
{:else}
<section class="grid min-w-0 gap-4">
  <div bind:this={header} data-testid="discussion-header" class="grid gap-1">
    <PageHeader level={1} title={`讨论 · ${disc.ticker} · ${disc.signal_date}`}>
      {#snippet meta()}
        {#if disc!.context_kind === 'plan'}
          {#if disc!.context?.version_no != null}<VersionChip version={disc!.context.version_no} />{/if}
          <CutoffTime at={disc!.context?.generated_at} label="生成于" />
          <CutoffTime at={disc!.context?.cutoff_at} />
          {#if disc!.plan_id}<a class="text-primary underline" href={`#plan/${disc!.plan_id}`}>回到计划页</a>{/if}
        {:else}
          {#if disc!.context?.end_kind}<span>{endText(disc!.context.end_kind)}</span>{/if}
          {#if disc!.context?.end_session}<span>结束日 {disc!.context.end_session}</span>{/if}
          {#if disc!.card_id != null}<a class="text-primary underline" href={`#review/cards/${disc!.card_id}`}>回到复盘卡</a>{/if}
        {/if}
        <a class="text-primary underline" href={`#instrument/${encodeURIComponent(disc!.ticker)}`}>标的页</a>
      {/snippet}
    </PageHeader>
    <p class="text-xs text-muted-foreground">回答只读截止时间之前的数据；它不能改任何东西，计划修订只能由你点「重新复查」。证据：未验证</p>
  </div>

  <ol class="grid gap-3">
    {#each disc.turns as turn, index (turn.id)}
      <li data-testid="turn" class="grid gap-1 rounded-md border border-border p-3 text-sm {turn.role === 'user' ? 'bg-card' : ''}">
        {#if turn.role === 'user'}
          <p class="text-xs text-muted-foreground">你 · {fmtBeijing(turn.created_at)}</p>
          <p class="whitespace-pre-wrap">{turn.body}</p>
          {#if turn.attachment}<p class="text-xs text-muted-foreground">附件：{attachmentLabel(turn.attachment)}</p>{/if}
          {#if turn.user_input_id != null || savedInput[turn.id] != null}
            <p class="text-xs">已存为补充信息 <span>user:{turn.user_input_id ?? savedInput[turn.id]}</span></p>
          {:else if turn.request_id}
            <p class="flex flex-wrap items-center gap-2 text-xs">
              <select aria-label="补充信息类型" class={SELECT}
                      value={saveKind[turn.id] ?? 'judgment'}
                      onchange={e => saveKind[turn.id] = (e.currentTarget as HTMLSelectElement).value as UserInputKind}>
                {#each KINDS as kind (kind)}<option value={kind}>{USER_INPUT_KIND_TEXT[kind]}</option>{/each}
              </select>
              <Button size="sm" onclick={() => saveAsInput(turn)}>存为补充信息</Button>
            </p>
            {#if saveError[turn.id]}<Alert variant="danger"><AlertDescription>{saveError[turn.id]}</AlertDescription></Alert>{/if}
          {/if}
          {#if index === disc.turns.length - 1}
            {#if turn.state === 'interrupted'}
              <Alert variant="warn" role="status"><AlertDescription>{DISCUSS_INTERRUPTED_TEXT}</AlertDescription></Alert>
            {:else if timedOut}
              <Alert variant="warn" role="status"><AlertDescription>{DISCUSS_TIMEOUT_TEXT}</AlertDescription></Alert>
            {:else}
              <p class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <StatusPill domain="run" value="running" text="回答中…" />
                <span>已等待 {waited} 秒</span>
              </p>
            {/if}
          {/if}
        {:else}
          <p class="text-xs text-muted-foreground">回答{turn.cutoff_at ? ` · 截止 ${fmtBeijing(turn.cutoff_at)}` : ''}</p>
          {#if turn.status === 'ok'}
            <p data-answer class="whitespace-pre-wrap">{turn.body}</p>
            {#if turn.refs?.length}<p class="text-xs text-muted-foreground">引用<RefList refs={turn.refs} runId={turn.agent_run_id} onFact={scrollToContext} /></p>{/if}
          {:else if turn.status === 'rejected'}
            <p class="text-xs text-warn">这条回答没有通过校验：{reasonText(turn.reason)}</p>
            <details class="text-xs">
              <summary class="cursor-pointer text-primary">仍要看原文（未通过校验）</summary>
              <p class="whitespace-pre-wrap text-muted-foreground">{turn.body}</p>
            </details>
          {:else}
            <p class="text-xs text-warn">这一轮没有得到回答：{reasonText(turn.reason)}</p>
          {/if}
          {#if turn.agent_run_id}
            <div><Button variant="link" size="sm" class="text-xs" aria-expanded={!!reasoningOpen[turn.id]}
                    onclick={() => reasoningOpen[turn.id] = !reasoningOpen[turn.id]}>看这次回答读了什么</Button></div>
            {#if reasoningOpen[turn.id]}<AgentReasoning runId={turn.agent_run_id} />{/if}
          {/if}
          {#if turn.detail?.draft_dropped}
            <p class="text-xs text-muted-foreground">经验草稿未通过校验，已丢弃：{reasonText(String(turn.detail.draft_dropped))}</p>
          {/if}
          {#if turn.knowledge_draft}
            {@const draft = turn.knowledge_draft}
            <section aria-label="经验草稿" class="grid gap-0.5 rounded-md border border-border p-2 text-xs">
              <p class="font-medium">{draft.title}</p>
              <p class="whitespace-pre-wrap">{draft.body}</p>
              <p><span class="text-muted-foreground">适用范围</span> {draft.scope}</p>
              <p><span class="text-muted-foreground">反例</span> {draft.counter_examples}</p>
              {#if draft.target_knowledge_id != null}
                <p class="text-muted-foreground">改写 <a class="text-primary underline" href={`#knowledge/mine/${draft.target_knowledge_id}@${draft.target_version}`}>know:{draft.target_knowledge_id}@{draft.target_version}</a></p>
              {/if}
              {#if draft.verdict?.action === 'approve'}
                <p>已采纳{#if draft.verdict.ref} <a class="text-primary underline" href={knowHref(draft.verdict.ref)}>{draft.verdict.ref}</a>{/if}</p>
              {:else if draft.verdict?.action === 'dismiss'}
                <p class="text-muted-foreground">已不采纳</p>
              {:else}
                <a class="text-primary underline" href="#knowledge/mine/drafts">去审定</a>
              {/if}
            </section>
          {/if}
        {/if}
      </li>
    {:else}
      <li class="text-xs text-muted-foreground">还没有提问。问题只限于这个{disc.context_kind === 'card' ? '复盘卡' : '计划'}。</li>
    {/each}
  </ol>

  <div class="grid gap-2 text-sm">
    <Field label="你的问题" id={`${uid}-question`} hint="1–4000 字" error={questionError || null}>
      {#snippet children({ id, describedby, invalid })}
        <Textarea {id} rows={3} aria-describedby={describedby} aria-invalid={invalid} readonly={busy} bind:value={question} />
      {/snippet}
    </Field>
    {#if attachment}
      <p class="flex items-center gap-2 text-xs"><span>附件：{attachment.label}</span>
        <Button variant="ghost" size="icon" aria-label="移除附件" onclick={() => attachment = null}><Icon name="x" /></Button></p>
    {/if}
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="primary" {busy} onclick={ask}>提问</Button>
      <Button size="sm" aria-expanded={pickerOpen} onclick={togglePicker}>就这条改写</Button>
    </div>
    {#if pickerOpen}
      <section aria-label="选一条作为附件" class="grid gap-1 rounded-md border border-border p-2 text-xs">
        {#if !picker}
          <DataBlock state="loading" skeleton="row" />
        {:else}
          <ul class="grid gap-0.5">
            {#each picker.entries as e (e.id)}
              <li><Button variant="link" size="sm" class="text-xs" onclick={() => pickKnowledge(e)}>{e.title}（第 {e.current_version} 版）</Button></li>
            {/each}
            {#each picker.drafts as d (d.id)}
              <li><Button variant="link" size="sm" class="text-xs" onclick={() => pickDraft(d)}>草稿：{d.title}</Button></li>
            {/each}
          </ul>
          {#if !picker.entries.length && !picker.drafts.length}<DataBlock state="empty" message="还没有可选的知识或草稿" />{/if}
        {/if}
        <p class="text-muted-foreground">附件是你提供的材料，不是证据，回答不能引用它。</p>
      </section>
    {/if}
    {#if askError}<Alert variant="danger"><AlertDescription>{askError}</AlertDescription></Alert>{/if}
  </div>
</section>
{/if}
