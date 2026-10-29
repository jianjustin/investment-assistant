<script lang="ts">
  import { untrack } from 'svelte'
  import * as api from '../lib/api'
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

<section class="space-y-4 min-w-0">
  {#snippet failureBlock()}
    {#if failure}
      {#if failure.status === 503}
        <div role="alert" class="text-sm space-y-1">
          <p class="font-medium text-red-600">概念卡加载失败</p>
          <ul class="list-disc ml-5 text-xs">
            {#each failure.problems.slice(0, 10) as problem}<li>{problem}</li>{/each}
          </ul>
        </div>
      {:else}
        <p role="alert" class="text-sm text-red-600">加载失败：{failure.message}</p>
      {/if}
    {/if}
  {/snippet}

  {#if mode === 'browse'}
    <header>
      <h1 class="text-lg font-semibold">概念</h1>
      <p class="text-xs text-muted">概念卡随代码版本更新，<code>{index?.knowledge_version ?? 'knowledge-1'}</code>；所有规则与 Agent 都未经验证</p>
      <p class="text-xs text-muted">你自己的经验在 <a class="text-accent underline" href="#knowledge/mine">我的知识</a></p>
    </header>
    {#if failure}
      {@render failureBlock()}
    {:else if loading && !index}
      <p class="text-sm text-muted">加载中…</p>
    {:else if index}
      {#if index.concepts.length === 0}
        <p class="text-sm text-muted">还没有概念卡</p>
      {:else}
        <input type="search" aria-label="过滤" placeholder="按 id、标题或摘要过滤"
               class="text-sm border border-border rounded px-2 py-1 bg-bg w-full max-w-sm" bind:value={filter} />
        {#each groups as g (g.id)}
          <section aria-label={GROUP_TEXT[g.id] ?? g.title} class="space-y-1">
            <h2 class="font-semibold"><CodeText text={g.title} /> · {g.rows.length} 张</h2>
            <ul class="space-y-1 text-sm">
              {#each g.rows as c (c.id)}
                <li class="border border-border rounded p-2 bg-surface">
                  <a class="font-medium text-accent underline" href={`#knowledge/${c.id}`}>{c.title}</a>
                  <code class="text-xs text-muted">{c.id}</code>
                  {#each c.applies_to as version}<span class="text-xs px-1 rounded bg-surface-2">{version}</span>{/each}
                  <p class="text-xs text-muted">{c.summary}</p>
                </li>
              {/each}
            </ul>
          </section>
        {:else}
          <p class="text-sm text-muted">没有匹配的概念卡</p>
        {/each}
      {/if}
    {/if}

  {:else if mode === 'card'}
    <p><a class="text-xs text-accent underline" href="#knowledge">返回概念列表</a></p>
    {#if failure?.status === 404}
      <p class="text-sm">没有这张概念卡：{cardId(sub ?? '')}</p>
    {:else if failure}
      {@render failureBlock()}
    {:else if loading && !card}
      <p class="text-sm text-muted">加载中…</p>
    {:else if card}
      {#if card.stale}<p class="text-sm text-amber-700">{card.stale.note}</p>{/if}
      <header class="space-y-1">
        <h1 class="text-lg font-semibold">{card.title}</h1>
        <p class="text-xs text-muted flex flex-wrap items-center gap-2">
          <span><CodeText text={GROUP_TEXT[card.group] ?? card.group} /></span>
          <code>{card.ref}</code>
          {#each card.applies_to as version}<span class="px-1 rounded bg-surface-2">{version}</span>{/each}
        </p>
        <p class="text-sm">{card.summary}</p>
      </header>
      <div class="knowledge-body text-sm space-y-2">{@html card.html}</div>
      {#if card.related_cards.length}
        <section aria-label="相关" class="space-y-1">
          <h2 class="font-semibold text-sm">相关</h2>
          <ul class="flex flex-wrap gap-2 text-sm">
            {#each card.related_cards as r (r.id)}<li><a class="text-accent underline" href={`#knowledge/${r.id}`}>{r.title}</a></li>{/each}
          </ul>
        </section>
      {/if}
      {#if card.backlinks.length}
        <section aria-label="被这些卡提到" class="space-y-1">
          <h2 class="font-semibold text-sm">被这些卡提到</h2>
          <ul class="flex flex-wrap gap-2 text-sm">
            {#each card.backlinks as r (r.id)}<li><a class="text-accent underline" href={`#knowledge/${r.id}`}>{r.title}</a></li>{/each}
          </ul>
        </section>
      {/if}
      <section aria-label="挂在这张卡上的我的知识" class="space-y-1">
        <h2 class="font-semibold text-sm">挂在这张卡上的我的知识</h2>
        {#if attached.error}
          <p class="text-xs text-muted">{attached.error}</p>
        {:else if attached.items === null}
          <p class="text-xs text-muted">加载中…</p>
        {:else if attached.items.length === 0}
          <p class="text-xs text-muted">还没有挂在这张卡上的经验</p>
        {:else}
          <ul class="text-sm space-y-0.5">
            {#each attached.items as e (e.id)}
              <li><a class="text-accent underline" href={`#knowledge/mine/${e.id}`}>{e.title}</a>
                <span class="text-xs text-muted"> · 第 {e.current_version} 版 · {e.scope}</span></li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

  {:else if mode === 'mine'}
    {#if minePage.page === 'list'}
      <header class="space-y-1">
        <h1 class="text-lg font-semibold">我的知识</h1>
        <p class="text-xs text-muted">你审定过的经验：判断，不是事实。Agent 只能读到截止时间之前写入的版本；
          <ConceptTerm id={ATTACH.myKnowledge.item}>说明</ConceptTerm>
          · <a class="text-accent underline" href="#knowledge">返回概念</a></p>
      </header>
      <KnowledgeList />
    {:else if minePage.page === 'new'}
      <p><a class="text-xs text-accent underline" href="#knowledge/mine">返回我的知识</a></p>
      <h1 class="text-lg font-semibold">写一条经验</h1>
      <div class="border border-border rounded p-3">
        <KnowledgeForm initial={{ tickers: prefillTicker() }} onSubmit={createEntry} />
      </div>
    {:else if minePage.page === 'drafts'}
      <p><a class="text-xs text-accent underline" href="#knowledge/mine">返回我的知识</a></p>
      <h1 class="text-lg font-semibold">待审定的草稿</h1>
      {#if draftsError}
        <p role="alert" class="text-sm text-red-600">{draftsError}</p>
      {:else if drafts === null}
        <p class="text-sm text-muted">加载中…</p>
      {:else if drafts.length === 0}
        <p class="text-sm text-muted">没有待审定的草稿</p>
      {:else}
        <ul class="space-y-3">
          {#each drafts as d (d.id)}
            <li class="border border-border rounded p-3 text-sm space-y-1">
              <p class="font-medium">{d.title}</p>
              <p class="whitespace-pre-wrap">{d.body}</p>
              <p class="text-xs"><span class="text-muted">适用范围</span> {d.scope}</p>
              <p class="text-xs"><span class="text-muted">反例</span> {d.counter_examples}</p>
              {#if d.target_knowledge_id != null}
                <p class="text-xs text-muted">改写 <a class="text-accent underline" href={knowHref(`know:${d.target_knowledge_id}@${d.target_version}`)}>know:{d.target_knowledge_id}@{d.target_version}</a></p>
              {/if}
              {#if d.origin === 'review_card'}
                <p class="text-xs">来自复盘卡的草稿只能在卡上审定：
                  <a class="text-accent underline" href={`#review/cards/${d.card_id}`}>到复盘卡审定</a></p>
              {:else}
                {@const stale = staleDraftText(d)}
                {#if stale}<p class="text-xs text-amber-700">{stale}</p>{/if}
                <div class="flex gap-2">
                  <button type="button" class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2 disabled:opacity-50"
                          disabled={!!stale} title={stale ?? undefined}
                          onclick={() => adopting[d.id] = true}>采纳</button>
                  <button type="button" class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2"
                          onclick={() => dismiss(d)}>不采纳</button>
                </div>
                {#if dismissError[d.id]}<p role="alert" class="text-xs text-red-600">{dismissError[d.id]}</p>{/if}
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
      <p><a class="text-xs text-accent underline" href="#knowledge/mine">返回我的知识</a></p>
      {#key sub}<KnowledgeItem id={minePage.id} version={minePage.version} />{/key}
    {/if}

  {:else}
    <header class="flex flex-wrap items-center gap-3">
      <h1 class="text-lg font-semibold">{principles?.title ?? '原理'}</h1>
      <input type="date" aria-label="日期" class="text-xs border border-border rounded px-1 py-0.5 bg-bg"
             value={date} onchange={e => date = (e.currentTarget as HTMLInputElement).value} />
      <span class="text-xs text-muted">{date ? '' : '默认最近已收盘交易日'}</span>
    </header>
    {#if failure?.status === 404}
      <p class="text-sm text-muted">还没有原理页</p>
    {:else if failure}
      {@render failureBlock()}
    {:else if loading && !principles}
      <p class="text-sm text-muted">加载中…</p>
    {:else if principles}
      {#each principles.sections as section, i (i)}
        <section aria-label={section.heading} class="space-y-2">
          <h2 class="font-semibold">{section.heading}</h2>
          <div class="knowledge-body text-sm space-y-2">{@html section.html}</div>
          {#if section.stage}
            <div data-testid="stage-box" class="border border-border rounded p-2 bg-surface space-y-1">
              <RunOverview session={date || undefined} compact onlyStage={section.stage} />
              <a class="text-xs text-accent underline" href="#today">在『今日』看完整运行一览</a>
            </div>
          {/if}
        </section>
      {/each}
    {/if}
  {/if}
</section>

<style>
  .knowledge-body :global(h2) { font-weight: 600; margin-top: 0.75rem; }
  .knowledge-body :global(p), .knowledge-body :global(ul), .knowledge-body :global(ol) { margin: 0.25rem 0; }
  .knowledge-body :global(ul) { list-style: disc; margin-left: 1.25rem; }
  .knowledge-body :global(ol) { list-style: decimal; margin-left: 1.25rem; }
  .knowledge-body :global(a) { color: var(--accent); text-decoration: underline; }
  .knowledge-body :global(code) { padding: 0 0.2rem; border-radius: 0.2rem; background: var(--surface-2); }
  .knowledge-body :global(table) { border-collapse: collapse; font-size: 0.75rem; }
  .knowledge-body :global(th), .knowledge-body :global(td) { border: 1px solid var(--border); padding: 0.2rem 0.5rem; }
</style>
