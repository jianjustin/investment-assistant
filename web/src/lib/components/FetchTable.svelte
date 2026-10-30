<script lang="ts">
  import { Button } from '$lib/ui/button/index'
  import DataTable from '$lib/ui/data-table/DataTable.svelte'
  import type { Column } from '$lib/ui/data-table/types'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import { failedTargetsFirst } from '../runs'
  import type { FetchFamily, FetchTarget } from '../runs'
  import { fmtBeijing } from '../format'

  // 拉取详情（spec §7.3 ②）：按族分组；目标表默认只展开失败目标，「显示全部 n 个目标」展开全部。
  // 所有文本（含失败原因、error_kind）一律按原文纯文本显示。
  let { families }: { families: FetchFamily[] } = $props()

  const LEGACY_NOTE = '这次运行早于目标级明细（v2.8），只记录了失败的目标'
  let showAll = $state<Record<string, boolean>>({})

  /** Rows of a family: its targets, or (rows older than v2.8) one failed row per recorded failure. */
  function targetsOf(family: FetchFamily): FetchTarget[] {
    if (family.targets && !family.legacy) return family.targets
    return (family.failures ?? []).map(f => ({
      target: f.target, ok: false, attempts: null, error_kind: null, http_status: null, reason: f.reason,
      rows: null, latest: null, elapsed_ms: null,
    }))
  }
  const shown = (family: FetchFamily): FetchTarget[] => {
    const all = failedTargetsFirst(targetsOf(family))
    return showAll[family.family] || family.legacy ? all : all.filter(t => !t.ok)
  }
  const cell = (value: unknown) => value === null || value === undefined || value === '' ? '无' : String(value)
  const resultText = (t: FetchTarget) => t.ok ? '成功'
    : `失败${t.error_kind ? `（${t.error_kind}）` : ''}${t.http_status != null ? ` HTTP ${t.http_status}` : ''}`

  // In a run detail the rows turn into cards on a phone (spec 4.3).
  type Row = FetchTarget & { k: string }
  const columns: Column<Row>[] = [
    { key: 'target', header: '目标', cell: targetCell },
    { key: 'result', header: '结果', cell: resultCell },
    { key: 'attempts', header: '尝试次数', value: t => cell(t.attempts) },
    { key: 'reason', header: '失败原因', cell: reasonCell },
    { key: 'rows', header: '行数', value: t => cell(t.rows) },
    { key: 'latest', header: '最新时点', value: t => cell(t.latest) },
  ]
</script>

{#snippet targetCell(t: Row)}<span class="font-mono">{t.target}</span>{/snippet}
{#snippet resultCell(t: Row)}<StatusPill domain="node" value={t.ok ? 'success' : 'failed'} text={resultText(t)} />{/snippet}
{#snippet reasonCell(t: Row)}<span class="break-all">{cell(t.reason)}</span>{/snippet}

<div class="grid gap-3">
  {#each families as family (family.family)}
    {@const total = targetsOf(family).length}
    {@const list = shown(family)}
    <section aria-label={`拉取 ${family.title}`} class="grid gap-1">
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h4 class="text-sm font-medium">{family.title}</h4>
        <StatusPill domain="run" value={family.status} />
        <span class="text-xs text-muted-foreground">{family.ok_count} / {family.target_count}</span>
        {#if family.started_at || family.finished_at}
          <span class="text-xs text-muted-foreground">{fmtBeijing(family.started_at)} 至 {fmtBeijing(family.finished_at)}</span>
        {/if}
        {#if family.scope}<span class="text-xs text-muted-foreground">范围：{family.scope}</span>{/if}
      </div>
      {#if family.legacy}<p class="text-xs text-muted-foreground">{LEGACY_NOTE}</p>{/if}
      {#if list.length}
        <DataTable {columns} rows={list.map((t, i) => ({ ...t, k: `${t.target}#${i}` }))} rowKey={(t) => t.k} cards="narrow" pageSize={0} sticky={false} />
      {:else if !family.legacy && total > 0}
        <p class="text-xs text-muted-foreground">没有失败的目标</p>
      {/if}
      {#if !family.legacy && family.target_count > total}
        <p class="text-xs text-muted-foreground">共 {family.target_count} 个目标，明细只记录了前 {total} 个</p>
      {/if}
      {#if !family.legacy && total > 0 && total > list.length}
        <div><Button variant="link" size="sm" class="text-xs"
                onclick={() => showAll[family.family] = true}>显示全部 {total} 个目标</Button></div>
      {:else if !family.legacy && showAll[family.family] && total > 0}
        <div><Button variant="link" size="sm" class="text-xs"
                onclick={() => showAll[family.family] = false}>只看失败目标</Button></div>
      {/if}
    </section>
  {/each}
</div>
