<script lang="ts">
  import ConceptTerm from './ConceptTerm.svelte'
  import { DataTable } from '$lib/ui/data-table/index'
  import type { Column, RowGroup } from '$lib/ui/data-table/types'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import PlanLevels from '$lib/ui/domain/PlanLevels.svelte'
  import { ATTACH } from '../knowledge'
  import { fmtBeijing } from '../format'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // 「标的」页计划历史（spec §10.3）：日期 · 链与版本 · 入场 / 止损 / T1 · 变化点（宿主 diff）· 变化原因 · 结束方式。
  // 每条链开头一行 chain_open（写「为什么又开」），结尾一行 chain_end；一条链一组（组头就是链与链之间的分隔，
  // 已结束的链整组置灰）；并入的单元（retrigger）是链内一行。两个开关是请求参数：切换时回调 onToggle，由页面重新请求。
  let { rows, chains = [], ticker = '', includeReviews = false, includeBaselines = false, onToggle }: {
    rows: wb.HistoryRow[]; chains?: wb.HistoryChain[]; ticker?: string
    includeReviews?: boolean; includeBaselines?: boolean
    onToggle?: (next: { include_reviews: boolean; include_baselines: boolean }) => void
  } = $props()

  const I = ATTACH.instrument
  const KIND_TEXT: Record<string, string> = {
    chain_open: '新开链', version: '版本', retrigger: '再次触发', review: '复查', fill: '成交', chain_end: '结束',
  }

  // 按链分组：连续的同链行一组，保持时间顺序（行已按 at 正序）；没有链的行（如规则基线）按原位置自成一组，
  // 不并到别处。
  const groups = $derived.by(() => {
    const out: { signal: string | null; rows: wb.HistoryRow[] }[] = []
    for (const r of rows ?? []) {
      const last = out[out.length - 1]
      if (last && last.signal === r.chain_signal_date) last.rows.push(r)
      else out.push({ signal: r.chain_signal_date, rows: [r] })
    }
    return out
  })

  const md = (d: string) => d.slice(5)
  const chainText = (r: wb.HistoryRow) => r.chain_signal_date
    ? `${ticker ? `${ticker}·` : ''}${md(r.chain_signal_date)}${r.version_no != null ? ` 第 ${r.version_no} 版` : ''}`
    : '无'
  const diffItems = (r: wb.HistoryRow) => (r.diff ?? []).map(d =>
    `${tl.CHANGE_FIELD_TEXT[d.field] ?? d.field} ${tl.diffValueText(d.field, d.before)} → ${tl.diffValueText(d.field, d.after)}`)
  const changeTexts = (r: wb.HistoryRow) => (r.changes ?? []).map(c => (typeof c === 'string' ? c : c.text)).filter(Boolean)
  const signalsText = (r: wb.HistoryRow) => (r.signals_fired ?? []).map(k => tl.SIGNAL_TEXT[k] ?? k).join('、')
  const reasonLine = (r: wb.HistoryRow) => [
    r.decided_by ? (tl.DECIDED_BY_TEXT[r.decided_by as tl.DecidedBy] ?? r.decided_by) : '', r.reason ?? '',
  ].filter(Boolean).join('：')
  const endText = (r: wb.HistoryRow) => {
    if (r.kind !== 'chain_end') return ''
    const end = r.end as { text?: string } | string | null | undefined
    return r.text || (typeof end === 'string' ? end : end?.text ?? '')
  }

  // 链与链之间的分隔用分组：一条链一组（组头是链的名字，已结束的链整组置灰）；没有链的行（规则基线）自成一组。
  type Keyed = wb.HistoryRow & { _k: string }
  const tableGroups = $derived<RowGroup<Keyed>[]>(groups.map((g, gi) => {
    const chain = g.signal ? chains.find(c => c.signal_date === g.signal) : undefined
    return {
      key: `${g.signal ?? ''}|${gi}`,
      label: g.signal ? `${ticker ? `${ticker}·` : ''}${md(g.signal)}` : '无链',
      muted: !!chain && !tl.ACTIVE_STATES.includes(chain.state as tl.ChainState),
      rows: g.rows.map((r, i) => ({ ...r, _k: `${gi}|${r.kind}|${r.at}|${i}` })),
    }
  }))
  const levelNum = (v: string | number | null | undefined) => (v == null ? null : Number(v))
  const columns: Column<Keyed>[] = [
    { key: 'session', header: '日期', cell: dateCell },
    { key: 'chain', header: '链与版本', cell: chainCell },
    { key: 'levels', header: '入场 / 止损 / T1', cell: levelsCell },
    { key: 'diff', header: '变化点', cell: diffCell },
    { key: 'reason', header: '变化原因', cell: reasonCell },
    { key: 'end', header: '结束方式', cell: endCell },
  ]

  // 开关先在本地生效，再通知页面重新请求；页面回传的值覆盖本地值。
  let reviews = $state(false)
  let baselines = $state(false)
  $effect(() => { reviews = includeReviews; baselines = includeBaselines })
  function change() {
    onToggle?.({ include_reviews: reviews, include_baselines: baselines })
  }
