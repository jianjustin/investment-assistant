<script lang="ts">
  import { untrack } from 'svelte'
  import { Alert, AlertDescription, AlertTitle } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import * as Card from '$lib/ui/card/index'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import PageHeader from '$lib/ui/domain/PageHeader.svelte'
  import { Input } from '$lib/ui/input/index'
  import TabNav from '$lib/ui/tab-nav/TabNav.svelte'
  import * as api from '../lib/api'
  import '../styles/knowledge-body.css'
  import CodeText from '../lib/components/CodeText.svelte'
  import ConceptTerm from '../lib/components/ConceptTerm.svelte'
  import KnowledgeForm from '../lib/components/KnowledgeForm.svelte'
  import KnowledgeItem from '../lib/components/KnowledgeItem.svelte'
  import KnowledgeList from '../lib/components/KnowledgeList.svelte'
  import RunOverview from '../lib/components/RunOverview.svelte'
  import {
    ATTACH, GROUP_TEXT, type ConceptCard, type ConceptsView, type PrinciplesView,
  } from '../lib/knowledge'
  import {
    growthError, idempotentRequests, isTickerLike, knowHref, normalizeTicker, staleDraftText, unwrapRecord,
  } from '../lib/growth'
  import type { KnowledgeDraft, KnowledgeEntry, KnowledgeValues } from '../lib/growth'

  // 「知识」菜单（spec §5）：#knowledge（浏览）、#knowledge/<id>[@<version>]（卡片页）、#knowledge/principles（原理页）。
  // 卡片与原理页正文是后端渲染的 HTML（原始 HTML 已关闭，只有知识接口返回的内容进 {@html}）。
  let { sub }: { sub?: string } = $props()

  type Failure = { status: number | null; message: string; problems: string[] }
  // 「我的知识」(v2.7 §5.5)：mine（列表）、mine/new、mine/drafts、mine/<id>[@<版本>]；概念 id 含点号，不会撞上 mine。
  const isMine = (s: string | undefined) => s === 'mine' || !!s?.startsWith('mine/')
  const mode = $derived(isMine(sub) ? 'mine' : sub === 'principles' ? 'principles' : sub && sub !== 'concepts' ? 'card' : 'browse')
  const minePage = $derived.by(() => {
    const rest = sub?.slice('mine/'.length) ?? ''
    if (sub === 'mine') return { page: 'list' as const }
    if (rest === 'new') return { page: 'new' as const }
    if (rest === 'drafts') return { page: 'drafts' as const }
    const m = /^(\d+)(?:@(\d+))?$/.exec(rest)
    return m ? { page: 'item' as const, id: Number(m[1]), version: m[2] ? Number(m[2]) : null } : { page: 'list' as const }
  })

  let index = $state<ConceptsView | null>(null)
  let card = $state<ConceptCard | null>(null)
  let principles = $state<PrinciplesView | null>(null)
  let failure = $state<Failure | null>(null)
  let loading = $state(true)
  let filter = $state('')
  let date = $state('')
  let generation = 0

  const failureOf = (e: unknown): Failure => {
    const err = e as { status?: number; problems?: string[]; message?: string }
    return { status: typeof err?.status === 'number' ? err.status : null,
             message: String(err?.message ?? e), problems: Array.isArray(err?.problems) ? err.problems : [] }
  }
  const cardId = (ref: string) => ref.replace(/^concept:/, '').split('@')[0]

  async function run<T>(fetcher: () => Promise<T>, accept: (value: T) => void) {
    const token = ++generation
    loading = true
    failure = null
    try {
      const value = await fetcher()
      if (token === generation) accept(value)
    } catch (e) {
      if (token === generation) failure = failureOf(e)
    } finally {
      if (token === generation) loading = false
    }
  }

  // 路由变化才重新取；日期只影响运行一览，不在这里。
  $effect(() => {
    const m = mode
    const ref = sub
    untrack(() => {
      if (m === 'browse') void run(() => api.getConcepts(), v => { index = v })
      else if (m === 'principles') void run(() => api.getPrinciples(), v => { principles = v })
      else if (m === 'mine') { loading = false; failure = null }
      else {
        card = null
        void run(() => api.getConcept(ref!), v => { card = v })
        void loadAttached(cardId(ref!))
      }
    })
  })

  // 概念卡页的「挂在这张卡上的我的知识」：有效的、最新版；读不到只影响这一段
  let attached = $state<{ items: KnowledgeEntry[] | null; error: string }>({ items: null, error: '' })
  async function loadAttached(conceptId: string) {
    attached = { items: null, error: '' }
    try {
      const res = await api.getMyKnowledge({ concept: conceptId, status: 'active' })
      attached = { items: Array.isArray(res?.items) ? res.items : [], error: '' }
    } catch (e) {
      attached = { items: null, error: growthError(e) }
    }
  }

  // 新建：#knowledge/mine/new?ticker=NVDA 预填标的
  const prefillTicker = () => {
    const t = normalizeTicker(new URLSearchParams(location.hash.split('?')[1] ?? '').get('ticker') ?? '')
    return t && isTickerLike(t) ? [t] : []
  }
  async function createEntry(values: KnowledgeValues, requestId: string) {
    const reply = await api.postMyKnowledge({ request_id: requestId, ...values })
    location.hash = `#knowledge/mine/${unwrapRecord<{ id: number }>(reply).id}`
  }

  // 草稿页：讨论草稿逐条采纳（可改）/ 不采纳；复盘卡的草稿只能在卡上审定
  let drafts = $state<KnowledgeDraft[] | null>(null)
  let draftsError = $state('')
  let adopting = $state<Record<number, boolean>>({})
  let dismissError = $state<Record<number, string>>({})
  const dismissRequests: Record<number, ReturnType<typeof idempotentRequests>> = {}
  async function loadDrafts() {
    try {
      drafts = (await api.getKnowledgeDrafts('open')).drafts
      draftsError = ''
    } catch (e) {
      drafts = null
      draftsError = growthError(e)
    }
  }
  $effect(() => {
    if (mode === 'mine' && minePage.page === 'drafts') untrack(() => { void loadDrafts() })
  })
  async function adopt(d: KnowledgeDraft, values: KnowledgeValues, requestId: string) {
    await api.postDraftVerdict(d.id, {
      request_id: requestId, action: 'approve', ...values,
      ...(d.target_knowledge_id != null && d.target_version != null ? { base_version: d.target_version } : {}),
    })
    adopting[d.id] = false
    await loadDrafts()
  }
  async function dismiss(d: KnowledgeDraft) {
    const requests = (dismissRequests[d.id] ??= idempotentRequests())
    dismissError[d.id] = ''
    try {
      await api.postDraftVerdict(d.id, { request_id: requests.idFor({ id: d.id, action: 'dismiss' }), action: 'dismiss' })
      requests.done()
      await loadDrafts()
    } catch (e) {
      dismissError[d.id] = growthError(e)
    }
  }

  const needle = $derived(filter.trim().toLowerCase())
  const matches = (c: { id: string; title: string; summary: string }) =>
    !needle || [c.id, c.title, c.summary].some(value => value.toLowerCase().includes(needle))
  const groups = $derived((index?.groups ?? []).map(g => ({
    ...g, rows: (index?.concepts ?? []).filter(c => c.group === g.id && matches(c)),
  })).filter(g => g.rows.length > 0))
