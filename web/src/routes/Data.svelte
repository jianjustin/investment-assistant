<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import { KNOWN_FAMILIES, type DataOverview } from '../lib/data-families'
  import DataFamilyCard from '../lib/components/DataFamilyCard.svelte'

  let { sub }: { sub?: string } = $props()

  let overview = $state<DataOverview | null>(null)
  let error = $state('')
  let loading = $state(true)
  let generation = 0

  async function load() {
    const token = ++generation
    try {
      const next = await api.getDataFamilies()
      if (token !== generation) return
      overview = next
      error = ''
    } catch (e) {
      if (token === generation) { error = String((e as Error)?.message ?? e); overview = null }
    } finally {
      if (token === generation) loading = false
    }
  }

  onMount(() => {
    load()
    return () => { generation++ }
  })

  // 已知族 id 进详情（Task 11 填充）；未知子路径落在总览
  let familyId = $derived(sub && (KNOWN_FAMILIES as readonly string[]).includes(sub) ? sub : null)
</script>

<section class="space-y-4">
  {#if familyId}
    <header class="flex items-center justify-between">
      <h1 class="text-lg font-semibold">{overview?.families.find(card => card.id === familyId)?.title ?? familyId} · 数据族</h1>
      <a class="text-xs text-accent underline" href="#data">返回总览</a>
    </header>
    <p class="text-sm text-muted">族详情与原始数据浏览建设中。</p>
  {:else if error}
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if loading}
    <p class="text-sm text-muted">加载中…</p>
  {:else if overview}
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-lg font-semibold">数据</h1>
        <p class="text-xs text-muted">最近收盘交易日 {overview.session}</p>
      </div>
    </header>
    <p aria-label="证据说明" class="text-xs text-muted border border-border rounded p-2 bg-surface">{overview.evidence}</p>
    {#if !overview.fetch_runs_ready}
      <p class="text-xs text-warn border border-border rounded p-2 bg-surface"><span>迁移 024 未执行</span>：最近拉取不可见，拉取接口不可用。</p>
    {/if}
    <div class="grid gap-3 md:grid-cols-2">
      {#each overview.families as card (card.id)}
        <DataFamilyCard {card} onfetched={load} />
      {/each}
    </div>
  {/if}
</section>