</script>

{#snippet dateCell(r: Keyed)}<span class="whitespace-nowrap" data-kind={r.kind}>{r.session}</span>{/snippet}
{#snippet chainCell(r: Keyed)}{chainText(r)}{#if r.kind !== 'chain_open' && r.kind !== 'chain_end'} <span class="text-muted-foreground">{KIND_TEXT[r.kind] ?? r.kind}</span>{/if}{/snippet}
{#snippet levelsCell(r: Keyed)}
  {#if r.levels}<PlanLevels low={levelNum(r.levels.entry_low)} high={levelNum(r.levels.entry_high)} stop={levelNum(r.levels.stop)} target1={levelNum(r.levels.target1)} />{/if}
  {#if r.validity}<span class="block text-muted-foreground">有效期 {r.validity.valid_from} 至 {r.validity.valid_until}</span>{/if}
{/snippet}
{#snippet diffCell(r: Keyed)}{#each diffItems(r) as d, di (di)}<span class="block">{d}</span>{/each}{/snippet}
{#snippet reasonCell(r: Keyed)}
  {#if r.kind === 'chain_open'}
    <span>{r.text}</span>
  {:else if r.kind !== 'chain_end'}
    {#each changeTexts(r) as c, ci (ci)}<span class="block">{c}</span>{/each}
    {#if signalsText(r)}<span class="block text-muted-foreground">触发：{signalsText(r)}</span>{/if}
    {#if reasonLine(r)}<span class="block">{reasonLine(r)}</span>{/if}
    {#if !changeTexts(r).length && !reasonLine(r)}<span class="block">{r.text}</span>{/if}
    <span class="block text-muted-foreground">{fmtBeijing(r.at)}</span>
  {/if}
{/snippet}
{#snippet endCell(r: Keyed)}{#if r.kind === 'chain_end'}<span class="font-medium">{endText(r)}</span>{/if}{/snippet}

<div class="grid gap-2 text-sm">
  <div class="flex flex-wrap items-center gap-4 text-xs">
    <label class="flex items-center gap-1">
      <input type="checkbox" class="size-4 accent-primary" bind:checked={reviews} onchange={change} />
      显示每日维持的复查
    </label>
    <label class="flex items-center gap-1">
      <input type="checkbox" class="size-4 accent-primary" bind:checked={baselines} onchange={change} />
      显示规则基线
    </label>
    <span class="text-muted-foreground"><ConceptTerm id={I.chainState}>链状态说明</ConceptTerm></span>
  </div>

  {#if !rows?.length}
    <DataBlock state="empty" message="该标的还没有计划历史" />
  {:else}
    <div class="overflow-x-auto">
      <div class="min-w-[720px]">
        <DataTable {columns} groups={tableGroups} rowKey={r => r._k} ariaLabel="计划历史" sticky={false} />
      </div>
    </div>
    {#if chains.length}
      <p class="text-xs text-muted-foreground">共 {chains.length} 条链</p>
    {/if}
  {/if}
</div>
