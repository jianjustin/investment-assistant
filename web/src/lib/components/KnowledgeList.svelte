<script lang="ts">
  import { onMount } from 'svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import { conceptId, growthError, KNOWLEDGE_STATUS_TEXT, normalizeTicker } from '../growth'
  import type { KnowledgeEntry } from '../growth'

  // 「我的知识」列表（spec §5.5）：标题、挂靠、当前版本、状态、写入与最近修改时间、被引用次数、表现样本数；
  // 按状态（默认有效）、标的、概念筛选；「写一条」与「草稿（n）」入口。
  let status = $state<'active' | 'archived' | 'all'>('active')
  let ticker = $state('')
  let concept = $state('')
  let items = $state<KnowledgeEntry[] | null>(null)
  let error = $state('')
  let openDrafts = $state<number | null>(null)
  let generation = 0

  async function load() {
    const token = ++generation
    const params: { status: string; ticker?: string; concept?: string } = { status }
    if (ticker) params.ticker = ticker
    if (concept) params.concept = concept
    try {
      const res = await api.getMyKnowledge(params)
      if (token !== generation) return
      items = Array.isArray(res?.items) ? res.items : []
      error = ''
    } catch (e) {
      if (token !== generation) return
      items = null
      error = growthError(e)
    }
  }

  onMount(() => {
    void load()
    api.getKnowledgeDrafts('open').then(res => { openDrafts = res.drafts.length }).catch(() => { openDrafts = null })
  })
</script>

<div class="space-y-3">
  <div class="flex flex-wrap items-end gap-3 text-sm">
    <label class="flex flex-col text-xs">状态
      <select aria-label="状态" class="border border-border rounded px-2 py-1 bg-bg text-sm" bind:value={status} onchange={load}>
        <option value="active">有效</option><option value="archived">已归档</option><option value="all">全部</option>
      </select>
    </label>
    <label class="flex flex-col text-xs">标的
      <input aria-label="标的" class="border border-border rounded px-2 py-1 bg-bg text-sm w-28" value={ticker}
             onchange={e => { ticker = normalizeTicker((e.currentTarget as HTMLInputElement).value); void load() }} />
    </label>
    <label class="flex flex-col text-xs">概念
      <input aria-label="概念" class="border border-border rounded px-2 py-1 bg-bg text-sm w-44" value={concept}
             onchange={e => { concept = conceptId((e.currentTarget as HTMLInputElement).value.trim()); void load() }} />
    </label>
    <a class="px-3 py-1 rounded bg-accent text-white" href="#knowledge/mine/new">写一条</a>
    <a class="text-accent underline" href="#knowledge/mine/drafts">{openDrafts ? `草稿（${openDrafts}）` : '草稿'}</a>
  </div>

  {#if error}
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if items === null}
    <p class="text-sm text-muted">加载中…</p>
  {:else if items.length === 0}
    <p class="text-sm text-muted">还没有我的知识</p>
  {:else}
    <table class="text-sm w-full">
      <thead><tr class="text-left text-xs text-muted"><th>标题</th><th>挂靠</th><th>版本 · 状态</th><th>时间</th><th>被引用 · 样本</th></tr></thead>
      <tbody>
        {#each items as e (e.id)}
          <tr class="align-top border-t border-border {e.status === 'archived' ? 'text-muted' : ''}">
            <td><a class="text-accent underline" href={`#knowledge/mine/${e.id}`}>{e.title}</a>
              <p class="text-xs">{e.scope}</p></td>
            <td class="text-xs">
              {#each e.concepts as c (c)}<span class="mr-1"><ConceptTerm id={conceptId(c)} /></span>{/each}
              {#each e.tickers as t (t)}<a class="mr-1 text-accent underline" href={`#instrument/${t}`}>{t}</a>{/each}
            </td>
            <td class="text-xs">第 {e.current_version} 版 · {KNOWLEDGE_STATUS_TEXT[e.status] ?? e.status}</td>
            <td class="text-xs">写入 {fmtBeijing(e.written_at)}<br />最近修改 {fmtBeijing(e.updated_at)}</td>
            <td class="text-xs">被引用 {e.citation_count} 次<br />表现样本 {e.sample_count}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>
