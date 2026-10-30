<script lang="ts">
  import { onMount } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import ConfirmDialog from '$lib/ui/confirm-dialog/ConfirmDialog.svelte'
  import CutoffTime from '$lib/ui/domain/CutoffTime.svelte'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import PageHeader from '$lib/ui/domain/PageHeader.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import VersionChip from '$lib/ui/domain/VersionChip.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import { Input } from '$lib/ui/input/index'
  import ConceptTerm from './ConceptTerm.svelte'
  import KnowledgeForm from './KnowledgeForm.svelte'
  import KnowledgePerformance from './KnowledgePerformance.svelte'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import { ATTACH } from '../knowledge'
  import {
    changedFields, CITED_FIELD_TEXT, conceptId, growthError, idempotentRequests, KNOWLEDGE_ORIGIN_TEXT,
  } from '../growth'
  import type { KnowledgeItemView, KnowledgeValues } from '../growth'
  import { WorkbenchError } from '../workbench'

  // 条目页（spec §5.5）：所选（默认最新）版本的全文与挂靠、改 / 归档 / 恢复、版本历史、被引用、表现回看。
  // 正文一律按纯文本显示（保留换行），不渲染 Markdown、不解析 HTML。
  let { id, version }: { id: number; version?: number | null } = $props()

  let view = $state<KnowledgeItemView | null>(null)
  let error = $state('')
  let notFound = $state(false)
  let mode = $state<'view' | 'edit' | 'status'>('view')
  let stale = $state(false)
  let formGen = $state(0)                 // bumped to rebuild the edit form from the latest version
  let reloadNote = $state('')
  let reason = $state('')
  let statusBusy = $state(false)
  let statusError = $state('')
  let archiveOpen = $state(false)
  const uid = $props.id()
  const statusRequests = idempotentRequests()
  const M = ATTACH.myKnowledge

  async function load() {
    try {
      view = await api.getKnowledgeItem(id, version ?? undefined)
      error = ''
      notFound = false
    } catch (e) {
      view = null
      notFound = e instanceof WorkbenchError && e.status === 404
      error = growthError(e)
    }
  }
  onMount(() => { void load() })

  const versions = $derived([...(view?.versions ?? [])].sort((a, b) => a.version - b.version))
  const latest = $derived(versions.length ? versions[versions.length - 1] : (view?.current ?? null))
  const viewed = $derived(
    (version != null ? versions.find(v => v.version === version) : null) ?? latest ?? view?.current ?? null)
  const isOld = $derived(!!viewed && !!latest && viewed.version < latest.version)
  const archived = $derived.by(() => {
    if (!view) return false
    if (view.item.status) return view.item.status === 'archived'
    const last = [...view.status_history].sort((a, b) => a.created_at.localeCompare(b.created_at)).pop()
    return last?.status === 'archived'
  })
  const archiveReason = $derived(
    [...(view?.status_history ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at)).pop()?.reason ?? '')
  const history = $derived(versions.map((v, i) => ({
    v, changed: i === 0 ? null : changedFields(versions[i - 1], v),
  })).reverse())

  async function reviseSubmit(values: KnowledgeValues, requestId: string) {
    try {
      await api.postKnowledgeVersion(id, { request_id: requestId, base_version: latest!.version, ...values })
    } catch (e) {
      if (e instanceof WorkbenchError && e.status === 409 && e.message.startsWith('knowledge_stale')) stale = true
      throw e
    }
    mode = 'view'
    stale = false
    await load()
  }

  /** After a stale 409: reload, then refill the form from the new latest version. The old input is dropped, not resubmitted. */
  async function refreshStale() {
    await load()
    if (!latest) return
    formGen++
    stale = false
    reloadNote = `已有第 ${latest.version} 版，已载入最新内容，请对照后再提交`
  }

  function startStatus() { mode = 'status'; reason = ''; statusError = '' }
  async function changeStatus() {
    if (statusBusy) return
    const next: 'active' | 'archived' = archived ? 'active' : 'archived'
    const payload = { status: next, reason: reason.trim() }
    if ([...payload.reason].length > 300) { statusError = '理由最多 300 字'; archiveOpen = false; return }
    statusBusy = true
    statusError = ''
    try {
      await api.postKnowledgeStatus(id, { request_id: statusRequests.idFor(payload), ...payload })
      statusRequests.done()
      mode = 'view'
      await load()
    } catch (e) {
      statusError = growthError(e)
    } finally {
      statusBusy = false
      archiveOpen = false
    }
  }

  /** Archiving goes through the confirm dialog; restoring is the way back and needs no extra step. */
  function submitStatus() {
    if ([...reason.trim()].length > 300) { statusError = '理由最多 300 字'; return }       // before the dialog, so it never opens for an invalid reason
    if (archived) void changeStatus()
    else archiveOpen = true
  }