</script>

<section class="grid min-w-0 gap-4">
  {#snippet failureBlock()}
    {#if failure}
      {#if failure.status === 503}
        <Alert variant="danger">
          <Icon name="circle-x" />
          <AlertTitle>概念卡加载失败</AlertTitle>
          <AlertDescription>
            <ul class="ml-5 list-disc text-xs">
              {#each failure.problems.slice(0, 10) as problem}<li>{problem}</li>{/each}
            </ul>
          </AlertDescription>
        </Alert>
      {:else}
        <DataBlock state="error" message={`加载失败：${failure.message}`} />
      {/if}
    {/if}
  {/snippet}

  <TabNav label="知识" items={[
    { href: '#knowledge', label: '概念', current: mode === 'browse' || mode === 'card' },
    { href: '#knowledge/principles', label: '原理', current: mode === 'principles' },
    { href: '#knowledge/mine', label: '我的知识', current: mode === 'mine' },
  ]} />

  {#if mode === 'browse'}
    <PageHeader title="概念" level={1}>
      {#snippet meta()}
        <span>概念卡随代码版本更新，<code>{index?.knowledge_version ?? 'knowledge-1'}</code>；所有规则与 Agent 都未经验证</span>
      {/snippet}
    </PageHeader>
    {#if failure}
      {@render failureBlock()}
    {:else if loading && !index}
      <DataBlock state="loading" skeleton="block" />
    {:else if index}
      {#if index.concepts.length === 0}
        <DataBlock state="empty" message="还没有概念卡" />
      {:else}
        <Input type="search" aria-label="过滤" placeholder="按 id、标题或摘要过滤" class="max-w-sm" bind:value={filter} />
        {#each groups as g (g.id)}
          <section aria-label={GROUP_TEXT[g.id] ?? g.title} class="grid gap-1">
            <h2 class="text-base font-medium"><CodeText text={g.title} /> · {g.rows.length} 张</h2>
            <ul class="grid gap-1 text-sm">
              {#each g.rows as c (c.id)}
                <li class="rounded-md border border-border bg-card p-2">
                  <a class="font-medium text-primary underline" href={`#knowledge/${c.id}`}>{c.title}</a>
                  <code class="text-xs text-muted-foreground">{c.id}</code>
                  {#each c.applies_to as version}<span class="rounded-sm bg-muted px-1 text-xs">{version}</span>{/each}
                  <p class="text-xs text-muted-foreground">{c.summary}</p>
                </li>
              {/each}
            </ul>
          </section>
        {:else}
          <DataBlock state="empty" message="没有匹配的概念卡" />
        {/each}
      {/if}
    {/if}

  {:else if mode === 'card'}
    <p><Button variant="link" size="sm" href="#knowledge" class="text-xs">返回概念列表</Button></p>
    {#if failure?.status === 404}
      <DataBlock state="empty" message={`没有这张概念卡：${cardId(sub ?? '')}`} />
    {:else if failure}
      {@render failureBlock()}
    {:else if loading && !card}
      <DataBlock state="loading" skeleton="block" />
    {:else if card}
      {@const c = card}
      {#if c.stale}<Alert variant="warn"><Icon name="triangle-alert" /><AlertDescription>{c.stale.note}</AlertDescription></Alert>{/if}
      <PageHeader title={c.title} level={1}>
        {#snippet meta()}
          <span><CodeText text={GROUP_TEXT[c.group] ?? c.group} /></span>
          <code>{c.ref}</code>
          {#each c.applies_to as version}<span class="rounded-sm bg-muted px-1">{version}</span>{/each}
        {/snippet}
      </PageHeader>
      <p class="text-sm">{card.summary}</p>
      <div class="knowledge-body grid gap-2 text-sm">{@html card.html}</div>
      {#if card.related_cards.length}
        <section aria-label="相关" class="grid gap-1">
          <h2 class="text-sm font-medium">相关</h2>
          <ul class="flex flex-wrap gap-2 text-sm">
            {#each card.related_cards as r (r.id)}<li><a class="text-primary underline" href={`#knowledge/${r.id}`}>{r.title}</a></li>{/each}
          </ul>
        </section>
      {/if}
      {#if card.backlinks.length}
        <section aria-label="被这些卡提到" class="grid gap-1">
          <h2 class="text-sm font-medium">被这些卡提到</h2>
          <ul class="flex flex-wrap gap-2 text-sm">
            {#each card.backlinks as r (r.id)}<li><a class="text-primary underline" href={`#knowledge/${r.id}`}>{r.title}</a></li>{/each}
          </ul>
        </section>
      {/if}
      <section aria-label="挂在这张卡上的我的知识" class="grid gap-1">
        <h2 class="text-sm font-medium">挂在这张卡上的我的知识</h2>
        {#if attached.error}
          <DataBlock state="error" message={attached.error} />
        {:else if attached.items === null}
          <DataBlock state="loading" skeleton="row" />
        {:else if attached.items.length === 0}
          <DataBlock state="empty" message="还没有挂在这张卡上的经验" />
        {:else}
          <ul class="grid gap-0.5 text-sm">
            {#each attached.items as e (e.id)}
              <li><a class="text-primary underline" href={`#knowledge/mine/${e.id}`}>{e.title}</a>
                <span class="text-xs text-muted-foreground"> · 第 {e.current_version} 版 · {e.scope}</span></li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

  {:else if mode === 'mine'}
    {#if minePage.page === 'list'}
      <PageHeader title="我的知识" level={1}>
        {#snippet meta()}
          <span>你审定过的经验：判断，不是事实。Agent 只能读到截止时间之前写入的版本；
            <ConceptTerm id={ATTACH.myKnowledge.item}>说明</ConceptTerm></span>
        {/snippet}
      </PageHeader>
      <KnowledgeList />
    {:else if minePage.page === 'new'}
      <p><Button variant="link" size="sm" href="#knowledge/mine" class="text-xs">返回我的知识</Button></p>
      <PageHeader title="写一条经验" level={1} />
      <Card.Root size="sm">
        <Card.Content>
          <KnowledgeForm initial={{ tickers: prefillTicker() }} onSubmit={createEntry} />
        </Card.Content>
      </Card.Root>
    {:else if minePage.page === 'drafts'}
      <p><Button variant="link" size="sm" href="#knowledge/mine" class="text-xs">返回我的知识</Button></p>
      <PageHeader title="待审定的草稿" level={1} />
      {#if draftsError}
        <DataBlock state="error" message={draftsError} />
      {:else if drafts === null}
        <DataBlock state="loading" skeleton="block" />
      {:else if drafts.length === 0}
        <DataBlock state="empty" message="没有待审定的草稿" />
      {:else}
        <ul class="grid gap-3">
          {#each drafts as d (d.id)}
            <li class="grid gap-1 rounded-md border border-border bg-card p-3 text-sm">
              <p class="font-medium">{d.title}</p>
              <p class="whitespace-pre-wrap">{d.body}</p>
              <p class="text-xs"><span class="text-muted-foreground">适用范围</span> {d.scope}</p>
              <p class="text-xs"><span class="text-muted-foreground">反例</span> {d.counter_examples}</p>
              {#if d.target_knowledge_id != null}
                <p class="text-xs text-muted-foreground">改写 <a class="text-primary underline" href={knowHref(`know:${d.target_knowledge_id}@${d.target_version}`)}>know:{d.target_knowledge_id}@{d.target_version}</a></p>
              {/if}
              {#if d.origin === 'review_card'}
                <p class="text-xs">来自复盘卡的草稿只能在卡上审定：
                  <a class="text-primary underline" href={`#review/cards/${d.card_id}`}>到复盘卡审定</a></p>
              {:else}
                {@const stale = staleDraftText(d)}
                {#if stale}<p class="text-xs text-warn">{stale}</p>{/if}
                <div class="flex gap-2">
                  <Button size="sm" disabled={!!stale} title={stale ?? undefined}
                          onclick={() => adopting[d.id] = true}>采纳</Button>
                  <Button size="sm" onclick={() => dismiss(d)}>不采纳</Button>
                </div>
                {#if dismissError[d.id]}<Alert variant="danger"><Icon name="circle-x" /><AlertDescription>{dismissError[d.id]}</AlertDescription></Alert>{/if}
                {#if adopting[d.id] && !stale}
                  <div class="border-t border-border pt-2">
                    <KnowledgeForm initial={d} requireCounter submitLabel="确认采纳" requestKey={`draft:${d.id}`}
                                   onSubmit={(values, requestId) => adopt(d, values, requestId)} />
                  </div>
                {/if}
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    {:else}
      <p><Button variant="link" size="sm" href="#knowledge/mine" class="text-xs">返回我的知识</Button></p>
      {#key sub}<KnowledgeItem id={minePage.id} version={minePage.version} />{/key}
    {/if}

  {:else}
    <PageHeader title={principles?.title ?? '原理'} level={1}>
      {#snippet meta()}<span>{date ? '' : '默认最近已收盘交易日'}</span>{/snippet}
      {#snippet actions()}
        <Input type="date" aria-label="日期" class="w-40 text-xs" value={date}
               onchange={e => date = (e.currentTarget as HTMLInputElement).value} />
      {/snippet}
    </PageHeader>
    {#if failure?.status === 404}
      <DataBlock state="empty" message="还没有原理页" />
    {:else if failure}
      {@render failureBlock()}
    {:else if loading && !principles}
      <DataBlock state="loading" skeleton="block" />
    {:else if principles}
      {#each principles.sections as section, i (i)}
        <section aria-label={section.heading} class="grid gap-2">
          <h2 class="text-base font-medium">{section.heading}</h2>
          <div class="knowledge-body grid gap-2 text-sm">{@html section.html}</div>
          {#if section.stage}
            <div data-testid="stage-box" class="grid gap-1 rounded-md border border-border bg-card p-2">
              <RunOverview session={date || undefined} compact onlyStage={section.stage} />
              <a class="text-xs text-primary underline" href="#today">在『今日』看完整运行一览</a>
            </div>
          {/if}
        </section>
      {/each}
    {/if}
  {/if}
</section>
