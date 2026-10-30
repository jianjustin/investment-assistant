<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../api'
  import { actualRText, CARD_STATUS_TEXT, DISCIPLINE_TEXT, endText, growthError, normalizeTicker } from '../growth'
  import type { CardStatus, ReviewCardRow } from '../growth'
  import { rText } from '../workbench'
  import { DataTable } from '$lib/ui/data-table/index'
  import type { Column } from '$lib/ui/data-table/types'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import { Input } from '$lib/ui/input/index'

  // 「复盘 → 复盘卡」列表（spec §4.7）：按结束日倒序；标的 · 结束类型 · 结束日 · 你的决定 · 实际 R（无成交写「未成交」）·
  // 规则 / Agent 轨道 R · 纪律标记（待定的灰显）· 状态 · headline（没有草稿写状态文案）。可按状态、标的筛选。
  let { oncounts }: { oncounts?: (counts: Partial<Record<CardStatus, number>>) => void } = $props()

  const uid = $props.id()
  const SELECT = 'h-8 rounded-md border border-input bg-card px-2 text-sm text-foreground'
  let status = $state('')
  let ticker = $state('')
  let cards = $state<ReviewCardRow[] | null>(null)
  let counts = $state<Partial<Record<CardStatus, number>>>({})
  let error = $state('')
  let generation = 0

  async function load() {
    const token = ++generation
    const params: { status?: string; ticker?: string } = {}
    if (status) params.status = status
    if (ticker) params.ticker = ticker
    try {
      const res = await api.getReviewCards(params)
      if (token !== generation) return
      cards = Array.isArray(res?.cards) ? res.cards : []
      counts = res?.counts ?? {}
      error = ''
      // only an unfiltered read says how many cards are waiting for review
      if (!status && !ticker) oncounts?.(counts)
    } catch (e) {
      if (token !== generation) return
      cards = null
      error = growthError(e)
    }
  }
  onMount(() => { void load() })

  const stateOrder: CardStatus[] = ['to_review', 'reviewed', 'drafting', 'draft_failed']
  const settled = (row: ReviewCardRow) => row.flags.filter(f => !row.immature.includes(f))

  const columns: Column<ReviewCardRow>[] = [
    { key: 'ticker', header: '标的', cell: tickerCell },
    { key: 'end', header: '结束', cell: endCell },
    { key: 'execution', header: '你的执行 / 决定', value: row => row.execution_text ?? row.decision_text },
    { key: 'actual', header: '实际 R', align: 'num', value: row => actualRText(row) },
    { key: 'tracks', header: '规则 / Agent R', cell: tracksCell },
    { key: 'flags', header: '纪律', cell: flagsCell },
    { key: 'status', header: '状态', cell: statusCell },
    { key: 'headline', header: '一句话', cell: headlineCell },
  ]
</script>

{#snippet tickerCell(row: ReviewCardRow)}<a class="text-primary underline" href={`#review/cards/${row.id}`}>{row.ticker}</a>
  {#if row.signal_date}<span class="block text-xs text-muted-foreground">{row.signal_date}</span>{/if}{/snippet}
{#snippet endCell(row: ReviewCardRow)}{endText(row.end_kind, row.exit_basis)}<span class="block text-muted-foreground">{row.end_session}</span>{/snippet}
{#snippet tracksCell(row: ReviewCardRow)}<span class="tabular-nums">规则 {rText(row.rule_r)}</span><span class="block tabular-nums">Agent {rText(row.agent_r)}</span>{/snippet}
{#snippet flagsCell(row: ReviewCardRow)}
  {#each settled(row) as flag (flag)}<span class="mr-1 rounded-sm border border-warn/40 bg-warn/10 px-1 text-foreground">{DISCIPLINE_TEXT[flag] ?? flag}</span>{/each}
  {#each row.immature as flag (flag)}<span data-pending="true" class="mr-1 rounded-sm bg-muted px-1 text-muted-foreground">{DISCIPLINE_TEXT[flag] ?? flag}（待定）</span>{/each}
{/snippet}
{#snippet statusCell(row: ReviewCardRow)}<StatusPill domain="card" value={row.status} />{/snippet}
{#snippet headlineCell(row: ReviewCardRow)}<span data-headline>{row.headline ?? CARD_STATUS_TEXT[row.status] ?? row.status}</span>{/snippet}

<div class="grid gap-3">
  <div class="flex flex-wrap items-end gap-3 text-sm">
    <Field label="状态" id={`${uid}-status`}>
      {#snippet children({ id, describedby })}
        <select {id} aria-describedby={describedby} class={SELECT} bind:value={status} onchange={load}>
          <option value="">全部</option>
          {#each stateOrder as s (s)}<option value={s}>{CARD_STATUS_TEXT[s]}</option>{/each}
        </select>
      {/snippet}
    </Field>
    <Field label="标的" id={`${uid}-ticker`}>
      {#snippet children({ id, describedby })}
        <Input {id} aria-describedby={describedby} class="w-28" value={ticker}
               onchange={(e: Event) => { ticker = normalizeTicker((e.currentTarget as HTMLInputElement).value); void load() }} />
      {/snippet}
    </Field>
    {#if cards}
      <p class="text-xs text-muted-foreground">待审定 {counts.to_review ?? 0} · 已审定 {counts.reviewed ?? 0} · 起草中 {counts.drafting ?? 0}
        · 起草失败 {counts.draft_failed ?? 0}</p>
    {/if}
  </div>

  {#if error}
    <DataBlock state="error" message={error} onRetry={() => void load()} />
  {:else if cards === null}
    <DataBlock state="loading" skeleton="table" />
  {:else if cards.length === 0}
    <DataBlock state="empty" message="还没有复盘卡" />
  {:else}
    <DataTable {columns} rows={cards} rowKey={row => row.id} ariaLabel="复盘卡列表" sticky={false} />
  {/if}
</div>