</script>

<section class="grid min-w-0 gap-4">
  {#if notFound}
    <DataBlock state="empty" message={`没有这条知识：${id}`} />
  {:else if error}
    <DataBlock state="error" message={error} />
  {:else if !view || !viewed}
    <DataBlock state="loading" skeleton="block" />
  {:else}
    {#if isOld}
      <Alert variant="info">
        <Icon name="info" />
        <AlertDescription><span>这是第 {viewed.version} 版，最新为第 {latest!.version} 版</span>
          <a class="ml-2 text-primary underline" href={`#knowledge/mine/${id}`}>查看最新版</a></AlertDescription>
      </Alert>
    {/if}
    <PageHeader title={viewed.title} level={1}>
      {#snippet meta()}
        <StatusPill domain="knowledge" value={archived ? 'archived' : 'active'} />
        <VersionChip version={viewed.version} latest={isOld ? null : latest?.version ?? null} ref={`know:${id}@${viewed.version}`} />
        <CutoffTime at={view?.item.created_at} label="写入" />
        <CutoffTime at={viewed.created_at} label="本版" />
        <ConceptTerm id={M.item}>说明</ConceptTerm>
      {/snippet}
    </PageHeader>
    {#if archived && archiveReason}<p class="text-xs text-muted-foreground">归档理由：{archiveReason}</p>{/if}

    <div class="grid gap-2 text-sm">
      <p class="whitespace-pre-wrap">{viewed.body}</p>
      <div>
        <p class="text-xs text-muted-foreground">适用范围</p>
        <p class="whitespace-pre-wrap">{viewed.scope}</p>
      </div>
      {#if viewed.counter_examples}
        <div>
          <p class="text-xs text-muted-foreground">反例</p>
          <p class="whitespace-pre-wrap">{viewed.counter_examples}</p>
        </div>
      {/if}
      <p class="text-xs">挂靠：
        {#each viewed.concepts as c (c)}<span class="mr-2"><ConceptTerm id={conceptId(c)} /></span>{/each}
        {#each viewed.tickers as t (t)}<a class="mr-2 text-primary underline" href={`#instrument/${t}`}>{t}</a>{/each}
      </p>
    </div>

    <div class="grid gap-2">
      <div class="flex flex-wrap items-center gap-2">
        {#if archived}
          <span class="text-xs text-muted-foreground">已归档，先恢复才能改</span>
          <Button size="sm" onclick={startStatus}>恢复</Button>
        {:else}
          <Button size="sm" onclick={() => { mode = 'edit'; stale = false; reloadNote = '' }}>改</Button>
          <Button size="sm" onclick={startStatus}>归档</Button>
        {/if}
      </div>

      {#if mode === 'status'}
        <div class="grid gap-2 rounded-md border border-border p-3 text-sm">
          <Field label="理由" id={`${uid}-reason`}>
            {#snippet children({ id: fieldId, describedby })}
              <Input id={fieldId} aria-describedby={describedby} maxlength={300} bind:value={reason} />
            {/snippet}
          </Field>
          <div class="flex gap-2">
            <Button variant="primary" size="sm" busy={statusBusy && archived} onclick={submitStatus}>{archived ? '确认恢复' : '确认归档'}</Button>
            <Button size="sm" disabled={statusBusy} onclick={() => mode = 'view'}>取消</Button>
          </div>
          {#if statusError}<Alert variant="danger"><Icon name="circle-x" /><AlertDescription>{statusError}</AlertDescription></Alert>{/if}
        </div>
      {/if}

      {#if mode === 'edit' && latest}
        <div class="grid gap-2 rounded-md border border-border p-3">
          <p class="text-xs text-muted-foreground">改动会作为第 {latest.version + 1} 版写入，原来的版本都保留。</p>
          {#if reloadNote}<Alert variant="info"><Icon name="info" /><AlertDescription>{reloadNote}</AlertDescription></Alert>{/if}
          {#key formGen}
            <KnowledgeForm initial={latest} onSubmit={reviseSubmit} requestKey={`base:${latest.version}`} />
          {/key}
          <div class="flex gap-2">
            {#if stale}
              <Button size="sm" onclick={refreshStale}>刷新</Button>
            {/if}
            <Button size="sm" onclick={() => mode = 'view'}>取消</Button>
          </div>
        </div>
      {/if}
    </div>

    <section aria-label="版本历史" class="grid gap-1 text-sm">
      <h3 class="text-base font-medium">版本历史</h3>
      <ol aria-label="版本历史" class="grid gap-1">
        {#each history as { v, changed } (v.version)}
          <li class="text-xs">
            <a class="text-primary underline" href={`#knowledge/mine/${id}@${v.version}`}>第 {v.version} 版</a>
            · {fmtBeijing(v.created_at)}
            {#if changed === null}
              · 首版 · {KNOWLEDGE_ORIGIN_TEXT[view.item.origin] ?? view.item.origin}
              {#if view.item.source_card_id}· <a class="text-primary underline" href={`#review/cards/${view.item.source_card_id}`}>复盘卡 #{view.item.source_card_id}</a>{/if}
              {#if view.item.source_discussion_id}· <a class="text-primary underline" href={`#discuss/${view.item.source_discussion_id}`}>讨论 #{view.item.source_discussion_id}</a>{/if}
            {:else}
              · 改了：{changed.length ? changed.join('、') : '没有字段变化'}
            {/if}
          </li>
        {/each}
      </ol>
    </section>

    <section aria-label="被引用" class="grid gap-1 text-sm">
      <h3 class="text-base font-medium">被引用</h3>
      {#if view.citations.length}
        <ul aria-label="被引用" class="grid gap-0.5 text-xs">
          {#each view.citations as c, i (i)}
            <li>
              {#if c.plan_id}
                <a class="text-primary underline" href={`#plan/${c.plan_id}`}>{c.ticker} {c.signal_date} 第 {c.version_no} 版</a>
              {:else if c.head_plan_id}
                <a class="text-primary underline" href={`#plan/${c.head_plan_id}`}>{c.ticker} {c.signal_date} 复查 #{c.review_id}</a>
              {:else}
                {c.ticker} {c.signal_date}{c.review_id ? ` 复查 #${c.review_id}` : ''}
              {/if}
              · 引用的是第 {c.cited_version} 版 · {CITED_FIELD_TEXT[c.field] ?? c.field}
            </li>
          {/each}
        </ul>
      {:else}
        <DataBlock state="empty" message="还没有被计划或复查引用" />
      {/if}
    </section>

    <KnowledgePerformance {id} />

    <ConfirmDialog bind:open={archiveOpen} title="归档这条知识" consequence="归档后先恢复才能再改；所有版本都保留。"
                   actionLabel="归档" busy={statusBusy} onConfirm={changeStatus} />
  {/if}
</section>
