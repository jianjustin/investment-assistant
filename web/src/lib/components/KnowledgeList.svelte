<script lang="ts">
  import { onMount } from 'svelte'
  import { Button } from '$lib/ui/button/index'
  import DataTable from '$lib/ui/data-table/DataTable.svelte'
  import type { Column } from '$lib/ui/data-table/types'
  import CutoffTime from '$lib/ui/domain/CutoffTime.svelte'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import VersionChip from '$lib/ui/domain/VersionChip.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import { Input } from '$lib/ui/input/index'
  import ConceptTerm from './ConceptTerm.svelte'
  import * as api from '../api'
    import { conceptId, growthError, normalizeTicker } from '../growth'
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
  const uid = $props.id()
  const SELECT = 'h-8 rounded-md border border-input bg-card px-2 text-sm text-foreground'
  const columns: Column<KnowledgeEntry>[] = [
    { key: 'title', header: '标题', cell: titleCell }, { key: 'attach', header: '挂靠', cell: attachCell },
    { key: 'version', header: '版本 · 状态', cell: versionCell }, { key: 'times', header: '时间', cell: timesCell },
    { key: 'usage', header: '被引用 · 样本', cell: usageCell },
  ]

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

<div class="grid gap-3">
  <div class="flex flex-wrap items-end gap-3 text-sm">
    <Field label="状态" id={`${uid}-status`}>
      {#snippet children({ id })}
        <select {id} class={SELECT} bind:value={status} onchange={load}>
          <option value="active">有效</option><option value="archived">已归档</option><option value="all">全部</option>
        </select>
      {/snippet}
    </Field>
    <Field label="标的" id={`${uid}-ticker`}>
      {#snippet children({ id })}
        <Input {id} class="w-28" value={ticker}
               onchange={e => { ticker = normalizeTicker((e.currentTarget as HTMLInputElement).value); void load() }} />
      {/snippet}
    </Field>
    <Field label="概念" id={`${uid}-concept`}>
      {#snippet children({ id })}
        <Input {id} class="w-44" value={concept}
               onchange={e => { concept = conceptId((e.currentTarget as HTMLInputElement).value.trim()); void load() }} />
      {/snippet}
    </Field>
    <Button variant="primary" href="#knowledge/mine/new">写一条</Button>
    <Button variant="link" href="#knowledge/mine/drafts">{openDrafts ? `草稿（${openDrafts}）` : '草稿'}</Button>
  </div>

  {#if error}
    <DataBlock state="error" message={error} />
  {:else if items === null}
    <DataBlock state="loading" skeleton="table" />
  {:else if items.length === 0}
    <DataBlock state="empty" message="还没有我的知识" />
  {:else}
    <DataTable {columns} rows={items} rowKey={e => e.id} ariaLabel="我的知识" muted={e => e.status === 'archived'} cards="narrow" />
  {/if}
</div>

{#snippet titleCell(e: KnowledgeEntry)}
  <a class="text-primary underline" href={`#knowledge/mine/${e.id}`}>{e.title}</a>
  <p class="text-xs">{e.scope}</p>
{/snippet}
{#snippet attachCell(e: KnowledgeEntry)}
  <span class="text-xs">
    {#each e.concepts as c (c)}<span class="mr-1"><ConceptTerm id={conceptId(c)} /></span>{/each}
    {#each e.tickers as t (t)}<a class="mr-1 text-primary underline" href={`#instrument/${t}`}>{t}</a>{/each}
  </span>
{/snippet}
{#snippet versionCell(e: KnowledgeEntry)}
  <span class="inline-flex flex-wrap items-center gap-1.5 text-xs">
    <VersionChip version={e.current_version} ref={`know:${e.id}@${e.current_version}`} />
    <StatusPill domain="knowledge" value={e.status} />
  </span>
{/snippet}
{#snippet timesCell(e: KnowledgeEntry)}
  <span class="grid text-xs"><CutoffTime at={e.written_at} label="写入" /><CutoffTime at={e.updated_at} label="最近修改" /></span>
{/snippet}
{#snippet usageCell(e: KnowledgeEntry)}
  <span class="grid text-xs"><span>被引用 {e.citation_count} 次</span><span>表现样本 {e.sample_count}</span></span>
{/snippet}
